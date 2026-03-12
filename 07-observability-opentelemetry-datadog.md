# Section 7: Observability — OpenTelemetry & Datadog

### 7.1 Why Observability Matters (The Three Pillars)

Observability answers: **"What is happening inside my system right now, and why?"**

| Pillar | What It Is | Tool We Use | Example |
|--------|-----------|-------------|---------|
| **Logs** | Discrete events with context | Datadog Log Management | `"error": "connection refused", "service": "pricing-be", "env": "qa"` |
| **Traces** | Request journey across services | Datadog APM + OpenTelemetry | Request → API Gateway → Pricing → DB → Response (with timing) |
| **Metrics** | Aggregated measurements over time | Datadog Metrics + Prometheus | CPU usage 75%, request latency p99 = 2.3s, error rate 0.5% |

**Interview distinction:**
- **Monitoring** = "Is the system up?" (dashboards, alerts)
- **Observability** = "Why is the system slow/broken?" (drill into any request, any service, any time)

You need all 3 pillars together. Logs without traces = you know something failed but can't follow the request. Traces without metrics = you can debug one request but miss system-wide patterns. Metrics without logs = you know latency spiked but can't find the root cause.

---

### 7.2 Our Observability Architecture

```
┌───────────────────────────────────────────────────────┐
│  EKS Pod                                              │
│  ┌─────────────────┐  ┌──────────────────────┐        │
│  │ App Container    │  │ Istio Sidecar        │        │
│  │ (.NET / Python)  │  │ (Envoy proxy)        │        │
│  │                  │  │                      │        │
│  │ Structured JSON  │  │ Access logs          │        │
│  │ logs → stdout    │  │ mTLS metrics         │        │
│  │                  │  │                      │        │
│  │ DD_AGENT_HOST ───┼──┼─► Datadog Agent      │        │
│  │ port 8126 (APM)  │  │   (DaemonSet)        │        │
│  │ port 4317 (OTEL) │  │   on each EKS node   │        │
│  └─────────────────┘  └──────────────────────┘        │
└───────────────────────────────────────────────────────┘
         │                        │
         │  Traces + Logs         │  Node metrics
         ▼                        ▼
┌─────────────────────────────────────────────────────┐
│  Datadog Agent DaemonSet (per node)                  │
│  ├── Collects logs from pod stdout (container log)   │
│  ├── Receives APM traces on port 8126                │
│  ├── Receives OTEL spans on port 4317 (gRPC)        │
│  ├── Scrapes Prometheus /metrics endpoint            │
│  └── Sends everything → intake.datadoghq.com (HTTPS)│
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│  Datadog Backend                                     │
│  ├── Log Management (search, filter, alerts)         │
│  ├── APM (flame graphs, service map, latency)        │
│  ├── Metrics (dashboards, monitors, SLOs)            │
│  └── Infrastructure (host map, container view)       │
└─────────────────────────────────────────────────────┘
```

**Key infrastructure fact**: The Datadog Agent runs as a **DaemonSet** — one pod per EKS worker node. Every application pod on that node sends data to the local agent via `DD_AGENT_HOST` (the node's IP). This avoids cross-node network hops.

---

### 7.3 How Our 40+ Services Send Data to Datadog

Every service in our platform gets these Datadog environment variables in their Helm rollout.yaml:

```yaml
# Common across ALL 40+ services (Python + .NET)
env:
  - name: DD_AGENT_HOST
    valueFrom:
      fieldRef:
        fieldPath: status.hostIP          # Node IP where DD agent runs
  - name: DD_SERVICE
    value: {{ .Chart.Name }}              # e.g., "confirmation-pricing-be"
  - name: DD_ENV
    value: {{ .Values.environment }}      # ci, demo, qa, preprod
  - name: DD_VERSION
    value: "v{{ .Chart.AppVersion }}"     # Semantic version
  - name: DD_TAGS
    value: "layer:api,team:devops,asset:207804"
  - name: DD_TRACE_SAMPLE_RATE
    value: "1"                            # 100% trace sampling
  - name: DD_LOGS_INJECTION
    value: "true"                         # Inject trace_id into logs
  - name: DD_PROFILING_ENABLED
    value: "true"                         # CPU/memory profiling
  - name: DD_TRACE_AGENT_PORT
    value: "8126"                         # APM trace port
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: "http://$(DD_AGENT_HOST):4317" # OpenTelemetry gRPC endpoint
```

**Python vs .NET instrumentation difference:**

| Aspect | .NET Services (30+ services) | Python Services (6 services) |
|--------|----------------------------|------------------------------|
| **Instrumentation** | Automatic — CLR profiler hooks into runtime | Manual — explicit OTEL SDK calls |
| **Tracer** | Datadog .NET tracer (`/opt/datadog/`) | OpenTelemetry Python SDK |
| **Profiler** | CLR profiler (`CORECLR_PROFILER`) | Native Python profiler |
| **Extra env vars** | `CORECLR_ENABLE_PROFILING=true`, `CORECLR_PROFILER_PATH`, `DD_DOTNET_TRACER_HOME` | None (OTEL SDK configured in code) |
| **Log injection** | Automatic (DD tracer injects `dd.trace_id`) | Needs `ddtrace-run` wrapper |
| **Trace port** | 8126 (DD native) | 8126 (DD native) + 4317 (OTEL gRPC) |

---

### 7.4 OpenTelemetry — What I Built for k8s-ops-assistant

**What is OpenTelemetry (OTEL)?**

OpenTelemetry is a **vendor-neutral** observability framework. Instead of coding directly to Datadog's SDK (vendor lock-in), you code to OTEL's SDK and export to any backend — Datadog, Grafana, Jaeger, New Relic, etc.

```
Your Code → OTEL SDK → OTLP Protocol → Any Backend
                                         ├── Datadog
                                         ├── Grafana/Tempo
                                         ├── Jaeger
                                         └── New Relic
```

**Why this matters for interview:**
> "We chose OpenTelemetry over Datadog's native SDK because it's vendor-neutral. If we ever need to switch from Datadog to Grafana Stack, we change one environment variable (`OTEL_EXPORTER_OTLP_ENDPOINT`) — zero code changes."

**What I instrumented in the AI assistant:**

I added 3 instrumentation points in `base_agent.py`:

| Point | Span Name | What It Captures |
|-------|-----------|-----------------|
| **Top-level request** | `devops_assistant.agent.handle` | Total request duration, agent name, request_id, model |
| **LLM call** | `devops_assistant.agent.llm_call` | Iteration count, input/output tokens, LLM latency, model |
| **Tool execution** | `devops_assistant.agent.tool_call` | Tool name, duration, success/error, iteration |

**Span hierarchy (what you see in Datadog APM):**
```
devops_assistant.agent.handle (4200ms total)
  ├── devops_assistant.agent.llm_call (790ms, iteration=1, tokens_in=4821, tokens_out=180)
  ├── devops_assistant.agent.tool_call (1840ms, tool=query_logs, status=success)
  └── devops_assistant.agent.llm_call (1520ms, iteration=2, tokens_in=7200, tokens_out=640)
```

**The `agent_span()` context manager:**
```python
# framework/telemetry.py — helper for clean instrumentation
@contextmanager
def agent_span(name, attributes=None):
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, v)
        try:
            yield span
            span.set_status(StatusCode.OK)
        except Exception as e:
            span.set_status(StatusCode.ERROR, str(e))
            span.record_exception(e)
            raise
```

**How it's used in `base_agent.py`:**
```python
# Instrumentation point 1: Top-level request
async def handle(self, query, request_id):
    with agent_span("devops_assistant.agent.handle", {
        "agent.name": self.agent_name,
        "request.id": request_id,
        "gen_ai.request.model": self.model,
    }) as span:
        # ... agent loop runs here ...
        span.set_attribute("duration_ms", elapsed)

# Instrumentation point 2: LLM call
with agent_span("devops_assistant.agent.llm_call", {
    "agent.iteration": iteration,
    "gen_ai.system": "anthropic",
    "gen_ai.usage.input_tokens": usage.input_tokens,
    "gen_ai.usage.output_tokens": usage.output_tokens,
}) as span:
    response = await self.client.messages.create(...)

# Instrumentation point 3: Tool execution
with agent_span("devops_assistant.agent.tool_call", {
    "tool.name": tool_name,
    "agent.iteration": iteration,
}) as span:
    result = await tool_function(**args)
    span.set_attribute("tool.status", "success")
    span.set_attribute("tool.duration_ms", elapsed)
```

**Dual exporter modes:**

| Mode | When | Config |
|------|------|--------|
| **OTLP/gRPC** (production) | `OTEL_EXPORTER_OTLP_ENDPOINT` is set | Sends to Datadog Agent port 4317 |
| **Console** (debug) | `OTEL_CONSOLE_SPANS=true` | Prints JSON spans to stdout |
| **Silent** (default) | Neither set | Spans created but not exported (zero overhead) |

---

### 7.5 Structured Logging (JSON to Datadog)

**Why structured logging matters:**

```
# BAD — unstructured log (grep-able, not queryable)
2026-03-10 14:30:22 INFO Processing request for user john

# GOOD — structured JSON (fully queryable in Datadog)
{"timestamp": "2026-03-10T14:30:22Z", "level": "INFO", "event": "chat_stream_complete",
 "request_id": "req-abc123", "duration_ms": 4200, "agent": "datadog", "model": "opus-4.5"}
```

**Our implementation (`main.py` → `JSONFormatter`):**
```python
class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Add all extra fields (event, request_id, duration_ms, etc.)
        for key, value in record.__dict__.items():
            if key not in standard_fields:
                log_entry[key] = value
        return json.dumps(log_entry)
```

**Request ID propagation** — every log line for a request shares the same ID:
```python
# Middleware generates request_id for every HTTP request
request_id = f"req-{uuid.uuid4().hex[:12]}"
request_id_var.set(request_id)  # ContextVar — available everywhere in this request
response.headers["X-Request-ID"] = request_id  # Returned to client
```

**Key log events we emit:**

| Event | When | Useful Fields |
|-------|------|--------------|
| `chat_stream_complete` | Chat request finished | `duration_ms`, `agent`, `model`, `request_id` |
| `agent_request_start` | Agent begins processing | `agent`, `query`, `request_id` |
| `tool_execution_complete` | Tool finished | `tool`, `duration_ms`, `iteration`, `status` |
| `tool_execution_error` | Tool failed | `tool`, `error`, `iteration` |
| `llm_response` | Claude responded | `stop_reason`, `tool_calls_count`, `tokens` |
| `llm_api_error` | Claude API failed | `status_code`, `error_body` |

---

### 7.6 Prometheus Metrics (The Third Pillar)

We also expose a `/metrics` endpoint for Prometheus-format metrics. Datadog Agent scrapes this.

```python
# api/metrics.py — metric definitions
from prometheus_client import Counter, Histogram, Gauge

# Request metrics
chat_requests_total = Counter("chat_requests_total", "Total chat requests", ["status", "agent"])
chat_request_duration = Histogram("chat_request_duration_seconds", "Chat latency",
    ["agent"], buckets=[1, 2, 5, 10, 30, 60, 120])

# LLM metrics
llm_calls_total = Counter("llm_calls_total", "Claude API calls", ["model", "status"])
llm_call_duration = Histogram("llm_call_duration_seconds", "LLM latency",
    ["model"], buckets=[0.5, 1, 2, 5, 10, 30, 60])
llm_tokens_total = Counter("llm_tokens_total", "Token usage", ["direction"])  # input/output

# Tool metrics
tool_calls_total = Counter("tool_calls_total", "Tool executions", ["tool_name", "status"])
tool_call_duration = Histogram("tool_call_duration_seconds", "Tool latency",
    ["tool_name"], buckets=[0.1, 0.5, 1, 2, 5, 15, 30])

# Session metrics
active_sessions = Gauge("active_sessions", "Current concurrent sessions")
```

**Why both OTEL traces AND Prometheus metrics?**

| OTEL Traces | Prometheus Metrics |
|-------------|-------------------|
| **Per-request** detail (drill into ONE slow request) | **Aggregated** view (what's the p99 latency across ALL requests?) |
| Flame graphs, span trees | Time-series graphs, dashboards |
| "Why was this specific request slow?" | "Is the system getting slower over time?" |

---

### 7.7 Datadog Queries I Use Daily

These are the queries I run constantly — **memorize these for the interview**:

```bash
# 1. Find all real chat requests (filter out health checks and noise)
env:ci service:audit-devops-assistant @event:chat_stream_complete

# 2. Follow one request end-to-end (every log line for that request)
env:ci service:audit-devops-assistant @request_id:req-abc123def456

# 3. Agent + tool activity (see what the AI actually did)
env:ci service:audit-devops-assistant @event:(agent_request_start OR tool_execution_complete)

# 4. Errors only (skip NeMo guardrails FutureWarning noise)
env:ci service:audit-devops-assistant status:error -message:FutureWarning

# 5. All structured logs (filter out raw uvicorn access lines)
env:ci service:audit-devops-assistant @event:*

# 6. Slow requests (> 5 seconds)
env:ci service:audit-devops-assistant @duration_ms:>5000

# 7. Token cost tracking
env:ci service:audit-devops-assistant @event:llm_response @gen_ai.usage.input_tokens:>1000
```

**Query syntax breakdown:**

| Pattern | Meaning |
|---------|---------|
| `env:ci` | Environment tag = ci |
| `service:pricing-be` | Service tag (DD_SERVICE env var) |
| `@event:chat_stream_complete` | Facet search on structured field |
| `status:error` | Log level = ERROR |
| `-message:FutureWarning` | Exclude lines containing "FutureWarning" |
| `@duration_ms:>5000` | Numeric facet filter (greater than 5000ms) |

**Important gotcha**: Datadog uses **`env:` tags, NOT `kube_namespace:`** for filtering:
```python
# CORRECT
query = f"env:{environment} service:{service_name}"

# WRONG (old pattern, doesn't work)
query = f"kube_namespace:207804-confirmation-qa service:{service_name}"
```

**Service name gotcha for .NET services:**
```
# .NET service "pricing-be" → Datadog tag is "confirmation-pricing-be"
# Our Python service → Datadog tag is "audit-devops-assistant" (matches directly)
```

---

### 7.8 What OTEL Gave Us (Before vs After)

| Capability | Before OTEL | After OTEL |
|-----------|------------|-----------|
| Spot real requests in log noise | 50 logs, all look identical | `@event:chat_stream_complete` → instantly find real requests |
| Request duration | Invisible | `duration_ms: 10098.99` on every chat response |
| Follow one request | Impossible | `@request_id:<id>` pulls every log line for that request |
| Find slow requests | Manual grep | `@duration_ms:>5000` query |
| Agent/tool activity | None | `@event:tool_execution_complete` → tool name, iteration, duration |
| Token costs | None | `gen_ai.usage.input_tokens` per LLM call |
| Error root cause | Read full log dump | Exception stack trace attached to span |

**Interview Answer:**

> "Before I added OpenTelemetry, debugging the AI assistant meant reading raw log dumps. After OTEL, I can trace any request end-to-end — I see exactly how long the LLM call took, which tool was invoked, how many tokens were used, and where time was spent. If a request is slow, I query `@duration_ms:>5000` in Datadog and immediately see the flame graph showing the bottleneck — whether it's the Claude API, a Datadog log query, or a Kubernetes API call."

---

### 7.9 The Data Flow — All Three Pillars Together

**A real request through the observability pipeline:**

```
1. User asks: "Why is pricing-be restarting in QA?"
   │
2. FastAPI middleware:
   │  → Generates request_id: req-7f3a2b
   │  → Logs: {"event": "request_start", "request_id": "req-7f3a2b"}    ← LOG
   │  → Increments: chat_requests_total{agent="datadog"}                 ← METRIC
   │
3. Orchestrator routes to DatadogAgent
   │  → Logs: {"event": "agent_request_start", "agent": "datadog"}       ← LOG
   │  → Creates OTEL span: devops_assistant.agent.handle                 ← TRACE
   │
4. LLM call to Claude:
   │  → Creates OTEL span: devops_assistant.agent.llm_call               ← TRACE
   │  → span attributes: tokens_in=4821, tokens_out=180, duration=790ms
   │  → Increments: llm_calls_total{model="opus-4.5"}                   ← METRIC
   │  → Increments: llm_tokens_total{direction="input"} += 4821         ← METRIC
   │
5. Claude says: "Call query_logs tool"
   │  → Creates OTEL span: devops_assistant.agent.tool_call              ← TRACE
   │  → Calls Datadog API: query_logs("env:qa service:confirmation-pricing-be status:error")
   │  → Logs: {"event": "tool_execution_complete", "tool": "query_logs", "duration_ms": 1840}  ← LOG
   │  → Increments: tool_calls_total{tool="query_logs", status="success"}                       ← METRIC
   │  → Records: tool_call_duration{tool="query_logs"}.observe(1.84)                            ← METRIC
   │
6. Response streamed back:
   │  → Logs: {"event": "chat_stream_complete", "duration_ms": 4200}     ← LOG
   │  → Closes top-level OTEL span (4200ms total)                        ← TRACE
   │  → Records: chat_request_duration{agent="datadog"}.observe(4.2)     ← METRIC
```

**In Datadog, all 3 pillars are correlated:**
- **Logs**: `@request_id:req-7f3a2b` → shows every log line for this request
- **Traces**: Flame graph shows handle → llm_call → tool_call → llm_call
- **Metrics**: Dashboard shows this request contributed to the p99 latency spike

---

### 7.10 Datadog Log Indexes

**What are log indexes?**

Datadog routes logs to different indexes based on filters. Each index has its own retention period and query performance. Our platform uses:

| Index | What Goes In | Retention |
|-------|-------------|-----------|
| `a207804-k8s-logs-preprod` | All K8s pod logs from non-prod clusters | 15 days |
| `a209014-ait-demo-preprod` | AIT team demo/preprod logs | 15 days |

When querying, you must specify which index to search (or query all — slower):
```python
# Our Datadog tools query both indexes by default
DEFAULT_INDEXES = ["a207804-k8s-logs-preprod", "a209014-ait-demo-preprod"]
```

---

### 7.11 Volume Mounts for Observability

One gotcha with Datadog on read-only filesystem pods — the tracer needs a writable temp directory:

```yaml
# In rollout.yaml — every service needs this
volumeMounts:
  - name: datadog-temp
    mountPath: /tmp-datadog         # DD_TRACE_LOG_DIRECTORY points here
  - name: api-temp
    mountPath: /tmp                 # General temp (uvicorn, etc.)
volumes:
  - name: datadog-temp
    emptyDir: {}                    # Writable emptyDir on read-only FS
  - name: api-temp
    emptyDir: {}
```

**Why?** Our security standard is `readOnlyRootFilesystem: true`. But the Datadog tracer writes temporary files. Solution: mount `emptyDir` volumes at `/tmp` and `/tmp-datadog`. The data lives in the node's memory, not on disk, and is wiped when the pod dies.

---

### 7.12 Known Gap — Trace-to-Log Linking

**Current state**: OTEL spans exist in Datadog APM, structured logs exist in Datadog Log Management, but they're **not linked** in the flame graph UI.

**Root cause**: The Python application needs `ddtrace-run` wrapper to inject `dd.trace_id` into log output. Without it, Datadog can't correlate logs to specific traces.

**Fix needed** (in Helm rollout.yaml + Dockerfile):
```yaml
# Helm rollout.yaml — add if not present
- name: DD_LOGS_INJECTION
  value: "true"

# Dockerfile CMD — wrap with ddtrace-run
CMD ["ddtrace-run", "uvicorn", "audit_devops_assistant.api.main:app", ...]
```

This is a good interview talking point — shows you understand the gap AND know the fix.

---

### 7.13 Interview Questions — Scenario-Based

**Q: "A service is throwing 500 errors in production. Walk me through how you debug it."**

> "1. **Datadog Log Management**: Query `env:prod service:confirmation-pricing-be status:error` — find the error messages and stack traces
> 2. **Request ID**: Pick one error, grab the `request_id`, then query `@request_id:<id>` — see the full request lifecycle
> 3. **APM Flame Graph**: If traces are linked, click into the trace — see exactly which span failed and how long each step took
> 4. **Metrics Dashboard**: Check `chat_requests_total{status=error}` — is this a spike or constant? When did it start?
> 5. **Compare**: Check if the error correlates with a deployment (DD_VERSION tag), a config change, or an upstream dependency failure
> 6. **Kubernetes**: If it's a pod issue (OOMKilled, CrashLoopBackOff), check `kubectl describe pod` and events"

**Q: "How do you monitor a canary deployment?"**

> "During canary, Argo Rollout shifts 50% traffic to the new version. I monitor in Datadog:
> 1. **Error rate by version**: `env:ci service:pricing-be @dd.version:v1.2.3 status:error` — compare new vs old
> 2. **Latency by version**: Datadog APM shows latency distribution split by version tag
> 3. **Custom metrics**: Our Prometheus metrics track `chat_request_duration` with version labels
> 4. **If errors spike**: Abort the rollout (`kubectl argo rollouts abort <name>`), Argo automatically shifts 100% back to stable
> 5. **Auto-rollback**: We could add Datadog analysis to the Rollout strategy — Argo supports Datadog metric queries as promotion criteria"

**Q: "Explain the difference between Datadog APM and OpenTelemetry."**

> "Datadog APM is a **product** — it's where you view traces, flame graphs, service maps. OpenTelemetry is a **standard** — it's how your application generates and exports trace data.
>
> They're complementary, not competing. We use OTEL SDK in our code to create spans, then export via OTLP gRPC to the Datadog Agent, which forwards to Datadog APM backend. If we ever switch to Grafana Tempo, we change one env var — the OTEL SDK stays the same.
>
> For .NET services, Datadog's auto-instrumentation (CLR profiler) is easier — no code changes needed. For Python, we chose OTEL because it gives us custom span attributes like `gen_ai.usage.input_tokens` that Datadog's auto-instrumentation wouldn't capture."

**Q: "How do you handle log volume and cost in Datadog?"**

> "Datadog charges by log volume (GB ingested). We control cost through:
> 1. **Structured logging**: Only emit meaningful events with `@event:` tags — no raw debug output in production
> 2. **Log indexes**: Different indexes with different retention — production gets 30 days, non-prod gets 15 days
> 3. **Exclusion filters**: Filter out noisy logs before they hit the index (e.g., health check 200s, uvicorn access logs)
> 4. **Sampling**: `DD_TRACE_SAMPLE_RATE=1` in non-prod (100%), could reduce in prod if volume is too high
> 5. **Archive**: Old logs go to S3 (Datadog Archives) for compliance — cheaper than keeping in hot index"

**Q: "Your Datadog dashboard shows a latency spike. How do you find the root cause?"**

> "1. **Time range**: Narrow the dashboard to when the spike started
> 2. **Service map**: Check Datadog APM service map — is the latency in our service or an upstream dependency?
> 3. **Traces**: Sort traces by duration (descending) — find the slowest requests
> 4. **Flame graph**: Open a slow trace — see which span took the most time. Is it the LLM call? A database query? A tool execution?
> 5. **Correlate**: Check if the spike matches a deployment (version tag change), a cloud event (EKS scaling), or an external dependency (Claude API latency)
> 6. **Metrics**: Check CPU/memory metrics for the pod — if it's resource-constrained, the HPA should have scaled up. If HPA maxReplicas hit, that's the bottleneck."

**Q: "How would you set up observability for a new microservice from scratch?"**

> "1. **Structured logging**: JSON formatter to stdout — Datadog Agent collects automatically from container logs
> 2. **Datadog env vars**: Add DD_SERVICE, DD_ENV, DD_VERSION, DD_AGENT_HOST to the Helm rollout.yaml — copy from existing service template
> 3. **Trace instrumentation**: For Python, add OTEL SDK + `agent_span()` for critical code paths. For .NET, just set `CORECLR_ENABLE_PROFILING=true` — auto-instrumented
> 4. **Prometheus metrics**: Add a `/metrics` endpoint with counters/histograms for key operations
> 5. **Volume mounts**: Add `emptyDir` at `/tmp` and `/tmp-datadog` for read-only filesystem compatibility
> 6. **Verify**: Deploy to CI, query `env:ci service:<name>` in Datadog — should see logs immediately. Check APM for traces.
> 7. **Dashboard**: Create a Datadog dashboard with error rate, latency p99, request volume, resource usage"

**Q: "What's the difference between ELK Stack and Datadog?"**

> "I've used both — ELK at Arrise and Datadog at Thomson Reuters.
>
> | Aspect | ELK Stack | Datadog |
> |--------|-----------|---------|
> | **Hosting** | Self-hosted (we managed Elasticsearch, Logstash, Kibana) | SaaS (managed by Datadog) |
> | **Cost model** | Infrastructure cost (EC2, storage) | Per-host + per-GB ingested |
> | **Logs** | Excellent (Elasticsearch is built for log search) | Excellent (with faceted search) |
> | **APM/Traces** | Separate setup (Jaeger, Elastic APM) | Built-in, unified with logs |
> | **Metrics** | Separate (Prometheus/Grafana alongside) | Built-in, unified |
> | **Ops overhead** | High (index management, shard rebalancing, upgrades) | Zero (SaaS) |
> | **Scale** | You manage scaling (adding nodes, tuning JVM) | Automatic |
>
> Datadog wins for teams that want all 3 pillars unified with zero ops overhead. ELK wins if you need full control and want to minimize SaaS costs at scale."

---
