# Section 15: System Design — CS Vocabulary & HLD Concepts

> **Purpose:** Two things in one doc.
> 1. Map every design decision in the DevOps assistant to its proper CS name — so in interviews you use the right terminology for what you built.
> 2. Cover the High Level Design topics from Scaler Module 13 — with your own system as the running example.
>
> **Frame:** You built a production multi-agent LLM system. Every HLD concept appears in it. Don't study these as abstract theory — anchor each one to something you shipped.

---

## Part 1 — What You Built, Named in CS Terms

### 1.1 Multi-Agent Architecture

**What you built:** Orchestrator → three specialist agents (Datadog, K8s, Cert)

**CS names:**
- **Multi-Agent Architecture** — multiple autonomous agents, each with bounded responsibility
- **Router / Dispatcher Pattern** — rule-based selector that routes to the right handler
- **Separation of Concerns (SoC)** — each component has one reason to change

**Interview framing:** "I applied the Single Responsibility Principle at the agent layer. Each agent has one domain, one system prompt, one tool set."

**Alternative — LLM-based routing:**
- More flexible, handles ambiguous queries
- Adds ~2s latency and frontier-model cost on every request
- For 90%+ of queries in a known domain, rule-based wins on latency + testability

---

### 1.2 The ReAct Pattern (Reasoning + Acting)

**What you built:** `BaseAgent.handle()` — loop that calls Claude → gets `tool_use` → executes tool → feeds result back → repeats until `end_turn`

**CS name:** **ReAct (Yao et al. 2022)** — Think → Act → Observe loop.

In Claude's API: `stop_reason: tool_use` = Think+Act. `tool_result` = Observe. `stop_reason: end_turn` = done.

**Why max 10 iterations?** Two reasons: cost (each iteration = full Claude call with growing history) and latency (each round-trip is 3-8s). A query that can't converge in 10 steps needs human escalation.

---

### 1.3 REST + Server-Sent Events (SSE)

**What you built:** `POST /v1/chat/stream` returning `text/event-stream`

**CS names:**
- **REST** — stateless, resource-oriented HTTP API style
- **SSE (Server-Sent Events)** — HTTP/1.1 unidirectional streaming
- **Chunked Transfer Encoding** — HTTP mechanism that lets the body arrive in pieces
- **Async I/O** — FastAPI + asyncio handles multiple SSE streams on one thread via event loop

**SSE vs WebSocket:**

| | SSE | WebSocket |
|---|---|---|
| Direction | Server → Client only | Bidirectional |
| Protocol | HTTP/1.1 — works through proxies, CDNs | WS upgrade — may break at proxies |
| Reconnect | Built-in browser auto-reconnect | Manual |
| Your use case | ✅ Streaming tokens back | Overkill |

For LLM token streaming, SSE is the industry standard. OpenAI and Anthropic both use it.

---

### 1.4 Authentication — Defense in Depth (3 layers)

**What you built:** JWT RS256 inbound → CIAM M2M outbound → TR Common Token API

**CS names:**
- **JWT (JSON Web Token)** — stateless auth token. `header.payload.signature`. RS256 = RSA asymmetric signing.
- **OAuth 2.0 Client Credentials Grant** — M2M flow. `client_id + client_secret → access_token`. No user involved.
- **Token Delegation / Federation** — each layer exchanges one credential for another
- **Defense in Depth** — multiple independent security layers

**RS256 vs HS256:**

| | RS256 (asymmetric) | HS256 (symmetric) |
|---|---|---|
| Signing key | Private (only issuer has it) | Shared secret (both parties) |
| Verify key | Public (anyone can verify) | Same shared secret |
| Risk if verifier compromised | Can't forge tokens | Shared secret leaks → can forge tokens |
| Your rule | Services that only verify use RS256 | Services that both issue + verify can use HS256 internally |

**Cache-Aside with Proactive Refresh** (`CIAMTokenClient`):
- Check cache first: 99.9% of calls return from memory (~0ms)
- 5-minute buffer: refresh before expiry, not after miss
- `invalidate()` method: force fresh fetch without pod restart

---

### 1.5 Scatter-Gather (Fan-Out Pattern)

**What you built:** `correlate_infra_with_services` — `ThreadPoolExecutor` hitting PG + RMQ + OpenSearch + Datadog in parallel

**CS name:** **Scatter-Gather** — scatter N requests to N backends, gather all results, return composite. Latency = `max(N)` not `sum(N)`.

**Why threads, not asyncio?** `psycopg2` and the Kubernetes client are sync libraries. You can't `await` a sync function. Threads are the correct bridge for sync I/O in an async context.

---

### 1.6 Design Patterns in Your Code

| Pattern | Where in code | Category |
|---------|--------------|----------|
| **Template Method** | `BaseAgent` skeleton loop; subclasses implement `get_system_prompt()` and `_register_tools()` | Behavioural |
| **Strategy** | `ModelSelector` — algorithm (which model) swappable at runtime | Behavioural |
| **Factory (implicit)** | `ChatService` creates the right agent based on routing decision | Creational |
| **Singleton** | `SessionManager` — one instance shared across requests | Creational |
| **Decorator** | FastAPI middleware stack (auth → rate-limit → guardrails) wraps the handler | Structural |
| **Facade** | `correlate_infra_with_services` — single interface hiding PG+RMQ+OS+DD complexity | Structural |
| **Cache-Aside** | `CIAMTokenClient` — cache check → fetch on miss → store | Architectural |

---

### 1.7 Why FastAPI, Not the Claude SDK Directly?

The Claude SDK (`anthropic` Python library) = a function call wrapper. It does NOT give you:

| What you needed | What provides it |
|----------------|-----------------|
| HTTP server for multiple simultaneous users | FastAPI |
| JWT-gated access | `AuthMiddleware` |
| Rate limiting (100 req/min/user) | `RateLimitMiddleware` |
| SSE streaming to a browser | `StreamingResponse` |
| Multi-turn session state | `SessionManager` + TTLCache |
| OTEL observability | `telemetry.py` wired into FastAPI lifespan |
| Deployed as K8s pod reachable by portal + automation | A running HTTP server |

**One-liner:** The SDK is the engine. FastAPI is the car. You needed the car.

### 1.8 Why Not LangChain / LlamaIndex?

| Concern | Why it mattered |
|---------|----------------|
| CIAM auth chain is non-standard | Framework auth hooks assume direct API keys; you'd fight the framework |
| OTEL instrumentation needs per-field control | `stop_reason`, `iteration`, per-tool `duration_ms` — standard LangChain instrumentation doesn't give these |
| Prompt caching requires exact message structure | LangChain can silently change message ordering and break Anthropic cache hits |
| Debuggability at 2am | 200 lines you fully understand beats 2000 framework lines you trace through during an incident |

When you'd reconsider: graph-based workflows (human-in-the-loop), large vector store integrations, multi-engineer team needing convention over configuration.

---

## Part 2 — HLD Concepts from Scaler Module 13 (Mapped to Your Work)

### 2.1 Caching

**Concepts:**
- **Cache-Aside (Lazy Loading)** — app checks cache, fetches on miss, stores result. Your `CIAMTokenClient` is this.
- **Write-Through** — write to cache and DB simultaneously. Not used in your system.
- **TTL (Time To Live)** — auto-expire entries. Your `SessionManager` uses 1-hour TTL.
- **Eviction policies** — LRU (least recently used), LFU (least frequently used). TTLCache uses LRU.
- **Cache invalidation** — your `CIAMTokenClient.invalidate()` is manual invalidation.

**Interview question:** "How would you cache user sessions at scale?"
> "In-memory TTLCache works fine for a single pod. At scale, move session state to Redis — it's a distributed cache with TTL support, allowing multiple pod instances to share session state without stickiness. The key is still the session_id from the JWT."

---

### 2.2 Load Balancing

**Concepts:**
- **L4 load balancing** — at TCP layer, routes by IP/port. Faster but no app-layer awareness.
- **L7 load balancing** — at HTTP layer, can route by path, headers, cookies. Your Istio VirtualService does this.
- **Consistent Hashing** — hash requests to nodes; when nodes are added/removed, only 1/N keys move. Used in distributed caches.
- **Sticky sessions** — always route same user to same backend. Needed when session state is in-memory (your current state). Solved properly by moving state to Redis.

**Your context:** Single-pod today. HPA adds pods but sessions are in-memory — if a new pod handles a returning user, their history is gone. Redis would fix this.

---

### 2.3 CAP Theorem

Three properties a distributed system can guarantee at most two of:

| Property | Meaning |
|----------|---------|
| **C — Consistency** | Every read gets the most recent write (or an error) |
| **A — Availability** | Every request gets a response (not necessarily latest data) |
| **P — Partition Tolerance** | System continues operating if network between nodes breaks |

**Network partitions always happen in real distributed systems. You must choose: CP or AP.**

| Your component | CAP choice | Reasoning |
|---------------|-----------|-----------|
| `SessionManager` (in-memory) | AP | If pod restarts, sessions are lost. Available but not consistent across pods. |
| PostgreSQL (your platform) | CP | ACID transactions. On partition, it stops accepting writes rather than risk inconsistency. |
| RabbitMQ | AP | Queues stay up even during partition; deduplication handles duplicates. |

---

### 2.4 SQL vs NoSQL

**When SQL (PostgreSQL):** Structured data, ACID transactions, complex JOINs, strong consistency. Your Orleans cluster membership, Fivetran pipeline, audit data.

**When NoSQL:**

| Type | Example | When |
|------|---------|------|
| Key-Value | Redis, DynamoDB | Sessions, caches, feature flags |
| Document | MongoDB | User profiles, flexible schema |
| Wide-column | Cassandra | Time-series, high-write throughput |
| Graph | Neo4j | Relationships (social graphs) |
| Search | OpenSearch/Elasticsearch | Full-text search, log aggregation |

**Your stack:** PostgreSQL for transactional data, DynamoDB for deployment catalog (your `audit-devops-dynamo`), OpenSearch for log search. Each chosen for the right reasons.

---

### 2.5 Database Indexing

**B-tree index** — the default. Sorted tree structure. Good for range queries, equality, ORDER BY.

**When to add an index:**
- Columns in WHERE, JOIN ON, ORDER BY that are queried frequently
- High cardinality columns (many distinct values)

**Cost:** Every index slows down INSERTs/UPDATEs (index must be maintained). Don't index everything.

**Your context:** Your `pg_tools` diagnostic queries scan `pg_stat_user_tables` for bloat, `pg_stat_activity` for connections. Knowing why slow queries exist (missing index vs. too many connections vs. lock contention) is what your assistant diagnoses.

---

### 2.6 ACID Transactions

| Property | Meaning | Example |
|----------|---------|---------|
| **Atomicity** | All operations succeed or all fail (no partial writes) | Transfer $100 — debit and credit both happen or neither |
| **Consistency** | DB stays in valid state after transaction | Foreign key constraints always hold |
| **Isolation** | Concurrent transactions don't see each other's partial work | Two users booking last seat — one wins, one gets "unavailable" |
| **Durability** | Committed data survives crashes | Written to WAL (Write-Ahead Log) before confirming |

**Isolation levels** (weakest → strongest):
1. Read Uncommitted — can read dirty data
2. Read Committed — only read committed data (PostgreSQL default)
3. Repeatable Read — same row always returns same data in a transaction
4. Serializable — transactions execute as if serial (strongest, most expensive)

---

### 2.7 Message Queues — Kafka vs RabbitMQ

| | Kafka | RabbitMQ |
|---|---|---|
| Model | Log-based (consumers read at their own offset) | Queue-based (messages deleted after ACK) |
| Replay | Yes — consumers can re-read old messages | No — consumed = gone |
| Throughput | Very high (millions/s) | High (thousands/s) |
| Ordering | Per-partition | Per-queue |
| Use case | Event streaming, audit logs, CDC | Task queues, microservice messaging |
| Your platform | Kafka equivalent for streaming | **RabbitMQ** with MassTransit for .NET service messaging |

**Backpressure:** When a consumer is slow, the queue fills. Solutions: more consumers (scale out), DLQ (dead-letter queue) to park failed messages, circuit breaker to stop sending.

---

### 2.8 Rate Limiting

**Your implementation:** `RateLimitMiddleware` — 100 requests/minute/user.

**Algorithms:**

| Algorithm | How it works | Pros / Cons |
|-----------|-------------|-------------|
| **Token Bucket** | Bucket fills at fixed rate; each request consumes one token | Allows bursts up to bucket size |
| **Leaky Bucket** | Requests drain at fixed rate; excess dropped | Smooth output, no burst |
| **Fixed Window** | Count requests in a fixed time window | Simple but has boundary spike issue |
| **Sliding Window** | Rolling count over last N seconds | More accurate, more memory |

Your `RateLimitMiddleware` is a **sliding window** counter per user — stores a deque of timestamps, counts how many are within the last 60s.

**Distributed rate limiting:** When you have multiple pods, per-pod rate limiting fails (each pod allows 100, so 3 pods allow 300). Fix: centralize counters in Redis with atomic increment + TTL.

---

### 2.9 Microservices Patterns

**Your platform:** 40+ .NET microservices — you live this.

| Pattern | What it solves | Your example |
|---------|--------------|-------------|
| **API Gateway** | Single entry point, auth, routing, rate limiting | Istio IngressGateway |
| **Service Mesh** | mTLS, observability, traffic management between services | Istio |
| **Sidecar** | Inject capabilities without app code changes | Envoy proxy as Istio sidecar |
| **Circuit Breaker** | Stop calling a failing service; retry after cooldown | Istio `DestinationRule` outlier detection |
| **Bulkhead** | Isolate failures — don't let one service take down others | K8s resource limits + HPA |
| **Saga** | Distributed transactions across services without 2PC | MassTransit sagas in your .NET services |

---

### 2.10 Classic Interview Design Problems — Quick Sketches

**"Design a rate limiter"**
> Data store: Redis. Algorithm: sliding window counter. Key: `rate_limit:{user_id}`. On each request: ZADD timestamp, ZREMRANGEBYSCORE to remove old entries, ZCARD to count. Reject if count > limit. TTL handles cleanup. Distribute across multiple nodes with Redis Cluster.

**"Design a URL shortener"**
> Generate 6-char random ID → store `{short_id: original_url}` in K-V store (Redis or DynamoDB). On redirect: look up, 301/302 redirect. Scale read-heavy traffic with CDN cache. Uniqueness: hash + collision check, or base62 encode auto-incrementing ID.

**"Design a notification system"**
> Message producer → Kafka topic per notification type → consumer per channel (email, push, SMS) → rate-limited delivery. Dead-letter queue for failed sends. User preferences stored in K-V. Idempotency key per notification to prevent duplicates.

**"How would you scale your DevOps assistant to 10,000 concurrent users?"**
> 1. Horizontally scale pods (HPA) — already set up.
> 2. Move session state from in-memory to Redis — currently the blocker for multi-pod.
> 3. Centralize rate limiting in Redis — per-pod counters don't work across replicas.
> 4. Add a queue (SQS/RabbitMQ) in front of the LLM calls — burst protection, Claude has rate limits.
> 5. Cache common responses (read-heavy, static answers) — simple K8s cluster health checks are cacheable.
> 6. Anthropic rate limits are the real ceiling — vertical limit (tokens/min) requires request queuing + retry.

---

## Part 3 — The Three-Sentence Framework for Every Design Decision

Every system design answer needs three sentences:

1. **What I chose:** "I used X."
2. **Why over the alternative:** "Because Y — the alternative Z would have required W."
3. **The tradeoff I accepted:** "The cost is Q — which I'd address in v2 by..."

**Practise these with your actual decisions:**

> **Rule-based orchestrator:** "I used keyword scoring because routing is high-frequency — every request — so adding an LLM call would burn 2s and frontier-model tokens on what is effectively a switch statement. The tradeoff is it fails on ambiguous cross-domain queries. I'd address that in v2 by adding the `handle_complex` path with a lightweight classifier."

> **3 agents not 1:** "Specialization keeps tool schemas tight — 17 tools in context instead of 38. Empirically, LLM tool-selection accuracy degrades with menu size, and each agent's system prompt stays focused. The tradeoff is cross-agent queries need a new routing layer — which isn't built yet."

> **FastAPI not LangChain:** "CIAM auth and per-tool OTEL instrumentation are non-standard — LangChain would wrap the Anthropic calls in layers I can't easily instrument at the `stop_reason` and iteration level. The BaseAgent loop is 200 lines I fully understand — debuggability at 2am matters more than saving those lines. For graph-based workflows, I'd reconsider."

---

*Created: 2026-06-11. Cross-reference: `ai-ml-prep/02-cs-vocabulary-system-design.md` (detailed version), Scaler Module 13 classes.*
