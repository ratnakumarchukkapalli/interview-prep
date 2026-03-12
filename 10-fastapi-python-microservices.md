# Section 10: FastAPI & Python Microservices

### 10.1 Why FastAPI — And Why I Chose It

FastAPI is a modern Python web framework built on Starlette (ASGI) and Pydantic (validation). I chose it for our DevOps portal backend services because:

| Reason | What It Means |
|--------|---------------|
| **Async-first** | Non-blocking I/O — perfect for services that call K8s API, AWS API, Datadog API without blocking |
| **Pydantic models** | Request/response validation happens automatically — invalid input returns 422 with clear error |
| **Auto-generated docs** | `/docs` (Swagger UI) and `/openapi.json` generated from type hints — zero manual spec writing |
| **Dependency injection** | Clean separation of auth, config, and business logic via `Depends()` |
| **Performance** | Starlette + uvicorn is one of the fastest Python frameworks (async event loop) |

**Interview Answer — "Why FastAPI over Flask or Django?":**

> "For our DevOps portal services, I needed: (1) async support for calling multiple external APIs concurrently (K8s, AWS, Datadog), (2) strong input validation for security (these services handle secrets and cluster operations), and (3) auto-generated OpenAPI specs for the React frontend team. Flask is synchronous by default and doesn't have built-in validation. Django is great for full-stack apps but overkill for microservices. FastAPI gives us all three with minimal boilerplate — a typical endpoint is 10 lines of code including validation."

---

### 10.2 The 4 FastAPI Services I Built/Maintain

I built **service-ops** and **k8s-ops-assistant** from scratch, and I maintain **db-ops** and contribute to **dynamo** and **harness**.

```
┌─────────────────────────────────────────────────────────────────┐
│                    DevOps Portal (React 18)                      │
│                 ci-outpost.api.tr.confirmation.com               │
└────────┬──────────┬──────────┬───────────┬──────────────────────┘
         │          │          │           │
    ┌────▼────┐ ┌───▼───┐ ┌───▼───┐ ┌────▼─────┐  ┌──────────┐
    │service- │ │db-ops │ │dynamo │ │harness   │  │k8s-ops-  │
    │ops      │ │       │ │       │ │          │  │assistant │
    │         │ │       │ │       │ │          │  │          │
    │Pod      │ │Cross- │ │Deploy │ │Feature   │  │AI-powered│
    │restart, │ │NS DB  │ │catalog│ │flags via │  │K8s/DD    │
    │secrets, │ │diag-  │ │DynamoDB│ │Split.io │  │assistant │
    │status   │ │nostics│ │       │ │API       │  │          │
    └─────────┘ └───────┘ └───────┘ └──────────┘  └──────────┘
```

---

### 10.3 service-ops — Pod Restart, Secrets, K8s Status (Built From Scratch)

**The Problem It Solves:**

> "Before service-ops, restarting a service in QA meant: find someone with kubectl access, construct the correct rollout name, run `kubectl argo rollouts restart`. For secrets, you needed AWS console access to Secrets Manager, find the right secret by name convention, edit JSON, and hope you didn't break the format. This was slow, error-prone, and only a few people had access."

**Architecture:**

```
React Portal → JWT Auth (RS256) → FastAPI → K8s API / AWS Secrets Manager / DynamoDB
```

**All Endpoints:**

| Endpoint | Method | Purpose | Rate Limit |
|----------|--------|---------|-----------|
| `/portal/v1/infrastructure/services/{name}/restart` | POST | Restart via Argo Rollout annotation | 10/min |
| `/portal/v1/infrastructure/secrets/{name}` | PATCH | Deep-merge secret update + DynamoDB backup | 5/min |
| `/api/v1/services/{name}/status` | GET | Pod status (name, ready, restart count, age, node) | 30/min |
| `/api/v1/services/{name}/uptime` | GET | Pod uptime details | 30/min |
| `/api/v1/restart/environments` | GET | Available environments (ci, demo, qa) | 30/min |
| `/api/v1/aafm/restart` | POST | Legacy AAFM restart via AWS Lambda proxy | 10/min |
| `/health` | GET | Health + K8s connectivity status | — |
| `/metrics` | GET | Prometheus metrics | — |

**Key Implementation: Restart Strategy**

```python
# We DON'T delete pods. We patch the Argo Rollout with a restart annotation.
# The rollout controller does a zero-downtime rolling update.

from kubernetes import client

def restart_service(service_name: str, environment: str):
    namespace = f"207804-confirmation-{environment}"
    rollout_name = f"confirmation-{service_name}-{environment}-rollout"

    # Patch rollout with restart annotation
    patch = {
        "spec": {
            "restartAt": datetime.utcnow().isoformat() + "Z"
        }
    }
    custom_api.patch_namespaced_custom_object(
        group="argoproj.io", version="v1alpha1",
        namespace=namespace, plural="rollouts",
        name=rollout_name, body=patch
    )
```

**Why Annotation-Based Restart (Not Pod Delete)?**

> "Deleting pods causes a sudden disruption — all pods go down simultaneously and the ReplicaSet creates new ones. With the Argo Rollout restart annotation, the controller does a rolling restart: it brings up new pods, waits for readiness, then terminates old pods one at a time. Zero downtime. This is especially important for our services because .NET cold start takes 30-60 seconds (startup probes allow up to 5 minutes)."

**Key Implementation: Deep-Merge Secrets**

```python
# Secrets in AWS Secrets Manager are JSON objects with nested structure.
# PATCH means "update only the keys I send, keep everything else".
# We use recursive deep merge — not shallow dict.update().

def deep_merge(base: dict, updates: dict) -> dict:
    """Recursively merge updates into base, preserving untouched keys"""
    for key, value in updates.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base

# Every update:
# 1. Read current secret from AWS Secrets Manager
# 2. Backup to DynamoDB (full snapshot + user attribution)
# 3. Deep-merge updates into current
# 4. Write merged result back to Secrets Manager
```

**DynamoDB Audit Trail:**

| Field | Value |
|-------|-------|
| Table | `a207804-audit-devops-secret-api-history` |
| Partition Key | `secret_name` |
| Sort Key | `timestamp` (ISO-8601) |
| Attributes | `secret_value`, `aws_sm_version_id`, `user_email`, `user_employee_id`, `correlation_id` |

> "Every secret update creates a DynamoDB record with the full before-state, who changed it, and when. If someone breaks a secret, we can restore from the audit trail without contacting AWS support."

---

### 10.4 db-ops — Cross-Namespace Database Diagnostics

**The Problem It Solves:**

> "PostgreSQL runs in its own namespace (`207804-postgres-ci`), but developers work in the application namespace (`207804-confirmation-ci`). To run a diagnostic query, they'd need: (1) kubectl access to the postgres namespace, (2) find the right secret name for credentials, (3) exec into a pod, (4) install psql, (5) construct the connection string. db-ops wraps all of this into a single API call."

**How Cross-Namespace Works:**

```yaml
# ServiceAccount in application namespace has RBAC to read secrets in postgres namespace
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: db-ops-secret-reader
  namespace: 207804-postgres-ci    # Target namespace
subjects:
  - kind: ServiceAccount
    name: database-operations-sa
    namespace: 207804-confirmation-ci  # Source namespace
roleRef:
  kind: Role
  name: secret-reader
```

**Endpoints:**

| Endpoint | Purpose | Safety |
|----------|---------|--------|
| `/api/v1/database/query` | Execute SELECT queries | Read-only enforced via validator |
| `/api/v1/database/update` | Execute INSERT/UPDATE/DELETE | Write access (authorized users only) |
| `/api/v1/database/long-running-queries` | Find slow queries (> N minutes) | Read-only diagnostic |
| `/api/v1/database/locks` | Current lock analysis | Read-only diagnostic |
| `/api/v1/database/connections` | Active connections by state | Read-only diagnostic |
| `/api/v1/database/stats` | DB size, connection count, tables | Read-only diagnostic |
| `/api/v1/database/table-sizes` | Per-table sizes | Read-only diagnostic |
| `/api/v1/database/kill-query` | Kill runaway query by PID | Controlled write (PG terminate) |
| `/api/v1/s3-backup/generate-presigned-url` | Download backup via presigned URL | Read-only (5h URL expiry) |

**Dynamic Connection Pattern:**

```python
# Single deployment handles CI/Demo/QA through environment parameter
class DatabaseService:
    def __init__(self, env: str, database_name: str):
        cluster = f"confirmation-pgdatabase-{env}"
        namespace = f"207804-postgres-{env}"
        secret_name = f"{cluster}-pguser-{database_name}"

        # Read credentials from K8s secret in postgres namespace
        secret = k8s_client.read_namespaced_secret(secret_name, namespace)
        self.host = base64.b64decode(secret.data["host"]).decode()
        self.password = base64.b64decode(secret.data["password"]).decode()

        # Connect with timeouts
        self.conn = asyncpg.connect(
            host=self.host, port=5432,
            user=database_name, password=self.password,
            database=database_name,
            timeout=30, command_timeout=300
        )
```

---

### 10.5 dynamo — Deployment Catalog API

**The Problem It Solves:**

> "With 40+ services across 8 environments, the team needed a single place to see: what version is deployed where, is there drift between QA and prod, what's the deployment success rate? Dynamo is the backend for that dashboard, backed by DynamoDB."

**Key Endpoints:**

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/deployments` | List all 46+ services with their deployment metadata |
| `GET /api/v1/deployments/{service}` | Specific service versions across all environments |
| `GET /api/v1/deployments/checkdrift` | Compare versions between two environments (e.g., prod vs QA) |
| `GET /api/v1/deployments/statistics` | 139 total deployments, 95.68% success rate |
| `POST /api/v1/deployments` | CI pipeline calls this to register a new deployment |

**Dual-Table Pattern:**

```python
# Outpost services and Cloud services store in different DynamoDB tables
TABLES = {
    "outpost": "a207804-product-config-op",     # EKS Outpost services
    "cloud":   "a207804-product-config",         # Cloud-native services
}
# Source parameter switches: ?source=outpost or ?source=cloud
```

**Dual-Auth Pattern:**

```python
# Read and write operations use DIFFERENT API keys
# Read:  X-API-Key header → for GET endpoints (portal reads)
# Write: X-Update-API-Key header → for POST/PUT (CI pipelines write)
# Both cached from AWS Secrets Manager (5-min TTL)
```

**Drift Detection (Real Data):**

> "The `/checkdrift?env=prod,qa` endpoint scans all services and compares versions. In our last check, 19 out of 46 services had version drift between prod and QA — meaning QA had newer code that hadn't been promoted yet. The portal shows this as a dashboard with red/green indicators so we can prioritize promotions."

---

### 10.6 harness — Feature Flag Management

**The Problem It Solves:**

> "Our platform uses Split.io (now Harness Feature Management) for feature flags. The Split dashboard is separate from our DevOps portal, and non-technical PMs couldn't easily find which flags were active in which environment. Harness service wraps the Split Admin API and presents flag data in our portal's UI."

**Key Endpoints:**

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/harness/workspaces` | List all Split workspaces |
| `GET /api/v1/harness/workspaces/{id}/splits` | Feature flags (paginated, 50/page) |
| `GET /api/v1/harness/workspaces/{id}/splits/all` | All flags (auto-pagination) |
| `GET /api/v1/harness/workspaces/{id}/splits/{name}/environment-details` | Flag treatments per environment (lazy-loaded) |
| `POST /api/v1/harness/cache/clear` | Force cache invalidation |

**Caching Pattern:**

```python
# Split API has rate limits. We cache responses for 5 minutes.
# Explicit cache clear endpoint for when PMs make changes and need to see them immediately.
CACHE_TTL = 300  # seconds
cache = {}

async def get_splits(workspace_id: str):
    cache_key = f"splits:{workspace_id}"
    if cache_key in cache and cache[cache_key]["expires"] > time.time():
        return cache[cache_key]["data"]

    data = await split_api.get_splits(workspace_id)
    cache[cache_key] = {"data": data, "expires": time.time() + CACHE_TTL}
    return data
```

---

### 10.7 Common Patterns Across All Services

**Pattern 1: Pydantic Settings for Configuration**

```python
# Every service uses Pydantic Settings for type-safe env var loading
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Audit DevOps Service Ops"
    ENVIRONMENT: str = "development"
    AWS_REGION: str = "us-east-1"
    SSO_JWKS_URL: str = "https://sso.thomsonreuters.com/pf/JWKS"
    SSO_ISSUER: str = "https://sso.thomsonreuters.com"

    model_config = SettingsConfigDict(env_file=".env")
```

> "Pydantic Settings loads from environment variables with type coercion and validation. If `AWS_REGION` isn't set, it falls back to `us-east-1`. If you pass an invalid type (e.g., integer where string expected), it fails at startup with a clear error — not at runtime when a request hits."

**Pattern 2: Structured JSON Logging**

```python
# All services log JSON for Datadog ingestion
import json, logging

class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
            "service": "audit-devops-service-ops",
        })
```

**Pattern 3: Correlation ID Middleware**

```python
# Every request gets a unique ID for tracing across logs
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid4()))
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response
```

**Pattern 4: Health Check with Dependency Verification**

```python
@router.get("/health")
async def health():
    k8s_ok = await check_k8s_connectivity()
    return {
        "status": "healthy" if k8s_ok else "degraded",
        "version": settings.VERSION,
        "timestamp": datetime.utcnow().isoformat(),
        "kubernetes_connection": k8s_ok
    }
```

**Pattern 5: TR ECR Base Image**

```dockerfile
# ALWAYS TR ECR — Docker Hub hits 100 pull/6h rate limit in CI
ARG BASE_IMAGE=833618288067.dkr.ecr.us-east-1.amazonaws.com/a207804/a207804-ue1-op-python:3.11-slim
FROM ${BASE_IMAGE}

# Security: non-root user
USER 14000:14001

# Local dev override: docker build --build-arg BASE_IMAGE=python:3.11-slim .
```

---

### 10.8 FastAPI Core Concepts — Interview Deep Dive

**Dependency Injection (Depends):**

```python
# Auth is injected, not hardcoded. Every endpoint that needs auth just declares it.
from fastapi import Depends

async def verify_jwt(request: Request) -> dict:
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    payload = jwt.decode(token, jwks_client.get_signing_key(token).key, algorithms=["RS256"])
    return payload

@router.post("/restart")
async def restart(request: RestartRequest, user: dict = Depends(verify_jwt)):
    # user is guaranteed to be authenticated here
    log.info(f"Restart by {user['email']}")
```

> "Dependency injection is FastAPI's killer feature. Auth, database sessions, config — anything that multiple endpoints need gets defined as a `Depends()`. It's composable too — you can have `Depends(verify_jwt)` inside `Depends(verify_admin)` for nested checks."

**Async/Await — Why It Matters:**

```python
# BAD: Synchronous — blocks the event loop, can only handle 1 request at a time
@router.get("/pods")
def get_pods():
    k8s_result = k8s_client.list_pods()       # Blocks 200ms
    dd_result = datadog_client.get_metrics()   # Blocks 300ms
    return {"k8s": k8s_result, "dd": dd_result}  # Total: 500ms sequential

# GOOD: Async — both calls happen concurrently
@router.get("/pods")
async def get_pods():
    k8s_task = asyncio.create_task(k8s_client.list_pods())
    dd_task = asyncio.create_task(datadog_client.get_metrics())
    k8s_result, dd_result = await asyncio.gather(k8s_task, dd_task)
    return {"k8s": k8s_result, "dd": dd_result}  # Total: 300ms (max of both)
```

**Pydantic Request Validation:**

```python
from pydantic import BaseModel, field_validator
from enum import Enum

class Environment(str, Enum):
    ci = "ci"
    demo = "demo"
    qa = "qa"

class RestartRequest(BaseModel):
    environment: Environment          # Enum validation — only ci/demo/qa
    service_name: str

    @field_validator("service_name")
    @classmethod
    def validate_service_name(cls, v):
        if not v.startswith("confirmation-"):
            raise ValueError("Service must start with 'confirmation-'")
        return v
```

> "Pydantic catches invalid input BEFORE it reaches business logic. If someone sends `environment: production`, they get a 422 with `value is not a valid enumeration member`. No SQL injection, no command injection — the input is validated at the boundary."

**Middleware Stack:**

```python
# Order matters — outermost middleware runs first
app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*.thomsonreuters.com"])
app.add_middleware(RateLimitMiddleware)       # slowapi
app.add_middleware(CorrelationIdMiddleware)   # Request tracing
app.add_middleware(SecurityHeadersMiddleware) # HSTS, CSP, X-Frame-Options

# Request flow:
# CORS → Rate Limit → Correlation ID → Security Headers → Route Handler
```

**Lifespan Events (Startup/Shutdown):**

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize connections, verify dependencies
    await k8s_client.connect()
    await setup_telemetry()
    log.info("Service started", extra={"version": settings.VERSION})
    yield
    # Shutdown: clean up resources
    await k8s_client.close()
    log.info("Service stopped")

app = FastAPI(lifespan=lifespan)
```

---

### 10.9 Security Patterns Across All Services

| Security Layer | Implementation | Service |
|---------------|----------------|---------|
| **Authentication** | JWT RS256 via TR SSO JWKS | service-ops |
| **Authentication** | API Key (X-API-Key header) | db-ops, harness, dynamo |
| **Authorization** | AD group membership check | service-ops (`APP-ConfirmNG-207804-Audit-DevOps-Self-Service-Group-Non-Prod`) |
| **Authorization** | Dual keys (read vs write) | dynamo |
| **Input validation** | Pydantic models + field validators | All services |
| **Rate limiting** | slowapi per-endpoint limits | service-ops (5-10/min), dynamo (10/min) |
| **Security headers** | HSTS, CSP, X-Frame-Options, X-Content-Type-Options | service-ops |
| **Audit trail** | DynamoDB with user attribution | service-ops (secrets) |
| **Read-only enforcement** | Query type validator (SELECT-only) | db-ops |
| **Container security** | UID 14000:14001, readOnlyRootFilesystem, no privilege escalation | All services |
| **Secret rotation** | AWS Secrets Manager + ExternalSecrets (1h refresh) | All services |
| **CORS** | `*.thomsonreuters.com` + localhost dev | All services |

**Interview Answer — "How do you secure a FastAPI microservice?":**

> "Defense in depth — multiple layers, each catching what the previous missed:
>
> 1. **Network layer**: Istio AuthorizationPolicy restricts which namespaces can even reach the service
> 2. **Transport layer**: TLS everywhere — Istio mTLS for pod-to-pod, HTTPS for external
> 3. **Authentication**: JWT RS256 with JWKS verification for service-ops (user-facing), API keys for service-to-service
> 4. **Authorization**: AD group membership — only members of our DevOps self-service group can call restart/secrets endpoints
> 5. **Input validation**: Pydantic models reject malformed requests at the boundary — before any business logic runs
> 6. **Rate limiting**: slowapi prevents abuse — 5 secret updates per minute, 10 restarts per minute
> 7. **Audit trail**: Every secret update logged to DynamoDB with user email, employee ID, and full before-state
> 8. **Container hardening**: Non-root (UID 14000), read-only filesystem, no privilege escalation, dropped capabilities"

---

### 10.10 Testing Patterns

```bash
# All services follow the same test structure
cd audit-devops-service-ops  # or db-ops, dynamo, harness
pytest tests/ -v                    # All tests
pytest tests/unit/ -v               # Unit tests (fast, no external deps)
pytest tests/api/ -v                # API tests (FastAPI TestClient)
pytest tests/integration/ -v        # Integration (requires live K8s/AWS)
```

**k8s-ops-assistant test suite: 479 tests, 65% coverage**
**service-ops test suite: 222+ tests, 80%+ coverage**

**Testing Pattern: FastAPI TestClient**

```python
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

def test_restart_service():
    with patch("app.services.restart_service.k8s_client") as mock_k8s:
        mock_k8s.patch_namespaced_custom_object.return_value = MagicMock()

        response = client.post(
            "/portal/v1/infrastructure/services/pricing-be/restart",
            json={"environment": "ci"},
            headers={"Authorization": f"Bearer {valid_jwt}"}
        )

        assert response.status_code == 200
        assert response.json()["pods_restarted"] > 0
        mock_k8s.patch_namespaced_custom_object.assert_called_once()
```

> "We mock external dependencies (K8s API, AWS, Datadog) in unit tests but call real services in integration tests. The TestClient runs the full FastAPI app in-process — middleware, auth, validation, everything — so API tests are nearly as reliable as hitting a real deployment."

---

### 10.11 Interview Scenario Questions

**Q: "How do you handle secrets in a FastAPI application deployed on Kubernetes?"**

> "We use a three-tier approach:
>
> 1. **AWS Secrets Manager** is the source of truth — credentials are created and rotated there
> 2. **ExternalSecrets Operator** syncs them to K8s Secrets every hour
> 3. **FastAPI service** reads credentials from environment variables (mounted from K8s Secret) or from the K8s API directly (like db-ops reading postgres credentials cross-namespace)
>
> Critically, we never hardcode secrets, never commit them to git, and never pass them as command-line args. The `.env` file exists only for local development and is in `.gitignore`. In production, everything comes from K8s Secrets backed by AWS Secrets Manager."

**Q: "A FastAPI endpoint is returning 500 errors intermittently. How do you debug?"**

> "Step by step:
>
> 1. **Check structured logs** in Datadog: `env:ci service:audit-devops-service-ops status:error` — find the correlation ID from the response header
> 2. **Follow the correlation ID**: `@correlation_id:<id>` shows every log line for that request
> 3. **Check the exception**: Our error handler logs the full traceback with the correlation ID
> 4. **Common causes**:
>    - K8s API timeout (300s default) — usually means the cluster is under load
>    - AWS Secrets Manager throttling — we cache to avoid this
>    - Connection pool exhaustion (asyncpg) — too many concurrent requests
> 5. **Fix pattern**: If it's intermittent, it's usually a resource contention issue — increase timeout, add retry with backoff, or scale the service"

**Q: "How would you add a new endpoint to an existing FastAPI service?"**

> "Following our pattern:
>
> 1. **Define the Pydantic model** in `models/` — request and response
> 2. **Write the business logic** in `services/` — keep route handlers thin
> 3. **Add the route** in `api/endpoints/` with proper auth (`Depends(verify_jwt)`), rate limit, and response model
> 4. **Register the router** in the main app
> 5. **Write tests**: unit test for business logic (mock externals), API test for the endpoint (TestClient)
> 6. **Run Bandit** security scan: `bandit -r app/ -ll` — catches common vulnerabilities
> 7. **Test locally**: `docker-compose up`, hit the endpoint via Swagger UI
> 8. **Deploy**: push → CI builds → Docker image → ECR → Helm values update → ArgoCD syncs"

**Q: "How do you handle rate limiting in FastAPI?"**

> "We use `slowapi` which is built on top of the `limits` library. Each endpoint gets its own rate limit based on impact:
>
> ```python
> from slowapi import Limiter
> limiter = Limiter(key_func=get_user_from_jwt)
>
> @router.post("/restart")
> @limiter.limit("10/minute")
> async def restart(...):
> ```
>
> - Secret updates: 5/minute (most dangerous — can break services)
> - Pod restarts: 10/minute (disruptive but recoverable)
> - Status queries: 30/minute (read-only, harmless)
>
> The key function extracts the user identity from the JWT, so rate limiting is per-user, not per-IP. This prevents a single user from spamming restart while allowing legitimate concurrent usage from multiple team members."

**Q: "Explain async/await in Python and when you'd use sync vs async endpoints"**

> "Python's `async/await` is cooperative multitasking — a single thread can handle many concurrent I/O operations by yielding control during `await`. When endpoint A is waiting for a K8s API response, Python runs endpoint B's code. This is perfect for I/O-bound services (our use case — calling external APIs).
>
> I use async endpoints for anything that calls external services (K8s, AWS, Datadog). I'd use sync endpoints only for pure computation (no I/O) — but in practice, all our endpoints involve I/O.
>
> One gotcha: if you call a blocking function (like `requests.get()` instead of `httpx.AsyncClient`) inside an async endpoint, it blocks the entire event loop. FastAPI handles this by running sync endpoints in a threadpool, but async endpoints must use truly async libraries (`asyncpg`, `httpx`, `aioboto3`)."

**Q: "How do you structure a FastAPI project for 40+ services?"**

> "Each of our 4 backend services follows the same project structure:
>
> ```
> app/
> ├── api/
> │   ├── endpoints/     # Route handlers (thin — just validation + delegation)
> │   └── router.py      # Combines all routers
> ├── core/
> │   ├── config.py      # Pydantic Settings (env vars)
> │   ├── auth.py        # JWT/API key verification
> │   ├── exceptions.py  # Custom exception classes
> │   └── logging.py     # Structured JSON logging
> ├── models/            # Pydantic request/response models
> ├── services/          # Business logic (testable, no HTTP concerns)
> └── main.py            # App factory, middleware, lifespan
> tests/
> ├── unit/              # Mock externals, test logic
> ├── api/               # TestClient, test full endpoints
> └── integration/       # Real K8s/AWS (CI pipeline)
> ```
>
> The key principle: endpoints are thin. They validate input (Pydantic), call a service function, and format the response. All business logic lives in `services/` where it can be unit tested without HTTP."

---
