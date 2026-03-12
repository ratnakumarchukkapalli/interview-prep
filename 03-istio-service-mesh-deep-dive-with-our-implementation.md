# Section 3: Istio Service Mesh — Deep Dive with Our Implementation

### 3.1 What is a Service Mesh? Why Istio?

**Without a service mesh:**
```
Pod A ──direct HTTP──> Pod B
       (no encryption, no access control, no observability)
```

**With Istio service mesh:**
```
Pod A ──> Envoy Sidecar ──mTLS encrypted──> Envoy Sidecar ──> Pod B
          (proxy injected        (transparent to           (proxy injected
           automatically)         the application)          automatically)
```

**What Istio gives you (without changing application code):**

| Capability | How | Your usage |
|-----------|-----|-----------|
| **mTLS encryption** | Envoy sidecars handle TLS handshake between all pods | PeerAuthentication mode: STRICT — all traffic encrypted |
| **Access control** | AuthorizationPolicy controls who can talk to whom | Only IngressGateway can reach our services |
| **Traffic management** | VirtualService routes traffic by path, header, weight | Canary deployments — 50% → 100% traffic shift |
| **Observability** | Envoy exports metrics, traces, access logs automatically | Datadog gets request count, latency, error rate per service |
| **Retries/Timeouts** | DestinationRule configures retry policies | Connection pool settings, circuit breaking |

> **Interview answer**: "Istio is a service mesh that injects an Envoy sidecar proxy into every pod. The sidecar intercepts all inbound and outbound traffic. This gives us three things without touching application code: mutual TLS encryption between all services, fine-grained access control via AuthorizationPolicy, and traffic routing for canary deployments via VirtualService. In our platform, every one of our 40+ microservices has an Istio sidecar."

### 3.2 Istio Architecture — Data Plane vs Control Plane

```
┌─── ISTIO CONTROL PLANE (istiod) ─────────────────────────────────┐
│                                                                    │
│  Pilot ──> pushes routing config to all Envoy sidecars            │
│  Citadel ──> manages certificates for mTLS                        │
│  Galley ──> validates Istio config (VirtualService, etc.)         │
│                                                                    │
│  (In modern Istio, all merged into single "istiod" binary)        │
└────────────────────────────────────────────────────────────────────┘
                    │
         pushes config via xDS protocol
                    │
┌─── DATA PLANE (Envoy Sidecars in every pod) ─────────────────────┐
│                                                                    │
│  Pod: pricing-be          Pod: nucleus-be                         │
│  ┌──────────────────┐     ┌──────────────────┐                    │
│  │ .NET app          │     │ .NET app          │                    │
│  │ Envoy sidecar ◄──mTLS──► Envoy sidecar    │                    │
│  └──────────────────┘     └──────────────────┘                    │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

| Component | What it does |
|-----------|-------------|
| **istiod** | Single binary running Pilot + Citadel + Galley. Pushes config to all sidecars, manages certs. |
| **Envoy sidecar** | Proxy injected into every pod (via `istio-injection=enabled` namespace label). Handles mTLS, routing, retries, metrics. |
| **Istio IngressGateway** | Entry point for external traffic into the mesh. Runs as a separate pod (usually LoadBalancer Service). |

> **Interview answer**: "Istio has two planes. The control plane (istiod) manages configuration and certificate distribution. The data plane is Envoy sidecar proxies injected into every pod. When I create a VirtualService, istiod pushes that routing rule to all relevant Envoy sidecars via the xDS protocol. The sidecars enforce it at the network level."

### 3.3 How Traffic Flows in Our Platform (End-to-End)

This is the FULL flow from a user request to a pod response in our Confirmation platform:

```
User Browser
    │
    ▼
AWS NLB / Load Balancer (Layer 4)
    │
    ▼
Istio IngressGateway Pod (in private-ingressgateway namespace)
    │ ── Gateway resource defines: host, TLS cert, port 443
    │ ── VirtualService defines: which path → which service
    │
    ▼
Envoy Sidecar (in target pod)
    │ ── AuthorizationPolicy checks: is this source allowed?
    │ ── PeerAuthentication enforces: mTLS STRICT
    │ ── DestinationRule applies: subset routing (stable/canary)
    │
    ▼
Application Container (e.g., audit-devops-assistant on port 8000)
```

> **Interview answer**: "External traffic hits our AWS NLB, which forwards to the Istio IngressGateway pod. The Gateway resource configures TLS termination with our certificate. The VirtualService routes based on URL path — for example, `/v1/chat` goes to the assistant service. The request passes through the destination pod's Envoy sidecar, which enforces mTLS and AuthorizationPolicy. Only then does it reach the application container."

### 3.4 Each Istio Resource — What It Does + Our Implementation

#### 3.4.1 Gateway — The Front Door

**Concept**: Defines which hosts, ports, and TLS certificates the IngressGateway accepts.

**Our implementation** (from `kwaf-service-mesh/templates/gateway.yaml`):

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: Gateway
metadata:
  name: e2e-gui-gateway
  annotations:
    argocd.argoproj.io/sync-wave: "1"    # Created FIRST in ArgoCD sync
spec:
  selector:
    istio: ingressgateway                  # Binds to Istio IngressGateway pod
  servers:
  - hosts:
    - ci-outpost.api.tr.confirmation.com   # Our domain
    port:
      name: https-kwaf-preprod
      number: 443
      protocol: HTTPS
    tls:
      credentialName: waf-outpost-cert     # K8s Secret with TLS cert
      mode: SIMPLE                          # TLS termination at gateway
```

**Key points to explain:**
- `selector: istio: ingressgateway` — tells which IngressGateway pod this Gateway binds to
- `tls.mode: SIMPLE` — gateway terminates TLS (decrypts), then forwards plain HTTP into the mesh (where mTLS re-encrypts)
- `credentialName` — references a K8s Secret containing the TLS certificate and private key

**Scenario Q: "What TLS modes does Istio Gateway support?"**

| Mode | What happens | When to use |
|------|-------------|-------------|
| **SIMPLE** | Gateway terminates TLS | Most common — our setup. Client→Gateway is HTTPS, Gateway→Pod is mTLS |
| **PASSTHROUGH** | Gateway passes TLS through, pod terminates | When the app handles its own TLS |
| **MUTUAL** | Both client and gateway present certificates | Client certificate authentication (mTLS at edge) |
| **ISTIO_MUTUAL** | Uses Istio's internal certificates | For mesh-internal gateways |

#### 3.4.2 VirtualService — Traffic Routing

**Concept**: Routes traffic based on host, path, headers, etc. to the right service and subset.

**Our implementation** (from `audit-devops-assistant/templates/virtual-service.yaml`):

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: VirtualService
metadata:
  name: audit-devops-assistant-virtualservice
spec:
  hosts:
    - ci-outpost.api.tr.confirmation.com   # Match incoming host
  gateways:
    - ci-ingress-gateway                    # Attached to this Gateway
  http:
    - name: chat-route
      match:
        - uri:
            prefix: /v1/chat               # Match these URL paths
        - uri:
            prefix: /v1/health
      route:
        - destination:
            host: audit-devops-assistant-service.207804-confirmation-ci.svc.cluster.local
            port:
              number: 8000
            subset: stable                  # Routes to "stable" subset
          weight: 100                       # 100% traffic to stable
        - destination:
            host: audit-devops-assistant-service.207804-confirmation-ci.svc.cluster.local
            port:
              number: 8000
            subset: canary                  # Canary subset
          weight: 0                         # 0% during normal operation
```

**Key points:**
- `hosts` — which hostname this VirtualService handles
- `gateways` — attached to our Gateway (otherwise only handles mesh-internal traffic)
- `match.uri.prefix` — path-based routing
- `subset: stable` / `subset: canary` — defined in DestinationRule, used by Argo Rollouts for canary
- `weight: 100/0` — during canary deployment, Argo Rollouts changes this to 50/50 then 100/0

> **Interview answer**: "VirtualService is like an Nginx location block but at the mesh level. It matches incoming requests by host and path, then routes to a destination service + subset. The key is the weight field — during normal operation, 100% goes to stable. During a canary deployment, Argo Rollouts automatically updates the weights to shift traffic gradually."

**Scenario Q: "How is VirtualService different from Kubernetes Ingress?"**

| Aspect | K8s Ingress | Istio VirtualService |
|--------|------------|---------------------|
| Traffic splitting | Not supported | weight-based (canary) |
| Matching | Host + path only | Host, path, headers, query params, method |
| Retries/Timeouts | Not supported | Built-in |
| mTLS | Not supported | Native via Istio |
| Fault injection | Not supported | Inject delays/errors for testing |
| Subset routing | Not supported | Route to specific pod subsets |

#### 3.4.3 DestinationRule — Subsets + Traffic Policy

**Concept**: Defines subsets (stable/canary) and traffic policies (mTLS, load balancing) for a service.

**Our implementation** (from `audit-devops-assistant/templates/destination-rule.yaml`):

```yaml
apiVersion: networking.istio.io/v1alpha3
kind: DestinationRule
metadata:
  name: audit-devops-assistant-v1.0.0-destination-rule
spec:
  host: audit-devops-assistant-service     # Target K8s Service
  trafficPolicy:
    tls:
      mode: ISTIO_MUTUAL                   # mTLS between all pods
  subsets:
    - name: stable                         # Stable subset
      labels:
        app: audit-devops-assistant-rollout
    - name: canary                         # Canary subset
      labels:
        app: audit-devops-assistant-rollout
      trafficPolicy:
        loadBalancer:
          simple: RANDOM                   # Random LB for canary pods
```

**Key points:**
- `tls.mode: ISTIO_MUTUAL` — enforces mutual TLS for all traffic to this service
- `subsets` — stable and canary both select pods with same label, but Argo Rollouts manages which pods are in which subset via pod-template-hash
- `loadBalancer: RANDOM` — for canary, random distribution prevents sticky sessions masking issues

**Scenario Q: "What's the difference between ISTIO_MUTUAL and STRICT mTLS?"**

> "They work at different layers:
> - `ISTIO_MUTUAL` in DestinationRule — tells the **client** sidecar to use Istio-managed certificates when connecting to this service
> - `STRICT` in PeerAuthentication — tells the **server** sidecar to REJECT any non-mTLS traffic
> Together they ensure end-to-end mTLS. DestinationRule controls what the sender does, PeerAuthentication controls what the receiver accepts."

#### 3.4.4 PeerAuthentication — mTLS Enforcement

**Concept**: Controls whether a workload accepts mTLS, plaintext, or both.

**Our implementation** (from `kwaf-service-mesh/templates/peerauthentication.yaml`):

```yaml
apiVersion: security.istio.io/v1beta1
kind: PeerAuthentication
metadata:
  name: default
  namespace: 207804-confirmation-ci        # Applied to entire namespace
spec:
  mtls:
    mode: STRICT                           # ONLY accept mTLS traffic
```

**mTLS modes:**

| Mode | Accepts mTLS? | Accepts plaintext? | When to use |
|------|-------------|-------------------|-------------|
| **STRICT** | Yes | NO — rejects plaintext | Production — our setup. Maximum security. |
| **PERMISSIVE** | Yes | Yes | Migration phase — when some services don't have sidecars yet |
| **DISABLE** | No | Yes | Special cases (e.g., legacy services without Istio) |

> **Interview answer**: "We use PeerAuthentication with mode STRICT on every namespace. This means any traffic that isn't mutually authenticated via Istio certificates is rejected. When we first onboarded services, we used PERMISSIVE mode temporarily so non-mesh services could still communicate. Once all services had sidecars, we switched to STRICT."

**Scenario Q: "Service A (with sidecar) can't talk to Service B (without sidecar). Why?"**

> "If the namespace has PeerAuthentication STRICT, Service B must present an mTLS certificate. Without a sidecar, it sends plaintext → rejected.
> Fix options:
> 1. Inject sidecar into Service B (best)
> 2. Create a port-level PeerAuthentication exception for Service B
> 3. Temporarily set namespace to PERMISSIVE (not recommended for prod)"

#### 3.4.5 AuthorizationPolicy — Access Control

**Concept**: Fine-grained access control — which service accounts can access which paths.

**Our implementation** (from `audit-devops-assistant/templates/authorization-policy.yaml`):

```yaml
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: audit-devops-assistant-ci-authorization-policy
spec:
  action: ALLOW
  rules:
    - from:
        - source:
            principals:
              - cluster.local/ns/private-ingressgateway/sa/private-ingressgateway-service-account
      to:
        - operation:
            paths:
              - /*
  selector:
    matchLabels:
      app: audit-devops-assistant-rollout
```

**Breaking this down:**
- `action: ALLOW` — whitelist model (only listed sources are allowed, everything else denied)
- `principals` — Istio identity = `cluster.local/ns/<namespace>/sa/<service-account>`
- Only the IngressGateway's service account can reach our service — no pod-to-pod direct access
- `selector` — applies only to pods matching this label

> **Interview answer**: "AuthorizationPolicy is like a firewall rule at Layer 7. In our setup, we use an ALLOW policy that only permits traffic from the IngressGateway's service account. This means even if an attacker gets into a random pod in the cluster, they can't directly call our service — they'd need to go through the IngressGateway, which handles authentication. It's defense in depth."

**Scenario Q: "You need to allow one service to call another directly (not through IngressGateway). How?"**

> "Add another principal to the AuthorizationPolicy:
> ```yaml
> principals:
>   - cluster.local/ns/private-ingressgateway/sa/private-ingressgateway-service-account
>   - cluster.local/ns/207804-confirmation-ci/sa/pricing-be-sa   # NEW
> ```
> This allows pricing-be to call our service directly within the mesh. The identity is verified by Istio's mTLS certificate — you can't spoof it."

#### 3.4.6 ServiceEntry — External Egress

**Concept**: By default, Istio blocks outbound traffic to external services. ServiceEntry allows specific external hosts.

**Our implementation** (from `audit-devops-assistant/templates/service-entry.yaml`):

```yaml
# We need 4 external services:
apiVersion: networking.istio.io/v1beta1
kind: ServiceEntry
metadata:
  name: audit-devops-assistant-datadog-egress
spec:
  hosts:
    - api.datadoghq.com                    # Datadog API
  location: MESH_EXTERNAL                  # Outside the mesh
  ports:
    - number: 443
      name: https
      protocol: TLS
  resolution: DNS                          # Resolve hostname via DNS

# Also created for:
# - aiplatform.gcs.int.thomsonreuters.com  (TR AI Platform — token fetching)
# - api.anthropic.com                       (Claude API — LLM calls)
# - sso.thomsonreuters.com                  (JWT/JWKS validation)
```

> **Interview answer**: "In a strict Istio mesh, outbound traffic to external services is blocked by default. Our AI assistant needs to call Datadog API, Anthropic API, TR AI Platform, and TR SSO. I created ServiceEntry resources for each external host — this tells Istio 'allow outbound TLS to these specific hosts on port 443'. Without ServiceEntry, the Envoy sidecar would reject the connection."

### 3.5 How Argo Rollouts + Istio Work Together for Canary

This is the full canary deployment flow:

```
Developer pushes new image tag to Helm chart
    │
    ▼
ArgoCD detects drift → syncs
    │
    ▼
Argo Rollout creates canary pod (new image)
    │
    ▼
Step 1: setWeight: 50
    │   Argo Rollout PATCHES the VirtualService:
    │   stable weight: 50, canary weight: 50
    │
    ▼
Step 2: pause: 1m (observe in Datadog)
    │
    ▼
Step 3: setWeight: 100
    │   stable weight: 0, canary weight: 100
    │   Old pods terminated, canary becomes new stable
    │
    ▼
Deployment complete. VirtualService reset to 100/0.
```

**Our rollout config** (from `rollout.yaml`):

```yaml
spec:
  strategy:
    canary:
      trafficRouting:
        istio:
          virtualService:
            name: audit-devops-assistant-virtualservice
            routes:
              - app-route           # Must match the route name in VirtualService
          destinationRule:
            name: audit-devops-assistant-v1.0.0-destination-rule
            canarySubsetName: canary
            stableSubsetName: stable
      steps:
        - setWeight: 50             # Send 50% to canary
        - pause:
            duration: 1m            # Wait 1 minute (monitor in Datadog)
        - setWeight: 100            # Promote to 100%
```

> **Interview answer**: "We use Argo Rollouts integrated with Istio for canary deployments. When a new image tag is pushed, Argo creates canary pods and patches the VirtualService weights — first 50/50, then pauses for 1 minute so we can observe metrics in Datadog, then promotes to 100%. The Istio DestinationRule defines the stable and canary subsets. If we see errors during the pause, we can abort and it rolls back automatically."

### 3.6 Security Layers — Our Defense in Depth

```
Layer 1: AWS NLB          → Only allows port 443
Layer 2: Istio Gateway     → TLS termination, host validation
Layer 3: VirtualService    → Path-based routing (only allowed paths)
Layer 4: AuthorizationPolicy → Only IngressGateway service account allowed
Layer 5: PeerAuthentication → mTLS STRICT — no plaintext
Layer 6: Container security → readOnlyRootFilesystem, runAsUser:14000, drop ALL capabilities
Layer 7: Application JWT   → RS256 token validation at FastAPI level
```

> **Interview answer**: "We have 7 layers of security. Network level: NLB restricts to port 443. Mesh level: Istio Gateway terminates TLS, VirtualService restricts paths, AuthorizationPolicy whitelists only the IngressGateway, PeerAuthentication enforces mTLS STRICT. Container level: read-only filesystem, non-root user (14000), all capabilities dropped, Seccomp RuntimeDefault. Application level: JWT RS256 authentication. An attacker would need to bypass all 7 layers."

### 3.7 Advanced Scenario Questions — Istio

**Q: "A new service you deployed can't receive any traffic. All other services work fine. What do you check?"**

> "Istio-specific debugging:
> 1. **Does the pod have a sidecar?** `kubectl get pod <name> -o jsonpath='{.spec.containers[*].name}'` — should show `istio-proxy`
> 2. **Is the namespace labeled?** `kubectl get ns <ns> --show-labels` — needs `istio-injection=enabled`
> 3. **AuthorizationPolicy too restrictive?** If I forgot to create one, and namespace has a deny-all default, traffic is blocked
> 4. **VirtualService route missing?** The URL path might not match any route
> 5. **DestinationRule subset mismatch?** If subset labels don't match pod labels, traffic has no destination
> 6. **Check Envoy logs**: `kubectl logs <pod> -c istio-proxy` — shows connection rejections and reasons"

**Q: "How do you debug mTLS issues between services?"**

> "mTLS troubleshooting:
> 1. `istioctl proxy-config cluster <pod>` — shows TLS settings for each upstream
> 2. `istioctl authn tls-check <pod> <service>` — verifies mTLS status between specific pods
> 3. Common issue: PeerAuthentication is STRICT but DestinationRule has `tls.mode: DISABLE` → connection fails
> 4. Check certificate validity: `istioctl proxy-config secret <pod>` — shows cert expiry
> 5. In Envoy logs: `SSL handshake error` means certificate mismatch or expired"

**Q: "How would you gradually migrate from no service mesh to Istio?"**

> "Phased approach:
> 1. **Phase 1**: Enable sidecar injection on one non-prod namespace. Set PeerAuthentication to PERMISSIVE (accepts both mTLS and plaintext)
> 2. **Phase 2**: Verify all services work with sidecars. Check Kiali or Envoy metrics for traffic flows
> 3. **Phase 3**: Create VirtualServices and DestinationRules for each service. No behavior change yet — just makes routing explicit
> 4. **Phase 4**: Add AuthorizationPolicies (ALLOW mode). Start restrictive — only IngressGateway
> 5. **Phase 5**: Switch PeerAuthentication to STRICT on non-prod. Test thoroughly
> 6. **Phase 6**: Roll out to prod namespaces one at a time. PERMISSIVE first, then STRICT after validation"

**Q: "What happens if istiod (control plane) goes down?"**

> "The data plane (sidecars) continues working! Envoy sidecars cache their configuration. Existing routing rules, mTLS certificates — all still work. What breaks:
> - No new configuration pushes (new VirtualServices won't take effect)
> - Certificate rotation stops (certs expire in 24h by default)
> - New pods won't get proper config on startup
> - So it's not immediate disaster, but must be fixed within hours before certs expire"

**Q: "How does Istio sidecar injection work?"**

> "Two ways:
> 1. **Automatic** (our approach): Label the namespace `istio-injection=enabled`. A mutating admission webhook intercepts pod creation and injects the Envoy sidecar container + init container automatically
> 2. **Manual**: `istioctl kube-inject -f deployment.yaml` — modifies the YAML to add sidecar
>
> The init container (`istio-init`) sets up iptables rules to redirect all pod traffic through Envoy. That's how the sidecar intercepts traffic transparently — the app doesn't know it's there."

### 3.8 Our Complete Istio Resource Map Per Service

Every service in our platform gets this set of Istio resources:

| Resource | Purpose | Sync Wave |
|----------|---------|-----------|
| **Gateway** | TLS termination, host binding (shared across services) | 1 |
| **VirtualService** | Path routing → service, stable/canary weights | 3 |
| **DestinationRule** | mTLS policy, stable/canary subsets | 2 |
| **AuthorizationPolicy** | Whitelist IngressGateway only | 2 |
| **PeerAuthentication** | mTLS STRICT (namespace-wide, shared) | 1 |
| **ServiceEntry** | External egress whitelist (only services that need it) | 1 |

> **Interview answer**: "Every one of our 40+ services has a VirtualService for routing, DestinationRule for mTLS and subset definitions, and AuthorizationPolicy for access control. These are all templated in Helm — I maintain the templates. Gateway and PeerAuthentication are namespace-wide (shared). ServiceEntry is only for services that call external APIs. ArgoCD sync waves ensure they deploy in the right order — Gateway and PeerAuth first, then DestinationRule and AuthPolicy, then VirtualService, then the Rollout itself."

---

### 3.9 Real Traffic Flow — selfreg-be (Self-Registration Backend) in Demo

**This is your go-to interview story.** When the interviewer asks "walk me through traffic flow in your platform," use this exact example with real names, real IPs, real ports.

#### The Request

An auditor opens their browser and navigates to the Confirmation self-registration page. The frontend sends an API call:

```
GET https://demo-outpost.api.tr.confirmation.com/api/confirmation/selfregistration/health
```

#### Step-by-Step Flow (with real resource names)

```
 BROWSER
   │
   │ https://demo-outpost.api.tr.confirmation.com/api/confirmation/selfregistration/health
   │
   ▼
 DNS RESOLUTION
   │  demo-outpost.api.tr.confirmation.com → 10.230.34.4 (Rackspace F5 LB)
   ▼
 F5 LOAD BALANCER (10.230.34.4:443)
   │  - Receives HTTPS traffic
   │  - Forwards to EKS cluster NodePort 32390
   │  - Does NOT terminate TLS here (TLS passthrough)
   ▼
 ISTIO INGRESS GATEWAY (private-ingressgateway namespace)
   │  - 3 Envoy proxy pods (HA)
   │  - Listens on port 8443
   │  - Reads TLS SNI header from ClientHello
   │  - SNI = "demo-outpost.api.tr.confirmation.com"
   │  - Looks up matching Gateway across all namespaces
   │  - Finds: demo-ingress-gateway in 207804-confirmation-demo
   │  - Loads cert: demo-outpost-cert (from private-ingressgateway namespace)
   │  - TERMINATES TLS (mode: SIMPLE)
   │  - Decrypts HTTPS → plaintext HTTP
   ▼
 GATEWAY (demo-ingress-gateway)
   │  Namespace: 207804-confirmation-demo
   │  - Matches host: demo-outpost.api.tr.confirmation.com
   │  - Passes decrypted request to VirtualServices in same namespace
   ▼
 VIRTUALSERVICE (confirmation-selfreg-be-demo-virtualservice)
   │  - Matches gateway: demo-ingress-gateway
   │  - Matches host: demo-outpost.api.tr.confirmation.com
   │  - Matches path: prefix /api/confirmation/selfregistration
   │  - Routes to: confirmation-selfreg-be-demo-service:8080
   │  - Subset: stable (weight: 100), canary (weight: 0)
   ▼
 DESTINATIONRULE (confirmation-selfreg-be-demo-v*-destination-rule)
   │  - Host: confirmation-selfreg-be-demo-service
   │  - Selects subset: stable
   │  - Applies trafficPolicy: tls.mode = ISTIO_MUTUAL
   │  - Envoy sidecar establishes mTLS to target pod's sidecar
   ▼
 SERVICE (confirmation-selfreg-be-demo-service)
   │  - Type: ClusterIP
   │  - Selector: app=confirmation-selfreg-be-demo-rollout
   │  - Port: 8080 → targetPort: 8080
   │  - K8s resolves to pod endpoint IPs
   ▼
 AUTHORIZATION POLICY (confirmation-selfreg-be-demo-authorization-policy)
   │  - Checks source principal (SPIFFE identity)
   │  - Allows: cluster.local/ns/private-ingressgateway/sa/private-ingressgateway-service-account
   │  - Denies everything else (zero-trust)
   ▼
 POD (confirmation-selfreg-be-demo-rollout-*)
   │  Container: .NET app on port 8080
   │  Sidecar: istio-proxy (Envoy — handles mTLS, telemetry)
   │  UID: 14000, read-only FS, non-root
   │
   ▼
 RESPONSE flows back the same path (encrypted at each layer)
```

**Simplified one-liner** (for quick reference):
```
Browser → F5 (10.230.34.4) → IngressGateway [TLS termination] → Gateway → VirtualService → DestinationRule → Service → AuthorizationPolicy → Pod [mTLS]
```

#### The Two Layers of TLS Encryption

This is critical to explain clearly in interviews:

```
LAYER 1: External TLS (Browser ←→ IngressGateway)
══════════════════════════════════════════════════

  IngressName CRD                    Plexus Platform
  (plexus.tr.com/v1alpha1)           (TR cert automation)
         │                                  │
         │  Lists domain names              │  Provisions TLS certificate
         │  e.g., demo-outpost.api...       │  for listed domains
         ▼                                  ▼
   K8s Secret: demo-outpost-cert
   Namespace: private-ingressgateway
   Type: kubernetes.io/tls
         │
         │  Referenced by Gateway
         │  credentialName: demo-outpost-cert
         ▼
   Istio IngressGateway Pod
   - TLS mode: SIMPLE (server-side only)
   - Terminates HTTPS from browser
   - Decrypts to plaintext HTTP


LAYER 2: Internal mTLS (Pod ←→ Pod within mesh)
══════════════════════════════════════════════════

   DestinationRule
   trafficPolicy.tls.mode: ISTIO_MUTUAL
         │
         │  Istio control plane (istiod)
         │  auto-issues short-lived certs
         │  to each pod's Envoy sidecar
         ▼
   Pod A (Envoy sidecar) ←—mTLS—→ Pod B (Envoy sidecar)
   - Mutual authentication (both sides present certs)
   - Encrypted in transit
   - Auto-rotated certificates (istiod manages lifecycle)
```

| Layer | What | Where | TLS Mode | Who Manages Cert |
|-------|------|-------|----------|-----------------|
| **External** | Browser → IngressGateway | F5 → IngressGateway | `SIMPLE` | IngressName CRD (Plexus auto-provisions) |
| **Internal** | Pod → Pod | Within service mesh | `ISTIO_MUTUAL` | Istio (automatic, short-lived, auto-rotated) |

#### Three Gateway Patterns Per Environment

Each environment has **3 domain patterns** for different access types:

| Pattern | Gateway Name | Host (Demo) | Use Case |
|---------|-------------|-------------|----------|
| **Outpost** | `demo-ingress-gateway` | `demo-outpost.api.tr.confirmation.com` | Primary external traffic via F5 |
| **External** | `demo-external-ingress-gateway` | `demo-external.api.tr.confirmation.com` | External API consumers (banks, auditors) |
| **Internal/OP** | `demo-gateway` | `demo.api.tr.confirmation.com` + `demo.sso.confirmation.com` | Internal operations, SSO, VPN access |

All 3 domains resolve to **the same F5 IP** (10.230.34.4). The IngressGateway uses **TLS SNI** (Server Name Indication) to match the correct Gateway — the client sends the hostname in the TLS ClientHello before encryption, and Istio uses that to pick which Gateway config to apply.

Each service gets **2 VirtualServices** — one for the outpost gateway, one for the internal/OP gateway. Same routing logic, different entry points.

#### ArgoCD Sync Wave Order (Why Order Matters)

When ArgoCD deploys selfreg-be, resources must be created in a specific order. If a VirtualService references a Service that doesn't exist yet, Istio can't route traffic.

| Wave | Resource | Example Name | Why This Order |
|------|----------|-------------|----------------|
| **-1** | Job (PreSync) | `confirmation-selfreg-be-migration-job` | DB migrations BEFORE app starts |
| **0** | ExternalSecret | `confirmation-selfreg-be-demo-rolloutexternalsecret` | Fetch secrets from AWS SM |
| **0** | ExternalSecret | `confirmation-rmq-externalsecret-demo` | RabbitMQ credentials |
| **1** | Service | `confirmation-selfreg-be-demo-service` | Must exist before DR references it |
| **2** | DestinationRule | `confirmation-selfreg-be-demo-v*-destination-rule` | Subsets must exist before VS routes to them |
| **2** | AuthorizationPolicy | `confirmation-selfreg-be-demo-authorization-policy` | Access rules before traffic flows |
| **3** | VirtualService | `confirmation-selfreg-be-demo-virtualservice` | Routes traffic — needs Service + DR ready |
| **3** | VirtualService | `confirmation-selfreg-be-demo-op-virtualservice` | Internal route (same logic) |
| **4** | Rollout | `confirmation-selfreg-be-demo-rollout-*` | Pods created AFTER all networking is ready |
| **5** | HPA | `confirmation-selfreg-be-demo-hpa` | Auto-scaling starts after pods are running |

#### Canary Deployment During This Flow

When a new image tag is pushed for selfreg-be:

```
Time →

           │─ setWeight:50 ─│── pause:1m ──│── auto-promote ──│
           │                │              │                  │
 Stable:  100% ──────────► 50% ────────► 50% ──────────────► 100% (new version)
 Canary:    0% ──────────► 50% ────────► 50% ──────►  0% (old scaled down)
           │                │              │                  │
         deploy           shift          monitor            done
```

The Argo Rollout modifies the VirtualService weights and injects `rollouts-pod-template-hash` labels into the DestinationRule subsets so Istio knows which physical pods are stable vs canary.

#### Naming Convention — The Glue That Connects Everything

All resources reference each other through a consistent naming pattern:

```
Prefix:      confirmation
Service:     selfreg
Type:        be
Environment: demo

app.fullname = confirmation-selfreg-be
```

| Resource | Name Pattern | Example |
|----------|-------------|---------|
| Service | `{fullname}-{env}-service` | `confirmation-selfreg-be-demo-service` |
| VirtualService | `{fullname}-{env}-virtualservice` | `confirmation-selfreg-be-demo-virtualservice` |
| VirtualService (OP) | `{fullname}-{env}-op-virtualservice` | `confirmation-selfreg-be-demo-op-virtualservice` |
| DestinationRule | `{fullname}-{env}-v{tag}-destination-rule` | `confirmation-selfreg-be-demo-v1.0.0-9241a8e1-destination-rule` |
| Rollout | `{fullname}-{env}-rollout-{tag}` | `confirmation-selfreg-be-demo-rollout-1.0.0-9241a8e1` |
| AuthPolicy | `{fullname}-{env}-authorization-policy` | `confirmation-selfreg-be-demo-authorization-policy` |
| HPA | `{fullname}-{env}-hpa` | `confirmation-selfreg-be-demo-hpa` |
| Pod label | `{fullname}-{env}-rollout` | `confirmation-selfreg-be-demo-rollout` |

#### Environment Map

| Env | Namespace | Outpost Host | Internal Host | Cert Secret |
|-----|-----------|-------------|---------------|-------------|
| **CI** | `207804-confirmation-ci` | `ci-outpost.api.tr.confirmation.com` | `ci.api.tr.confirmation.com` | `ci-outpost-cert` |
| **Demo** | `207804-confirmation-demo` | `demo-outpost.api.tr.confirmation.com` | `demo.api.tr.confirmation.com` | `demo-outpost-cert` |
| **QA** | `207804-confirmation-qa` | `qa-outpost.api.tr.confirmation.com` | `qa.api.tr.confirmation.com` | `qa-outpost-cert` |
| **Preprod** | `207804-datawarehouse-preprod` | (KWAF + postgres-dwh only) | — | — |

All environments share: same F5 LB IP (10.230.34.4), same IngressGateway namespace (`private-ingressgateway`), same 3 IngressGateway pods.

#### Debug Commands (Quick Reference)

```bash
# Check the full flow for selfreg-be in demo
kubectl get gateway -n 207804-confirmation-demo | grep demo
kubectl get vs -n 207804-confirmation-demo | grep selfreg
kubectl get dr -n 207804-confirmation-demo | grep selfreg
kubectl get authorizationpolicy -n 207804-confirmation-demo | grep selfreg

# Check VirtualService weights (during canary)
kubectl get vs confirmation-selfreg-be-demo-virtualservice -n 207804-confirmation-demo \
  -o yaml | grep -A5 "weight"

# Check DestinationRule subsets (see rollouts-pod-template-hash)
kubectl get dr -n 207804-confirmation-demo -o yaml | grep -A5 "subsets"

# View cert domains
kubectl get secret demo-outpost-cert -n private-ingressgateway \
  -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -text -noout | grep -A1 "Subject Alternative Name"

# Check Envoy sidecar logs for traffic issues
kubectl logs <pod-name> -n 207804-confirmation-demo -c istio-proxy --tail=50

# Watch rollout progress
kubectl argo rollouts get rollout confirmation-selfreg-be-demo-rollout-1.0.0-9241a8e1 \
  -n 207804-confirmation-demo -w
```

#### Interview Answer — Full Story Format

> "Let me walk you through a real request on our Confirmation platform. Say an auditor hits our self-registration API:
>
> The request goes to `demo-outpost.api.tr.confirmation.com`, which DNS resolves to our F5 load balancer at 10.230.34.4. The F5 does TLS passthrough — it doesn't terminate TLS, just forwards to the EKS cluster's NodePort.
>
> Inside the cluster, the Istio IngressGateway receives the request. We run 3 IngressGateway pods for HA in the `private-ingressgateway` namespace. The IngressGateway reads the TLS SNI header to figure out which Gateway config to use. It finds `demo-ingress-gateway`, loads the cert from `demo-outpost-cert` secret, and terminates TLS in SIMPLE mode. That's **Layer 1** of our encryption — external TLS.
>
> Now the request is plaintext HTTP inside the mesh. The VirtualService matches the path prefix `/api/confirmation/selfregistration` and routes to the `confirmation-selfreg-be-demo-service` with subset `stable` at 100% weight. During canary deployments, this weight shifts — Argo Rollouts automatically patches the VirtualService.
>
> The DestinationRule kicks in — it selects the stable pods using the `rollouts-pod-template-hash` label that Argo Rollouts injects, and applies `ISTIO_MUTUAL` TLS. That's **Layer 2** — pod-to-pod mTLS. Istiod auto-issues short-lived certs to each pod's Envoy sidecar and rotates them automatically.
>
> Before the request reaches the application container, the AuthorizationPolicy checks the source identity. We use zero-trust — only the IngressGateway's SPIFFE identity is allowed. Any pod-to-pod call that isn't from the IngressGateway gets denied.
>
> Finally, the request hits the .NET container on port 8080, running as UID 14000 with a read-only filesystem. The response flows back through the same encrypted path.
>
> All of this is deployed through ArgoCD with sync waves — secrets first (wave 0), Service (wave 1), DestinationRule and AuthPolicy (wave 2), VirtualService (wave 3), Rollout (wave 4), HPA (wave 5). The ordering ensures every dependency exists before it's referenced."

---
