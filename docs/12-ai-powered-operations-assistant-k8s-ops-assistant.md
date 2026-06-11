# Section 12: AI-Powered Operations Assistant (k8s-ops-assistant)

### 12.1 The Problem — Why I Built This

> "Our team has 40+ microservices across 8 environments. When someone asks 'why is pricing-be restarting in QA?', the investigation takes 30-45 minutes: log into Datadog, construct the right query syntax, filter by environment tag, check traces, then switch to kubectl, find the right namespace, describe the pod, check events. Multiply that by 5-10 incidents a week.
>
> I built an AI-powered assistant that takes natural language questions and autonomously investigates using Kubernetes and Datadog APIs. That 30-45 minute investigation now takes under 90 seconds."

---

### 12.2 Architecture — Multi-Agent with Rule-Based Routing

```
┌─────────────────────────────────────────────────────────────┐
│                   DevOps Portal (React 18)                   │
└──────────────────────────┬──────────────────────────────────┘
                           │ POST /v1/chat/stream (SSE)
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                    FastAPI + JWT Auth                         │
│  Security Headers │ Rate Limiting │ Input Guardrails          │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                    SessionManager                            │
│  TTLCache: 1h sessions │ 1,000 concurrent │ Conversation Hx  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│              Orchestrator (Rule-Based, No LLM)               │
│                                                              │
│  Level 1: @mentions     → @datadog → DatadogAgent            │
│                         → @k8s    → K8sAgent                 │
│                         → @cert   → CertAgent                │
│                                                              │
│  Level 2: Keyword score → K8S_INFRA(2.5) > Cert(2.0) > DD(1.5) > K8s(1.0) │
│           K8S_INFRA: postgres/rmq/opensearch/connections/locks│
│                                                              │
│  Level 3: Fallback      → DatadogAgent                       │
└────────┬──────────────────┬──────────────────┬──────────────┘
         │                  │                  │
    ┌────▼────┐       ┌────▼────┐        ┌────▼────┐
    │Datadog  │       │K8s     │        │Cert    │
    │Agent    │       │Agent   │        │Agent   │
    │~20 tools│       │17 tools│        │1 tool  │
    └────┬────┘       └────┬────┘        └────┬────┘
         │                  │                  │
         ▼                  ▼                  ▼
    ┌─────────┐       ┌─────────┐        ┌─────────┐
    │BaseAgent│       │BaseAgent│        │BaseAgent│
    │Loop     │       │Loop     │        │Loop     │
    │(max 10) │       │(max 10) │        │(max 10) │
    └────┬────┘       └────┬────┘        └────┬────┘
         │                  │                  │
    ┌────▼────┐       ┌────▼────┐        ┌────▼────┐
    │Claude   │       │K8s API │        │TLS     │
    │Opus 4.7 │       │(boto3) │        │checker │
    │via TR AI│       │        │        │        │
    │Platform │       │        │        │        │
    └─────────┘       └─────────┘        └─────────┘
```

**Key Design Decisions:**

| Decision | Why |
|----------|-----|
| **Rule-based routing (not LLM)** | Deterministic, fast (~0ms), testable. LLM routing adds 2-3 seconds latency and non-determinism |
| **Multi-agent (not monolithic)** | Single agent with 38 tools confuses Claude. Specialized agents have focused system prompts |
| **10-iteration limit** | Prevents runaway queries and unbounded cost. Most queries complete in 3-5 iterations |
| **Keyword-based model routing** | COMPLEX queries → Opus 4.7, MEDIUM/SIMPLE → Sonnet 4.6. Cost guard: switch to Sonnet above 150K tokens |
| **Prompt caching** | System prompt + tool schemas cached at Anthropic (2 of 4 breakpoints). Saves ~60% on repeated short queries |
| **SSE streaming** | Time-to-first-feedback dropped from 41s (blocking) to <1s. Users see tool calls in real-time |

---

### 12.3 The Agentic Loop — How Claude Reasons

The `BaseAgent` runs an autonomous reasoning loop. Claude decides which tools to call, interprets results, and decides next steps — all without human intervention.

```
User: "Why is pricing-be restarting in QA?"
         │
         ▼
┌─ Iteration 1 ─────────────────────────────────────────────┐
│ Claude thinks: "I need pod status first"                   │
│ Tool call: get_pods(namespace="207804-confirmation-qa",    │
│            label_selector="app=confirmation-pricing-be-qa")│
│ Result: 3 pods, 2 CrashLoopBackOff, 15 restarts           │
└────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ Iteration 2 ─────────────────────────────────────────────┐
│ Claude thinks: "CrashLoopBackOff — need events and logs"   │
│ Tool call: get_pod_events(pod="pricing-be-qa-abc12")       │
│ Result: OOMKilled, Exit code 137, memory limit 1Gi        │
└────────────────────────────────────────────────────────────┘
         │
         ▼
┌─ Iteration 3 ─────────────────────────────────────────────┐
│ Claude thinks: "OOMKilled — let me check Datadog metrics"  │
│ (Orchestrator would route here if cross-agent was enabled) │
│ Claude synthesizes: "pricing-be is OOMKilled because..."   │
│ stop_reason: end_turn → Return response to user            │
└────────────────────────────────────────────────────────────┘
```

**The Loop in Code (Simplified):**

```python
# From framework/base_agent.py
async def handle(self, message: str, history: list) -> str:
    for iteration in range(MAX_ITERATIONS):  # Max 10
        # 1. Call Claude with system prompt + tools + history
        response = await self.llm_client.messages.stream(
            model=self.select_model(history),
            system=self.get_system_prompt(),
            messages=history,
            tools=self.registered_tools,
            max_tokens=16384
        )

        # 2. Check what Claude wants to do
        if response.stop_reason == "end_turn":
            return response.text  # Claude has the answer

        if response.stop_reason == "tool_use":
            # 3. Execute the tool Claude requested
            tool_name = response.tool_use.name
            tool_input = response.tool_use.input
            result = await self.execute_tool(tool_name, tool_input)

            # 4. Add result to history, loop back
            history.append({"role": "assistant", "content": response.content})
            history.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": response.tool_use.id,
                 "content": str(result)}
            ]})
            continue  # Back to step 1

    return "Reached maximum iterations. Here's what I found so far..."
```

---

### 12.4 The Three Agents — Tools & Capabilities

**DatadogAgent (19 Tools):**

| Category | Tools | Example Query |
|----------|-------|---------------|
| **Logs** (4) | `query_logs`, `get_error_logs`, `get_service_logs`, `get_recent_errors_summary` | "Show me errors in pricing-be last 1 hour" |
| **Traces** (5) | `query_traces`, `get_trace_details`, `get_slow_traces`, `correlate_trace_with_logs`, `get_service_dependencies` | "Find slow requests in forms-be" |
| **Metrics** (6) | `query_apm_metrics`, `get_service_health_metrics`, `get_metric_timeseries`, `compare_metrics_across_services`, `get_slo_status`, `discover_service_operation` | "Compare error rates across all services" |
| **Correlation** (4) | `investigate_error_full_context`, `analyze_service_health_unified`, `trace_error_to_root_cause`, `detect_anomalies` | "Investigate why record-gql-be has high latency" |

**K8sAgent (17 Tools — 10 base + 7 infra diagnostics when `ENABLE_INFRA_DIAGNOSTICS=true`):**

| Category | Tool | Purpose |
|----------|------|---------|
| **Core K8s** | `get_pods` | List pods with status, filtering by namespace/labels |
| | `describe_pod` | Detailed pod info (containers, limits, conditions) |
| | `get_pod_events` | Pod failure diagnostics (OOMKill, ImagePull, scheduling) |
| | `get_namespaces` | List available namespaces |
| | `resolve_namespace` | Fuzzy match: "qa" → `207804-confirmation-qa` |
| | `get_hpa_status` | HPA current/desired replicas, scaling events |
| | `get_rollout_status` | Argo Rollout deployment status, canary progress |
| | `get_pvcs` | PersistentVolumeClaim status and capacity |
| | `get_resource_metrics` | CPU/Memory utilization per pod |
| | `search_resources` | Cross-namespace resource search |
| **Infra Diagnostics** | `query_postgresql_diagnostics` | PG connection pools, table sizes, locks, replication lag for any service (32-service DB map) |
| | `query_rabbitmq_diagnostics` | RMQ queue depths, consumer counts, dead-letter queues |
| | `search_opensearch` | Full-text search across OpenSearch indexes |
| | `export_opensearch_csv` | HMAC-signed CSV export for audit compliance — time-bounded, tamper-evident download link |
| | `compare_secret_keys_across_envs` | Diff ExternalSecret key sets between CI/QA/Prod — catches missing keys before deployment |
| | `correlate_infra_with_services` | **Fan-out tool**: hits PG + RMQ + OpenSearch + Datadog in parallel via ThreadPoolExecutor. Returns composite platform health. Latency = max(4 backends) not sum. |
| | `exec_in_container` | Run read-only diagnostic commands inside a pod (e.g., `psql` health checks) |

**CertAgent (1 Tool):**

| Tool | Purpose |
|------|---------|
| `check_certificate_expiry` | Scan multiple domains, report expiry dates, generate PDF report |

---

### 12.5 Token Management & Model Selection

**The Challenge:**

Claude has a 200K token context window. A long investigation with tool results can easily hit this limit.

**Our Strategy:**

```python
# From framework/context_manager.py
def manage_context(history: list, system_prompt: str, tools: list) -> list:
    total_tokens = estimate_tokens(history + [system_prompt] + [tools])

    if total_tokens < 160_000:       # < 80%
        return history               # All good
    elif total_tokens < 190_000:     # 80-95%
        log.warning("Context approaching limit")
        return history               # Still OK
    else:                            # > 95%
        return truncate(history)     # Remove oldest messages

def truncate(history: list) -> list:
    # Always keep: system prompt + tool schemas
    # Always keep: last 6 messages (recent context)
    # Remove: oldest messages first
    # Last resort: truncate large tool results to first+last 4,000 chars
```

**Model Selection (keyword-driven, not context-size-driven):**

| Query Type | Model | Reasoning |
|------------|-------|-----------|
| COMPLEX: investigate/why/root-cause/correlate/anomaly, ambiguous queries | Claude Opus 4.7 | Strongest reasoning; default for quality |
| MEDIUM: show/get/list/check/view logs/errors/pods/traces | Claude Sonnet 4.6 | Fast, cheap for routine lookups |
| SIMPLE: greetings, help | Claude Sonnet 4.6 | Haiku not available at api.anthropic.com |
| Any query >150K tokens (cost guard) | Claude Sonnet 4.6 | Context-size override regardless of complexity |

---

### 12.6 SSE Streaming — Real-Time Feedback

Before streaming, users waited 30-60 seconds staring at a spinner. With SSE, they see every step in real-time:

```
POST /v1/chat/stream
Content-Type: text/event-stream

event: status
data: {"type": "status", "content": "Routing to K8sAgent..."}

event: tool
data: {"type": "tool", "name": "get_pods", "status": "running"}

event: tool
data: {"type": "tool", "name": "get_pods", "status": "done", "summary": "Found 15 pods"}

event: delta
data: {"type": "delta", "content": "I found 3 unhealthy pods in QA..."}

event: delta
data: {"type": "delta", "content": " pricing-be has 15 restarts due to OOMKilled..."}

event: done
data: {"type": "done", "session_id": "sess-abc123"}
```

> "Time-to-first-feedback dropped from 41 seconds to under 1 second. The user sees 'Routing to K8sAgent...', then 'Calling get_pods...', then 'Found 15 pods' — all before Claude even starts writing the final response. This makes the experience feel interactive, not like waiting for a black box."

---

### 12.7 CIAM M2M Authentication — Service-to-Service OAuth2

The assistant needs to call Claude through TR AI Platform. Originally we used an ESSO token (human SSO token) stored in Secrets Manager that expired every hour. I replaced this with **CIAM M2M** (Machine-to-Machine OAuth2).

**Before (ESSO):**

```
Token lifetime: ~1 hour
Rotation: Manual / cron job (update Secrets Manager daily)
Identity: Human user account (bad practice for service)
Failure risk: Token expires → service completely down
```

**After (CIAM M2M):**

```
Token lifetime: 24 hours
Rotation: Auto-refresh at runtime (CIAMTokenClient)
Identity: Service account (OAuth2 client_credentials)
Failure risk: Never expires mid-flight (5-min buffer refresh)
```

**Architecture:**

```
CIAM client_id + client_secret (AWS Secrets Manager)
  → POST auth.thomsonreuters.com/oauth/token (client_credentials grant)
  → 24h JWT (cached in CIAMTokenClient, auto-refresh at 23h 55m)
  → POST TR Common Token API (CIAM JWT → sk-ant-* Anthropic key)
  → api.anthropic.com (Claude)
```

**CIAMTokenClient Design:**

```python
# From clients/ciam_client.py
class CIAMTokenClient:
    REFRESH_BUFFER_SECONDS = 300  # Refresh 5 minutes before expiry

    async def get_token(self) -> str:
        # Cache-first: 99.9% of calls return from memory (~0ms)
        if self._token and time.time() < self._expires_at - self.REFRESH_BUFFER_SECONDS:
            return self._token

        # Fetch new token via OAuth2 client_credentials
        response = await httpx.post(CIAM_TOKEN_URL, data={
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        })
        self._token = response.json()["access_token"]
        self._expires_at = time.time() + response.json()["expires_in"]
        return self._token

    def invalidate(self):
        """Force fresh fetch — used when downstream rejects token"""
        self._token = None
        self._expires_at = 0
```

---

### 12.8 OpenTelemetry Instrumentation

I instrumented the assistant with OTEL at 3 points in the agentic loop:

```python
# Point 1: Agent request lifecycle
with agent_span("handle_request") as span:
    span.set_attribute("agent", "datadog-agent")
    span.set_attribute("request_id", request_id)
    # ... run agentic loop

# Point 2: LLM token tracking (every Claude call)
span.set_attribute("gen_ai.usage.input_tokens", response.usage.input_tokens)
span.set_attribute("gen_ai.usage.output_tokens", response.usage.output_tokens)
span.set_attribute("stop_reason", response.stop_reason)

# Point 3: Tool execution
with agent_span("tool_execution") as tool_span:
    tool_span.set_attribute("tool", tool_name)
    tool_span.set_attribute("iteration", iteration)
    result = await execute_tool(tool_name, tool_input)
    tool_span.set_attribute("duration_ms", elapsed)
```

**Datadog Queries to Verify It's Working:**

```
# Real chat requests (not health checks)
env:ci service:audit-devops-assistant @event:chat_stream_complete

# Follow one request end-to-end
env:ci service:audit-devops-assistant @request_id:<id>

# Tool usage patterns
env:ci service:audit-devops-assistant @event:tool_execution_complete

# Slow requests
env:ci service:audit-devops-assistant @duration_ms:>5000

# Token costs
env:ci service:audit-devops-assistant @gen_ai.usage.input_tokens:>10000
```

---

### 12.8b Cross-Subsystem Fan-Out — `correlate_infra_with_services`

When asked "is the platform healthy?" or "what's the state of demo right now?", the answer spans four subsystems. Instead of letting Claude call four tools sequentially (4 loop iterations, ~15-20s), one tool does the fan-out internally:

```python
# From tools/k8s_tools.py
def correlate_infra_with_services(namespace: str, environment: str):
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(query_postgresql_diagnostics, environment): "postgres",
            executor.submit(query_rabbitmq_diagnostics, namespace): "rabbitmq",
            executor.submit(search_opensearch, environment): "opensearch",
            executor.submit(query_datadog_error_rates, environment): "datadog",
        }
        results = {label: f.result() for f, label in futures.items()}
    return summarize_platform_health(results)
```

**Why one tool instead of four separate tools?**

| Approach | Latency | Token cost | Structure |
|----------|---------|------------|-----------|
| 4 sequential tools via Claude | sum(4 backends) ~15-20s | 4 loop iterations × full context | Claude decides what to check |
| `correlate_infra_with_services` (fan-out) | max(4 backends) ~3-5s | 1 tool result | Always checks all 4, deterministic |

**The tradeoff:** For exploration ("why is pricing-be slow?") — let Claude choose. For surveys ("is the platform healthy?") — fix the shape. This tool is the latter.

---

### 12.8c Proactive Monitoring Subsystem

Beyond answering questions, the assistant has a proactive watchdog that runs on a schedule and posts to Slack/Teams without a user query:

```
┌─────────────────────────────────────────────────────────────┐
│                   Proactive Scheduler                        │
│  Runs every N minutes (configurable)                         │
└──────────────────────────┬──────────────────────────────────┘
                           │ fires pre-configured checks
                           ▼
┌──────────────────────────────────────────────────────────────┐
│              ProactiveAgent (same BaseAgent loop)            │
│  Checks: CrashLoopBackOff pods, pending pods > 5 min,        │
│          cert expiry within 30 days, HPA at max replicas,    │
│          Datadog error rate spike vs baseline                │
└──────────────────────────┬──────────────────────────────────┘
                           │ only if anomaly found
                           ▼
                  Teams / Slack webhook
```

**Interview angle:** This converts the assistant from a reactive Q&A tool into a proactive observability layer. It's the same agentic loop but triggered by a scheduler instead of a user — the architecture doesn't change, the trigger does.

---

### 12.9 Multi-Tenant Portability

The assistant is designed so any TR team can onboard with zero code changes:

```bash
# New team onboarding: CIAM M2M is the primary auth (ESSO is legacy fallback)
CIAM_CLIENT_ID=<id>         # Primary: service-account credentials
CIAM_CLIENT_SECRET=<secret> # Primary: auto-refreshing, 24h token lifetime
DD_API_KEY=<key>
DD_APP_KEY=<key>
NAMESPACE_PREFIX=207804     # Their asset ID

# Optional: enable/disable agents
ENABLE_DATADOG_AGENT=true
ENABLE_K8S_AGENT=true
ENABLE_CERT_AGENT=false

# Optional: customize indexes, services
DD_LOG_INDEXES=their-index-1,their-index-2
SERVICES=their-svc-1,their-svc-2
```

> "All configuration is externalized via Pydantic Settings. Agent system prompts are built dynamically at startup from the config. Feature flags control which agents are available. A new team can clone the repo, fill 4 env vars, and have a working assistant for their namespace — no code changes needed."

---

### 12.10 Software 3.0 — How to Explain This in an Interview

| Paradigm | Approach | Example |
|----------|----------|---------|
| **Software 1.0** | Explicit rules | `if "pods" in query: get_pods()` — brittle, can't handle variations |
| **Software 2.0** | ML-trained patterns | Train classifier on incident data — needs labeled data, retraining |
| **Software 3.0** | Natural language reasoning | "Investigate why service has errors" → Claude autonomously decides tools |

> "We provide 38 tools (capabilities), domain context via system prompts, and real-time data access. Claude autonomously determines which tools to invoke, in what sequence, and how to synthesize results. We don't prescribe investigation workflows — the AI reasons about the best approach for each unique question. This is why it can handle questions it's never seen before."

**What the AI CANNOT Do (Interview Safety Question):**

| Capability | Allowed? |
|-----------|---------|
| Read pod status, logs, events | Yes |
| Query Datadog logs, traces, metrics | Yes |
| Check certificate expiry | Yes |
| Delete pods, scale deployments | **NO** — read-only operations only |
| Access secrets/configmaps content | **NO** — not authorized |
| Modify cluster configuration | **NO** — investigation only |
| Run arbitrary kubectl commands | **NO** — predefined tools only |

---

### 12.11 Interview Scenario Questions

**Q: "Explain the architecture of your AI operations assistant"**

> "It's a multi-agent system with rule-based routing. User queries come through a FastAPI REST API with JWT auth. The orchestrator uses a 3-level routing strategy — explicit @mentions first, then weighted keyword scoring (Cert 2.0 > Datadog 1.5 > K8s 1.0), then default to Datadog. Each agent runs an autonomous reasoning loop: Claude receives the question plus available tools, decides which tool to call, interprets the result, and either calls another tool or returns the final answer. Maximum 10 iterations per request.
>
> The key architectural decision was rule-based routing instead of LLM routing. It's deterministic, adds zero latency, and is fully testable. We tested LLM routing early on and it added 2-3 seconds per query for no quality improvement — the keyword scoring is accurate enough."

**Q: "How do you prevent the AI from hallucinating?"**

> "Three mechanisms:
> 1. **Grounded responses** — every answer must come from real API calls. Claude's system prompt says 'only answer based on tool results, never guess.' If a tool returns 'no pods found', Claude says that — it doesn't make up pod names.
> 2. **Tool-based architecture** — Claude can only access data through our predefined tools. It can't browse the internet, access arbitrary files, or call APIs we didn't define. The tool schema constrains what's possible.
> 3. **Output guardrails** — even if Claude accidentally includes something sensitive, the output sanitizer redacts passwords, API keys, SSNs, and credit card numbers before the response reaches the user."

**Q: "What would you improve about this system?"**

> "Three things on the roadmap:
> 1. **Cross-agent queries** — right now, each query routes to ONE agent. If someone asks 'why is pricing-be slow and are there OOMKills?', it goes to Datadog OR K8s, not both. The `handle_complex()` method exists in the orchestrator but it's dead code — never called. Implementing it would let us chain Datadog + K8s results in a single response.
> 2. **Vector database for similar incidents** — store past investigations with their root causes. When a similar pattern appears, the assistant could say 'this looks like the MassTransit consumer issue from February (INC-001)' with the previous resolution steps.
> 3. **Complexity-based model routing** — simple queries like 'list pods in QA' don't need Opus. Route simple→Haiku, medium→Sonnet, complex→Opus. Would cut costs by 60% based on our query distribution."

**Q: "How do you handle the cost of using Claude for every query?"**

> "Several strategies:
> 1. **Model selection by context size** — Opus for complex (< 150K tokens), Sonnet for long conversations (150K-180K). Opus costs 5x more per token.
> 2. **Focused tool sets** — each agent only sends its own tools to Claude (19 for Datadog, 10 for K8s, 1 for Cert). Fewer tools = fewer tokens in every API call.
> 3. **Context truncation** — when conversations get long, we remove oldest messages while preserving the last 6 exchanges. This keeps token usage bounded.
> 4. **OTEL tracking** — we log `input_tokens` and `output_tokens` on every LLM call to Datadog. I can query `@gen_ai.usage.input_tokens:>10000` to find expensive queries and optimize.
> 5. **Session TTL** — sessions expire after 1 hour, preventing unbounded history growth."

---
