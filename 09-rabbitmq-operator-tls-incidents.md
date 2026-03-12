# Section 9: RabbitMQ — Operator, TLS & Incidents

### 9.1 RabbitMQ Fundamentals — What Interviewers Expect You to Know

RabbitMQ is an open-source message broker implementing AMQP (Advanced Message Queuing Protocol). At Confirmation, it's the async backbone — every .NET microservice publishes and consumes messages through RabbitMQ for event-driven workflows.

**Core Concepts:**

| Concept | What It Is | Real Example |
|---------|-----------|--------------|
| **Exchange** | Receives messages from producers, routes to queues | `confirmation.forms.exchange` — forms-be publishes form submission events |
| **Queue** | Stores messages until a consumer processes them | `get-form-types-by-product` — record-gql-be consumes form type lookups |
| **Binding** | Rule connecting exchange → queue | Routing key `form.submitted` binds exchange to specific queue |
| **Consumer** | Application that reads from a queue | forms-be registers a MassTransit consumer for form type requests |
| **Exchange Types** | Direct, Fanout, Topic, Headers | Direct = exact key match, Fanout = broadcast, Topic = pattern match |
| **Acknowledgment** | Consumer tells RabbitMQ "message processed" | Auto-ack (risky) vs manual-ack (safe — message requeued on failure) |
| **Dead Letter Exchange** | Where rejected/expired messages go | Failed messages → `_error` queue (7-day TTL policy) |
| **Prefetch** | How many unacked messages a consumer holds | Low prefetch = fair dispatch, high prefetch = throughput |
| **Virtual Host** | Logical namespace for isolation | We use default `/` vhost (single platform, multiple services) |
| **MassTransit** | .NET abstraction over RabbitMQ | Our services use MassTransit for publish/subscribe and request/response |

**How Our Services Use RabbitMQ:**

```
┌──────────────┐    publish     ┌────────────────┐    route      ┌──────────────────┐
│ forms-be     │───────────────▶│ Exchange        │─────────────▶│ Queue            │
│ (Producer)   │  form.submitted│ (direct/topic)  │  binding key │ get-form-types   │
└──────────────┘                └────────────────┘               └────────┬─────────┘
                                                                          │ consume
                                                                 ┌────────▼─────────┐
                                                                 │ record-gql-be    │
                                                                 │ (Consumer via    │
                                                                 │  MassTransit)    │
                                                                 └──────────────────┘
```

**Interview Answer — "Explain RabbitMQ message flow":**

> "A producer publishes a message to an exchange with a routing key. The exchange evaluates its bindings and routes the message to matching queues. Consumers subscribed to those queues receive messages. In our platform, all 40+ .NET services use MassTransit as the RabbitMQ client library — it handles exchange/queue topology, serialization, retry policies, and error handling. When a consumer fails to process a message after retries, MassTransit moves it to an `_error` queue. We have a policy that auto-expires error queue messages after 7 days to prevent unbounded growth."

---

### 9.2 RabbitMQ on Kubernetes — Operator Architecture

We run RabbitMQ using the **RabbitMQ Cluster Operator** (v4.3.27). The operator manages cluster lifecycle through a `RabbitmqCluster` CRD.

**Architecture:**

```
┌──────────────────────────────────────────────────┐
│         RabbitMQ Cluster Operator (v4.3.27)       │
│    Watches RabbitmqCluster CRDs, manages pods     │
└──────────────────┬───────────────────────────────┘
                   │ manages
     ┌─────────────┼─────────────┐
     │             │             │
┌────▼───┐   ┌────▼───┐   ┌────▼───┐
│ Node 0 │   │ Node 1 │   │ Node 2 │
│ RMQ    │◄─▶│ RMQ    │◄─▶│ RMQ    │
│ 10Gi   │   │ 10Gi   │   │ 10Gi   │
│ PVC    │   │ PVC    │   │ PVC    │
└────────┘   └────────┘   └────────┘
  Erlang clustering (peer discovery via K8s API)
```

**What the Operator Creates From One CRD:**

| Resource | Purpose |
|----------|---------|
| **StatefulSet** | 3 RabbitMQ pods with stable network identity |
| **Headless Service** | DNS-based peer discovery (erlang clustering) |
| **Client Service** | AMQP (5671/5672) + Management UI (15672) |
| **ConfigMap** | rabbitmq.conf + advanced.config |
| **Secret** | Admin credentials (from ExternalSecret) |
| **PVC** (per pod) | 10Gi persistent message storage |
| **ServiceAccount** | K8s API access for peer discovery |

**Our Real Configuration (CI):**

```yaml
# From charts/rabbitmq-cluster/templates/rabbitmq-cluster.yaml
apiVersion: rabbitmq.com/v1beta1
kind: RabbitmqCluster
metadata:
  name: confirmation-rabbitmq-ci
  namespace: 207804-confirmation-ci
  annotations:
    sidecar.istio.io/inject: "false"  # RabbitMQ bypasses Istio mesh
spec:
  replicas: 3
  image: 833618288067.dkr.ecr.us-east-1.amazonaws.com/a207804/a207804-ue1-op-rabbitmq-operator-ci:3.13.7
  persistence:
    storageClassName: plexus-gp2
    storage: 10Gi
  resources:
    limits:   { cpu: "2", memory: 4Gi }
    requests: { cpu: "1", memory: 4Gi }
  rabbitmq:
    additionalConfig: |
      total_memory_available_override_value = 2.8GB
      disk_free_limit.absolute = 2GB
      cluster_formation.peer_discovery_backend = rabbit_peer_discovery_k8s
      cluster_formation.k8s.address_type = hostname
      tcp_listen_options.keepalive = true
  tls:
    secretName: confirmation-rabbitmq-tls-cert
    disableNonTLSListeners: false   # CI allows plain AMQP for ReportPortal
```

**Non-Prod vs Production:**

| Aspect | Non-Prod (CI/Demo/QA) | Production |
|--------|----------------------|------------|
| Cluster name | `confirmation-rabbitmq-ci` | `confirmation-rabbitmq-prod` |
| Replicas | 3 | 3 (QED: 5) |
| Resources | 2 CPU / 4Gi | 4 CPU / 8Gi (Prod-DR: 8Gi requests=limits for Guaranteed QoS) |
| TLS | Dual-mode (5672 + 5671) | 5671 only (`disableNonTLSListeners: true`) |
| Policies | HA mirroring + error TTL enabled | Disabled (operator webhook issues) |
| Memory | 2.8GB | 1.8GB |
| ECR account | `833618288067` (us-east-1) | `416557019297` (us-east-1), DR: `us-west-2` |
| Istio | Bypassed | Bypassed |

**Why Istio Bypass?**

> "RabbitMQ uses AMQP, a binary protocol, not HTTP. Istio's Envoy sidecar is an L7 proxy optimized for HTTP/gRPC — it can't inspect or route AMQP traffic meaningfully. Also, RabbitMQ manages its own TLS (port 5671) and Erlang distribution protocol for clustering. Adding Istio sidecar would break peer discovery and add latency to every message. Same reason PostgreSQL bypasses Istio."

---

### 9.3 TLS Configuration — Self-Signed Certificates

RabbitMQ uses **self-signed TLS certificates** (not public CA, not Istio mTLS). I wrote the certificate generation script.

**Certificate Chain:**

```
Self-Signed CA (cacert.pem)
  └── Server Certificate (cert.pem)
        Subject Alternative Names:
          DNS.1 = confirmation-rabbitmq-ci
          DNS.2 = confirmation-rabbitmq-ci.207804-rabbitmq-ci
          DNS.3 = confirmation-rabbitmq-ci.207804-rabbitmq-ci.svc
          DNS.4 = confirmation-rabbitmq-ci.207804-rabbitmq-ci.svc.cluster.local
```

**Why 4 SANs?**

> "Kubernetes services can be reached by short name (`confirmation-rabbitmq-ci`), namespace-qualified name, or FQDN. We need all 4 variants in the certificate's Subject Alternative Names because different clients connect using different forms. If a .NET service connects using the FQDN but the cert only has the short name, TLS handshake fails. Modern TLS ignores the CN field entirely — it only checks SANs."

**Certificate Generation Script** (`scripts/certificates/ci/certs.sh`):

```bash
#!/bin/bash
CLUSTER_NAME="confirmation-rabbitmq-ci"
NAMESPACE="207804-rabbitmq-ci"

# 1. Generate CA key pair
openssl genrsa -out key.pem 2048
openssl req -x509 -new -nodes -key key.pem -sha256 -days 365 -out cacert.pem

# 2. Generate server certificate with SANs
openssl req -new -newkey rsa:2048 -nodes -keyout server-key.pem -out cert.csr
openssl x509 -req -in cert.csr -CA cacert.pem -CAkey key.pem -CAcreateserial \
    -out cert.pem -days 365 -sha256

# 3. Create K8s TLS Secret
kubectl create secret generic confirmation-rabbitmq-tls-cert \
  --from-file=tls.crt=cert.pem \
  --from-file=tls.key=server-key.pem \
  --from-file=ca.crt=cacert.pem \
  -n 207804-confirmation-ci
```

**How .NET Services Trust the Self-Signed CA:**

> "Since our CA is self-signed, .NET services don't trust it by default (it's not in the OS trust store). We mount the `ca.crt` (the CA certificate — public, not secret) into each service pod via an ExternalSecret. The .NET RabbitMQ client is configured with `SslOption.CertPath` pointing to the mounted CA certificate, or the Helm chart injects it into the container's trust store at startup. This way, when the service connects to RabbitMQ on port 5671, it validates the server's certificate against our CA."

**File Roles:**

| File | Secret? | Purpose |
|------|---------|---------|
| `cacert.pem` | No (public) | CA certificate — distributed to all services for trust |
| `key.pem` | **YES** | CA private key — NEVER leaves the cert generation machine |
| `cert.pem` | No (public) | Server certificate — presented by RabbitMQ during TLS handshake |
| `server-key.pem` | **YES** | Server private key — stored in K8s Secret, mounted by RabbitMQ only |

---

### 9.4 Secrets Management — ExternalSecret with ArgoCD PreSync

RabbitMQ admin credentials flow through the same AWS Secrets Manager → ExternalSecret → K8s Secret chain, but with a critical ArgoCD sync wave ordering.

```yaml
# From templates/rabbitmq-admin-externalsecret.yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: confirmation-rabbitmq-admin-secret-ci
  annotations:
    argocd.argoproj.io/sync-wave: "-1"  # MUST exist before RabbitmqCluster CR
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: a207804-cn-aws
    kind: SecretStore
  target:
    name: confirmation-rabbitmq-admin-secret-ci
    template:
      data:
        username: "{{ .username }}"
        password: "{{ .password }}"
        host: "{{ .host }}"
        port: "5671"
        connection_string: "{{ .connection_string }}"
        default_user.conf: |
          default_user = {{ .username }}
          default_pass = {{ .password }}
  data:
    - secretKey: username
      remoteRef:
        key: a207804-ue1-op-rabbitmq-admin-ci-sm
        property: username
    - secretKey: password
      remoteRef:
        key: a207804-ue1-op-rabbitmq-admin-ci-sm
        property: rabbitmq-password
```

**Why Sync Wave -1?**

> "The RabbitmqCluster CR references the admin secret via `spec.secretBackend.externalSecret.name`. If the secret doesn't exist when the operator tries to create the cluster, it fails. By setting `sync-wave: -1`, ArgoCD creates the ExternalSecret (which syncs from AWS Secrets Manager and creates the K8s Secret) before applying the RabbitmqCluster CR at wave 0. This is the same pattern we use for all K8s resources — secrets first, consumers second."

---

### 9.5 Queue Policies — HA Mirroring & Error Queue TTL

We manage RabbitMQ policies as Kubernetes CRDs through the **Messaging Topology Operator**.

**Policy 1: Classic Queue HA Mirroring**

```yaml
apiVersion: rabbitmq.com/v1beta1
kind: Policy
metadata:
  name: classic-queue-mirroring
spec:
  name: "DEFAULT-CLASSIC-QUEUES-POLICY-CLUSTER"
  pattern: ".*"          # Matches ALL queues
  applyTo: "classic_queues"
  definition:
    ha-mode: "all"       # Mirror to ALL nodes (3 copies)
    ha-sync-mode: "automatic"  # Auto-sync new mirrors
    max-length: 9000000  # 9 million messages max
    overflow: "reject-publish"  # Back-pressure: reject new messages at limit
    queue-mode: "lazy"   # Write to disk first, not memory
  priority: 1
```

**Interview Answer — "Explain ha-mode: all vs exactly":**

> "With `ha-mode: all`, every queue is mirrored to all 3 nodes. If any node goes down, the queue is still available on the other 2. With `ha-mode: exactly` and `ha-params: 2`, you get one primary + one mirror — uses less memory but tolerates only 1 node failure. We chose `all` because we have only 3 nodes and need maximum HA. The trade-off is 3x the memory/disk for every message, but with lazy mode (`queue-mode: lazy`), messages go to disk first, so memory pressure is manageable."

**Why `overflow: reject-publish`?**

> "When a queue hits 9 million messages (our max-length), RabbitMQ has two choices: drop the oldest message (`drop-head`) or reject the publisher (`reject-publish`). We chose reject-publish because it applies back-pressure — the producer gets a nack and can retry later. With drop-head, you silently lose messages. For audit confirmations, losing messages is unacceptable."

**Policy 2: Error Queue TTL**

```yaml
apiVersion: rabbitmq.com/v1beta1
kind: Policy
metadata:
  name: error-queue-ttl
spec:
  name: "ERROR-QUEUE-TTL-POLICY"
  pattern: ".*_error$"   # Matches queues ending with _error
  applyTo: "queues"
  definition:
    message-ttl: 604800000  # 7 days in milliseconds
    max-length: 10000       # Keep last 10,000 error messages
    overflow: "drop-head"   # Drop oldest errors when full
  priority: 2              # Higher priority than default policy
```

**Why 7-Day TTL on Error Queues?**

> "MassTransit moves failed messages to `{queue}_error` queues after exhausting retries. Without a TTL, these queues grow forever and consume disk. 7 days gives the team enough time to investigate failures, but we don't keep them indefinitely. If a bug causes thousands of failures, the 10,000 max-length prevents disk exhaustion, and drop-head keeps the most recent errors (which are more useful for debugging than the oldest ones)."

**Why Policies Disabled in Production?**

> "We hit an issue with the RabbitMQ operator's webhook validation in production — the topology operator's admission webhook was rejecting Policy CRDs due to a version compatibility issue with the r6 operator release. Rather than risk a production incident debugging operator webhooks, we applied equivalent policies directly via `rabbitmqctl` as a temporary fix and disabled the CRD-based policies in the Helm values."

---

### 9.6 ArgoCD Integration — Avoiding Sync Loops

RabbitMQ has a unique ArgoCD challenge: the operator injects fields into the `RabbitmqCluster` spec that don't exist in our Helm template. Without handling this, ArgoCD sees a constant "drift" and re-syncs endlessly.

```yaml
# From argocd/applications/non-prod/templates/rabbitmq-cluster-applicationset.yaml
spec:
  ignoreDifferences:
    - group: rabbitmq.com
      kind: RabbitmqCluster
      jqPathExpressions:
        - .spec.delayStartSeconds
        - .spec.terminationGracePeriodSeconds
        - .spec.service
        - .spec.secretBackend
```

**Interview Answer — "How do you handle operator-injected fields with ArgoCD?":**

> "This is a common GitOps challenge with operators. The RabbitMQ operator adds fields like `delayStartSeconds` and `terminationGracePeriodSeconds` to the live spec that don't exist in our Helm template. ArgoCD compares desired state (from git) vs live state (from cluster) and sees these extra fields as drift — triggering an infinite sync loop.
>
> The fix is `ignoreDifferences` with jqPathExpressions. We tell ArgoCD to ignore specific operator-injected paths during comparison. This preserves the GitOps principle (git is source of truth for OUR config) while acknowledging that the operator legitimately manages some fields at runtime."

---

### 9.7 Datadog Monitoring for RabbitMQ

Every RabbitMQ pod is auto-instrumented with Datadog OpenMetrics:

```yaml
# Injected via statefulSet override in the RabbitmqCluster CRD
annotations:
  ad.datadoghq.com/rabbitmq.check_names: '["openmetrics"]'
  ad.datadoghq.com/rabbitmq.instances: |
    [{
      "openmetrics_endpoint": "http://%%host%%:15692/metrics",
      "namespace": "rabbitmq",
      "metrics": [".*"],
      "tags": ["cluster:confirmation-rabbitmq-ci", "env:ci"]
    }]
```

**Key Metrics We Monitor:**

| Metric | What It Tells Us | Alert Threshold |
|--------|-----------------|-----------------|
| `rabbitmq_queue_messages_ready` | Messages waiting for consumers | > 10,000 sustained |
| `rabbitmq_queue_consumers` | Active consumers per queue | = 0 (critical — no one processing) |
| `rabbitmq_connections` | Total client connections | > 500 (connection leak) |
| `rabbitmq_channel_messages_unacked` | Messages delivered but not acked | > 1,000 (consumer stuck) |
| `rabbitmq_node_disk_free` | Available disk | < 2GB (broker blocks publishers) |
| `rabbitmq_node_mem_used` | Memory consumption | > 80% of 2.8GB limit |

---

### 9.8 Real Incidents — This Is What Interviewers Want

#### INC-001: record-gql-be CrashLoopBackOff — MassTransit Consumer Missing

**Date**: Feb 12, 2026 | **Env**: QA | **Duration**: ~24 hours

**The Story (STAR Format):**

> **Situation**: "We got an alert that `record-gql-be` was in CrashLoopBackOff in QA. The pod kept restarting with exit code 139 — which normally means segmentation fault."
>
> **Task**: "I needed to find the root cause and restore the service."
>
> **Action**: "First, I checked `kubectl logs --previous` to see the crash reason. The logs showed `MassTransit.RequestTimeoutException` at `FormService.cs:40`. The service was calling `FormService.InitializeFormNames()` synchronously in its DI constructor using `Task.Wait()`, expecting a 30-second response from the `get-form-types-by-product` RabbitMQ queue.
>
> So I checked the queue consumers: `rabbitmqctl list_queues name consumers | grep get-form-types`. The result was `get-form-types-by-product 0` — **zero consumers**. That queue is supposed to be served by `forms-be`, which was running fine (pods healthy, no restarts). But `forms-be` had silently stopped registering its MassTransit consumer after a recent deployment.
>
> The exit code 139 was misleading — it's actually the Datadog CLR profiler catching an unhandled .NET exception and terminating the process with SIGSEGV. The real exception was a `RequestTimeoutException` because no consumer existed for the queue."
>
> **Result**: "I restarted `forms-be` pods, which re-registered the MassTransit consumer. `record-gql-be` immediately started successfully. Total impact: ~24 hours of degraded record service in QA.
>
> Key takeaway: **always check consumer counts first** for MassTransit timeout errors. Exit code 139 in .NET with Datadog profiler is misleading — read the actual exception. And blocking async calls (`Task.Wait()`) in DI constructors is fragile — if the dependency is down, the entire service crashes on startup."

---

#### Incident Pattern: CHG0130049 — Proxy Change Cascade (5 Incidents)

**Date**: Feb 27–Mar 2, 2026 | **Env**: CI, Demo, QA | **5 separate incidents**

**The Background:**

> "Our network team pushed CHG0130049 — a change that routed all outbound traffic through a Local Gateway (LGW) instead of direct NAT. This required every service to use a corporate proxy (`webproxy.df1.corp.services:80`) and set `NO_PROXY` for internal traffic. The Helm-managed services were updated, but several edge cases broke."

**INC-004: reports-dwh-be — Missing NO_PROXY hostname**

> "Report generation was timing out (53-57 seconds → 499 client disconnect). The root cause: `reports-dwh-be` needed to call CG report service hostnames (`iqa5reportservice.confirmation.com` for CI, `iqa2reportservice.confirmation.com` for Demo). These were private/internal services but their hostnames weren't in NO_PROXY, so .NET HttpClient routed them through the corporate proxy, which couldn't reach them. Fix: add the hostnames to NO_PROXY in the Helm values."

**INC-005 + INC-008: Selenium Grid — Proxy missing on manually-managed pods**

> "The Selenium Grid is manually deployed (not via Helm/ArgoCD). When the proxy rollout happened, only Helm-managed services got the new env vars. Selenium hub, chrome, firefox, and edge node deployments had no HTTPS_PROXY/NO_PROXY. Grid showed 18/18 nodes UP, but browser sessions couldn't load any URLs — `ERR_CONNECTION_RESET` because Chrome inherits proxy settings from container env vars.
>
> Fix: `kubectl set env deployment/selenium-chrome-node HTTPS_PROXY=http://webproxy.df1.corp.services:80 NO_PROXY=169.254.169.254,localhost,.cluster.local,.svc.cluster.local`. Had to apply to all 4 deployments. Then in INC-008, a week later, the same thing happened because a deployment rollout reset the env vars — `kubectl set env` patches the deployment spec but if someone recreates the deployment, the patch is lost."

**INC-007: file-service-be — FTPS connection refused**

> "FTPS connection to `10.131.38.172:21` broke. Two-layer problem: (1) the egress IP changed, so the FTPS server's firewall rejected the new source. (2) With HTTPS_PROXY set, .NET routes via corporate proxy, but `webproxy.df1.corp.services` blocks CONNECT tunnels to private IP ranges (10.x.x.x) — returns 503. This is still OPEN pending a network ticket."

**Key Lesson for Interviews:**

> "CHG0130049 taught me that infrastructure changes cascade unpredictably. Five separate services broke for five different reasons — missing NO_PROXY entries, manually-managed pods, proxy blocking private IPs, transient job failures. My approach now: when a network change rolls out, I proactively check every service category — Helm-managed, operator-managed, manually-managed, CronJobs — not just the happy path."

---

#### INC-002: responder-queue-fe — Blank Page (CloudFront + WAF)

**Date**: Feb 20, 2026 | **Env**: QED (Production-like)

**The Story:**

> "The responder-queue frontend (CloudFront → S3 static site) was showing a blank page. Two stacked issues:
>
> 1. **Deleted OAI**: CloudFront was referencing a deleted Origin Access Identity (`E2M4C1ROW3XEWL`). All S3 requests returned 403. CloudFront's custom error response (403 → serve `index.html` with 200 status) masked the real error — it looked like the app loaded but had no content.
>
> 2. **Stale WAF IP set**: The nested CloudFront had a WAF with `DefaultAction: Block` and an IP allowlist of 125 CIDRs. AWS had published 199 CIDRs. CloudFront edge IPs not in the allowlist were silently blocked.
>
> Fix: switched to a valid OAI, updated S3 bucket policy, and ITOPS disabled WAF on the nested CloudFront (the umbrella already protects).
>
> Key lesson: **CHECK WAF EARLY** when `x-cache: Error from cloudfront` appears. Custom error responses (403 → 200) make debugging nearly impossible because the HTTP status looks fine."

---

#### INC-003: Webcomp FE — Angular outputPath Mismatch

**Date**: Feb 22-24, 2026 | **Env**: CI, Demo | **4 services affected**

**The Story:**

> "Four web component frontends (`webcomp-av-stats-fe`, `responder-queue-fe`, `responder-view-fe`) showed blank pages after migrating from CodePipeline to ArgoCD. The CI pipeline was producing 495-byte zip artifacts instead of full builds.
>
> Root cause: Angular's `angular.json` had `outputPath: dist/aafm-confirmation-webcomp-av-confirmation-stats` but the CI workflow used `ServiceName: aafm-confirmation-webcomp-av-stats-fe`. The workflow zips `dist/{ServiceName}/` — which doesn't exist because Angular built to a differently-named directory. Result: zip contains only `version.txt`, no app files.
>
> The sneaky part: QA still worked because it had old CodePipeline-deployed content in S3. Only CI and Demo (freshly deployed via ArgoCD) were affected.
>
> Fix: aligned Angular `outputPath` in 3 repos, fixed `package.json` and Dockerfile COPY paths. Key diagnostic: **always check zip artifact size** — 495 bytes signals missing build output."

---

#### INC-009: CSTools FE — WAF Blocking Proxy IP

**Date**: Mar 2, 2026 | **Env**: CI, Demo

**The Story:**

> "CSTools frontend loaded fine from developer laptops but showed MIME type errors in Selenium sessions. JS files returned `content-type: text/html` instead of `text/javascript`. QA worked perfectly.
>
> The difference: Selenium browsers go through corporate proxy (`155.46.138.248`). CI/Demo WAF only allowlisted Zscaler IPs, not corporate proxy IPs. QA's WAF had the `tr-webcorp` IP set which included `155.46.128.0/17`.
>
> When WAF blocked the request, CloudFront returned 403 → custom error response served `index.html` → browser received HTML where it expected JavaScript → MIME type error.
>
> Fix: Added `155.46.128.0/17` to the CI/Demo WAF IP set. Took effect in 30 seconds.
>
> Diagnostic command: `curl -sI --proxy http://webproxy.df1.corp.services:80 'https://ci.cstools.confirmation.com/main.js' | grep content-type`"

---

### 9.9 RabbitMQ Certificate Trust Chain — Deep Dive (Network Concepts)

This came from a WAF onboarding meeting with the network team (Aug 2025). The full trust chain for our platform has **three certificate types**:

| Type | Who Issues It | Who Trusts It | Our Usage |
|------|--------------|---------------|-----------|
| **Public CA** (Sectigo) | Sectigo Root X1 → Intermediate → Leaf | All browsers, OS trust stores | F5 BigIP → Istio IngressGateway (HTTPS) |
| **Self-Signed** | We generate our own CA | Only pods with our `ca.crt` mounted | RabbitMQ TLS (AMQP 5671) |
| **Private CA** (Istio) | Istiod runs its own PKI | Only pods in the mesh | Pod-to-pod mTLS (SPIFFE identities) |

**Interview Answer — "Why three different certificate types?":**

> "Each serves a different trust boundary:
>
> 1. **Public CA** (Sectigo) for internet-facing traffic — browsers already trust it, no client configuration needed. F5 BigIP terminates this TLS.
>
> 2. **Self-signed** for RabbitMQ — we control both sides (RabbitMQ server and .NET clients), so we don't need public trust. Self-signed avoids certificate cost and renewal complexity from external CAs. We just need to distribute our `ca.crt` to the client pods.
>
> 3. **Istio's private CA** for pod-to-pod — Istiod auto-provisions SPIFFE certificates (`spiffe://cluster.local/ns/{namespace}/sa/{service-account}`) with 24-hour rotation. No human involvement, no certificate files to manage.
>
> The key principle: use the simplest trust model that meets the security requirement. Public CA for external, self-signed for internal infrastructure, and automated PKI for service mesh."

---

### 9.10 How .NET Services Connect to RabbitMQ

Each .NET service gets RabbitMQ connection details through an ExternalSecret:

```
AWS Secrets Manager                        ExternalSecret                    K8s Secret
(a207804-ue1-op-forms-be-ci-app-sm)  ──sync──▶  (forms-be-ci-rabbitmq-   ──creates──▶  (confirmation-forms-
  property: "rabbitmq-host"                       externalsecret)                         rabbitmq-secrets-ci)
  property: "rabbitmq-password"                                                           │
  property: "rabbitmq-username"                                                    Mounted as env vars
  property: "rabbitmq-port"                                                        in forms-be pod:
                                                                                   RABBITMQ_HOST=confirmation-rabbitmq-ci...
                                                                                   RABBITMQ_PORT=5671
                                                                                   RABBITMQ_USERNAME=...
                                                                                   RABBITMQ_PASSWORD=...
```

**Three ExternalSecrets Per Service:**

| ExternalSecret | Purpose | Mount Type |
|---------------|---------|------------|
| App config (`-rolloutexternalsecret`) | Application secrets (JSON file) | Volume at `/app/Secrets` |
| RabbitMQ (`-rabbitmq-externalsecret`) | RabbitMQ credentials (extracted) | Environment variables |
| Liquibase (`-migration-job-secrets`) | Database migration credentials | Job env vars (PreSync) |

---

### 9.11 Peer Discovery & Erlang Clustering

RabbitMQ nodes find each other using **Kubernetes-based peer discovery**:

```yaml
# From rabbitmq.conf
cluster_formation.peer_discovery_backend = rabbit_peer_discovery_k8s
cluster_formation.k8s.host = kubernetes.default
cluster_formation.k8s.address_type = hostname
```

**How It Works:**

1. Node 0 starts, queries K8s API for pods matching the StatefulSet label
2. Node 0 finds only itself — becomes the cluster seed
3. Node 1 starts, queries K8s API, discovers Node 0
4. Node 1 joins Node 0's cluster via Erlang distribution protocol (port 25672)
5. Node 2 repeats — joins the existing 2-node cluster
6. Erlang cookie (shared secret) authenticates inter-node communication

**Why `address_type: hostname`?**

> "StatefulSet pods have stable hostnames (`confirmation-rabbitmq-ci-server-0`). Using hostname instead of IP means the Erlang cookie and cluster membership survives pod restarts — the new pod gets the same hostname and rejoins seamlessly. With IP-based discovery, a restarted pod gets a new IP and RabbitMQ treats it as a different node."

---

### 9.12 Interview Scenario Questions

**Q: "A queue has 500,000 messages backed up. What do you do?"**

> "First, I check WHY messages are accumulating:
>
> 1. **Check consumer count**: `rabbitmqctl list_queues name consumers messages | grep {queue}` — if consumers = 0, the consuming service is down or not registered
> 2. **Check consumer acknowledgment**: If consumers > 0 but messages growing, consumers are too slow or stuck. Check `messages_unacked` — high means consumers received but haven't acked
> 3. **Check if it's an error queue**: `_error` queues accumulate by design — MassTransit puts failed messages there
>
> Immediate fixes depending on root cause:
> - Consumers = 0: restart the consuming service, verify MassTransit registration
> - Consumers slow: scale up the consuming service (increase HPA replicas), check for downstream bottlenecks (database locks, external API timeouts)
> - Burst: if it's a temporary import batch, wait — lazy mode means messages are on disk, not consuming memory
>
> Our `overflow: reject-publish` policy kicks in at 9 million messages — publishers get back-pressure. Below that, RabbitMQ handles the queue fine with lazy mode."

**Q: "How would you handle a RabbitMQ node failure in production?"**

> "With 3-node cluster and `ha-mode: all`:
>
> 1. **Detection**: Datadog alerts on `rabbitmq_node_disk_free < 2GB` or pod not ready
> 2. **Immediate impact**: Queues mirrored to all 3 nodes — losing 1 node means queues are still available on the other 2. No message loss.
> 3. **Recovery**: The operator detects the failed pod, StatefulSet controller creates a new one with the same hostname. The new node auto-joins the cluster via K8s peer discovery.
> 4. **Mirror sync**: `ha-sync-mode: automatic` means the new node automatically syncs all queue data from existing mirrors
> 5. **Verify**: `rabbitmqctl cluster_status` shows 3 nodes, `rabbitmqctl list_queues name mirror_pids` shows mirrors on all nodes
>
> The only downtime scenario is if 2 out of 3 nodes fail simultaneously — which is why we use `podAntiAffinity` to spread nodes across different Kubernetes worker nodes."

**Q: "How do you rotate RabbitMQ credentials without downtime?"**

> "Step by step:
> 1. Update the password in AWS Secrets Manager (`a207804-ue1-op-rabbitmq-admin-ci-sm`)
> 2. ExternalSecret refreshes every 1 hour — or trigger manual refresh: `kubectl annotate externalsecret confirmation-rabbitmq-admin-secret-ci force-sync=$(date +%s) --overwrite`
> 3. The K8s Secret updates, but running pods still have the OLD credentials in memory
> 4. Restart RabbitMQ pods with a rolling restart — operator handles this gracefully one node at a time
> 5. Restart consuming services — they'll pick up new credentials on startup
>
> The key is ordering: update the secret source first, then restart the broker, then restart consumers. If you restart consumers before the broker has the new credentials, they'll get connection refused."

**Q: "Explain the difference between classic queues, quorum queues, and streams"**

> "Classic queues are the original RabbitMQ queue type — simple, fast, support all features (priorities, TTL, dead-lettering). We use them with `ha-mode: all` for mirroring. The downside: mirroring is eventually consistent — during network partitions, you can get split-brain.
>
> Quorum queues (introduced in 3.8) use Raft consensus — every message requires majority acknowledgment before it's considered committed. This means no split-brain, no message loss, but higher latency per message. They don't support all classic queue features (no priorities, no global QoS).
>
> Streams (introduced in 3.9) are an append-only log — like Kafka's topics. Consumers can read from any offset, replay messages, and multiple consumers read independently. Great for event sourcing and replay scenarios.
>
> We use classic queues because our .NET services with MassTransit are built around the classic queue model, and the HA mirroring is sufficient for our availability needs. If we were starting fresh, quorum queues would be the default choice for better consistency guarantees."

**Q: "A developer says 'messages are being lost'. How do you investigate?"**

> "Message loss in RabbitMQ is almost always a configuration issue, not a broker bug. My investigation:
>
> 1. **Publisher confirms**: Is the publisher using publisher confirms? Without them, the producer fires-and-forgets — if RabbitMQ doesn't accept the message (full queue, unroutable), the producer never knows
> 2. **Mandatory flag**: Without mandatory=true, messages sent to an exchange with no matching binding are silently dropped
> 3. **Consumer ack mode**: If using auto-ack, RabbitMQ removes the message the instant it's delivered — if the consumer crashes mid-processing, the message is gone
> 4. **TTL policy**: Check if a message-ttl policy is expiring messages before consumers can process them
> 5. **Max-length**: Our policy has max-length 9M with `overflow: reject-publish` — but if someone changed it to `drop-head`, older messages are silently dropped
> 6. **Error queues**: Check `_error` queues — MassTransit might be moving 'lost' messages there after retry failures
>
> In 90% of cases, 'lost messages' turn out to be messages sitting in an error queue, or consumer auto-ack dropping them on crash."

---
