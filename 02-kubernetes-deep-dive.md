# Section 2: Kubernetes Deep Dive

### 2.1 Kubernetes Architecture — Control Plane

Every K8s cluster has a **control plane** (brain) and **worker nodes** (muscle). Know every component.

```
                    ┌─── CONTROL PLANE (AWS manages in EKS) ───┐
                    │                                           │
User/CI ──kubectl──>│  API Server ──> etcd (cluster state DB)   │
                    │      │                                    │
                    │      ├──> Scheduler (assigns pods→nodes)  │
                    │      │                                    │
                    │      ├──> Controller Manager              │
                    │      │    ├─ ReplicaSet controller        │
                    │      │    ├─ Deployment controller        │
                    │      │    ├─ Node controller              │
                    │      │    └─ Service Account controller   │
                    │      │                                    │
                    │      └──> Cloud Controller Manager (AWS)  │
                    └───────────────────────────────────────────┘
```

| Component | What it does | Interview-level detail |
|-----------|-------------|----------------------|
| **API Server** | Front door to the cluster. ALL communication goes through it — kubectl, kubelet, controllers, everything. REST API over HTTPS. | "Every component talks to API server. It validates requests, authenticates (RBAC), and writes state to etcd." |
| **etcd** | Distributed key-value store. Holds ALL cluster state — pods, services, secrets, configmaps. | "etcd is the single source of truth. If etcd dies, you lose your cluster. That's why EKS manages it HA across 3 AZs." |
| **Scheduler** | Watches for unscheduled pods, picks the best node based on: resource requests, affinity rules, taints/tolerations, topology spread. | "Scheduler scores each node. Factors: available CPU/memory, node affinity, pod anti-affinity, taints." |
| **Controller Manager** | Runs control loops. Each controller watches a resource type and ensures actual state matches desired state. | "The Deployment controller ensures N replicas are running. If a pod dies, it creates a new one. Reconciliation loop." |

**Scenario Q: "Your kubectl commands are timing out. What could be wrong?"**

> "kubectl talks to the API Server. If it's timing out:
> 1. **API Server unreachable** — check if the EKS control plane endpoint is healthy (AWS manages this, rare but check AWS status)
> 2. **Network issue** — my machine can't reach the cluster endpoint. Check VPN, security groups, kubeconfig context
> 3. **API Server overloaded** — too many watchers or large LIST calls. Check with `kubectl get --raw /healthz`
> 4. **etcd slow** — if API server is up but slow, etcd might be under pressure (disk I/O). In EKS, this is AWS's problem — open a support case"

### 2.2 Worker Nodes — What Runs on Each Node

```
┌─── WORKER NODE ─────────────────────────────────────┐
│                                                      │
│  kubelet ──> talks to API Server, manages pods       │
│  kube-proxy ──> manages iptables/IPVS for Services   │
│  Container Runtime (containerd) ──> runs containers  │
│                                                      │
│  ┌─── Pod ──────────────┐  ┌─── Pod ──────────────┐ │
│  │ container(app)       │  │ container(app)       │ │
│  │ sidecar(istio-proxy) │  │ sidecar(istio-proxy) │ │
│  │ pause container      │  │ pause container      │ │
│  └──────────────────────┘  └──────────────────────┘ │
│                                                      │
│  DaemonSets: datadog-agent, aws-node (VPC CNI)       │
└──────────────────────────────────────────────────────┘
```

| Component | Role | Detail |
|-----------|------|--------|
| **kubelet** | Node agent. Receives pod specs from API Server, ensures containers are running. Reports node status back. | "kubelet is what actually starts/stops containers on the node. It also runs liveness/readiness probes." |
| **kube-proxy** | Maintains network rules (iptables or IPVS) so Services can route traffic to pods. | "When you create a Service, kube-proxy programs iptables rules on every node to forward traffic to the right pods." |
| **Container Runtime** | Runs containers. EKS uses `containerd` (Docker was deprecated in K8s 1.24). | "We use containerd. Docker shim was removed in K8s 1.24. Doesn't affect us — our Dockerfiles still work, containerd just runs them." |
| **pause container** | Holds the network namespace for the pod. All containers in a pod share this namespace. | "The pause container is why containers in the same pod can talk via localhost." |

**Scenario Q: "A node shows NotReady status. How do you troubleshoot?"**

> "NotReady means kubelet stopped reporting to the API Server, or node conditions failed.
> 1. `kubectl describe node <name>` — check Conditions: MemoryPressure, DiskPressure, PIDPressure, Ready
> 2. If MemoryPressure/DiskPressure — node is running out of resources, kubelet starts evicting pods
> 3. SSH to node (if possible) → check `systemctl status kubelet` — is it running?
> 4. Check `/var/log/messages` or `journalctl -u kubelet` for errors
> 5. Common in Outposts: network hiccup between Outpost rack and AWS Region breaks kubelet→API Server heartbeat. Usually self-heals in 40s (node-monitor-grace-period)
> 6. If node stays NotReady → cordon it (`kubectl cordon`), drain pods (`kubectl drain --ignore-daemonsets`), investigate or replace"

### 2.3 Pod Lifecycle — Know Every State

```
Pending ──> ContainerCreating ──> Running ──> Succeeded/Failed
                                    │
                                    └──> CrashLoopBackOff (restart loop)
```

| State | Meaning | Common cause |
|-------|---------|-------------|
| **Pending** | Scheduler can't find a node | Insufficient CPU/memory, no matching nodeSelector, PVC not bound |
| **ContainerCreating** | Image pulling or volumes mounting | Slow ECR pull, ImagePullBackOff (wrong tag/auth), volume mount timeout |
| **Running** | At least one container running | Normal state |
| **CrashLoopBackOff** | Container crashes, kubelet backs off restart | App error, OOMKilled, missing config/secret |
| **ImagePullBackOff** | Can't pull image | Wrong image tag, ECR auth expired, rate limited |
| **Evicted** | Node under pressure, kubelet evicted pod | DiskPressure or MemoryPressure on node |
| **Terminating** | Pod is shutting down | Stuck if finalizers exist or preStop hook hangs |

**Scenario Q: "Pods are stuck in Pending. What do you check?"**

> "Pending means the scheduler can't place the pod.
> 1. `kubectl describe pod` → Events section shows WHY
> 2. **Insufficient resources**: Node has 4Gi free, pod requests 8Gi → `0/5 nodes have sufficient memory`
>    - Fix: scale up node group, or reduce resource requests
> 3. **Node selector mismatch**: Pod has `nodeSelector: outpost=true` but no nodes have that label
> 4. **PVC not bound**: If pod mounts a PVC and the PVC is Pending → check StorageClass, provisioner
> 5. **Taints**: Node has taint `dedicated=database:NoSchedule` but pod has no toleration
> 6. **Pod anti-affinity**: Pod says "don't schedule on same node as another replica" but only 1 node available"

### 2.4 Resource Management — Requests vs Limits

This is a MUST-KNOW concept. Interviewers love this.

| Term | What it means | Effect |
|------|--------------|--------|
| **Request** | Guaranteed minimum resources for the pod | Scheduler uses this to decide which node. Pod ALWAYS gets this much. |
| **Limit** | Maximum resources the pod can use | If pod exceeds memory limit → OOMKilled. If pod exceeds CPU limit → throttled (not killed). |

```yaml
resources:
  requests:
    cpu: 250m       # 0.25 CPU core guaranteed
    memory: 512Mi   # 512 MiB guaranteed
  limits:
    cpu: 1000m      # can burst up to 1 core
    memory: 1Gi     # killed if exceeds 1 GiB
```

**Key concept: QoS Classes** (determined by how you set requests/limits)

| QoS Class | Condition | Eviction priority |
|-----------|-----------|-------------------|
| **Guaranteed** | requests = limits for ALL containers | Last to be evicted (safest) |
| **Burstable** | requests < limits (at least one set) | Evicted after BestEffort |
| **BestEffort** | No requests or limits set at all | First to be evicted |

> "In our Helm charts, every service has both requests and limits. Critical services like PostgreSQL and RabbitMQ have requests=limits (Guaranteed QoS) so they're never evicted. Application pods are Burstable — they get a guaranteed baseline but can burst during spikes."

**Scenario Q: "Your .NET service keeps getting OOMKilled. How do you handle it?"**

> "OOMKilled means the container exceeded its memory limit.
> 1. `kubectl describe pod` → check `Last State: Terminated, Reason: OOMKilled`
> 2. Check Datadog: `env:ci service:<name>` → look at memory usage pattern
> 3. Is it a memory leak or genuine need?
>    - **Gradual climb** = memory leak in the .NET app → escalate to dev team
>    - **Spike during load** = limit too tight → increase memory limit in Helm values
> 4. In our Helm values: `resources.limits.memory: 1Gi` → try `1.5Gi`
> 5. After changing: merge to Helm chart → ArgoCD auto-syncs → Argo Rollout does canary with new limits
> 6. Monitor in Datadog for 24h to confirm stability"

### 2.5 Scheduling — Affinity, Taints, Tolerations

These control WHERE pods run. Critical for Outposts.

**Node Affinity** — "I want to run on specific nodes"

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:  # HARD rule - must match
      nodeSelectorTerms:
        - matchExpressions:
            - key: topology.kubernetes.io/zone
              operator: In
              values: ["us-east-1-op1"]  # Outpost zone
```

**Pod Anti-Affinity** — "Don't put me on the same node as my replica"

```yaml
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:  # SOFT rule - try to spread
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchLabels:
              app: rabbitmq
          topologyKey: kubernetes.io/hostname
```

**Taints & Tolerations** — "This node is special, only matching pods allowed"

```yaml
# On the node (taint):
kubectl taint nodes db-node-1 dedicated=database:NoSchedule

# On the pod (toleration):
tolerations:
  - key: "dedicated"
    operator: "Equal"
    value: "database"
    effect: "NoSchedule"
```

| Concept | Analogy | Your usage |
|---------|---------|-----------|
| **nodeAffinity** | "I want to sit in this section" | Ensuring pods land on Outpost nodes, not cloud nodes |
| **podAntiAffinity** | "Don't seat me next to my twin" | Spreading RabbitMQ/PostgreSQL replicas across nodes for HA |
| **Taints** | "VIP section — invitation only" | Database nodes tainted so only DB pods schedule there |
| **Tolerations** | "I have an invitation to VIP" | PostgreSQL pods tolerate the database taint |

**Scenario Q: "How do you ensure your database pods run on dedicated nodes?"**

> "We use a combination of taints and node affinity.
> 1. **Taint the database nodes**: `dedicated=database:NoSchedule` — prevents any random pod from scheduling there
> 2. **Add toleration to PostgreSQL pods** in Helm chart — they're allowed on tainted nodes
> 3. **Add nodeAffinity** — PostgreSQL pods MUST schedule on nodes with label `role=database`
> 4. This guarantees: database pods run only on dedicated nodes, and no other pods compete for resources on those nodes"

### 2.6 Kubernetes Networking — Services & DNS

**How pods communicate:**

```
Pod A (10.0.1.15) ──> Service "my-svc" (ClusterIP 172.20.0.50) ──> Pod B (10.0.2.30)
                                    │
                          kube-proxy iptables rule
                          randomly selects a backend pod
```

| Service Type | What it does | When to use |
|-------------|-------------|-------------|
| **ClusterIP** | Internal-only IP. Accessible only within cluster. | 95% of our services — internal microservice-to-microservice |
| **NodePort** | Opens a port (30000-32767) on every node | Rarely used — Istio handles external routing |
| **LoadBalancer** | Creates an AWS ELB/NLB | Istio IngressGateway uses this for external traffic |
| **Headless** (ClusterIP: None) | No virtual IP — DNS returns individual pod IPs | StatefulSets like RabbitMQ and PostgreSQL |

**DNS in Kubernetes:**

Every Service gets a DNS entry: `<service-name>.<namespace>.svc.cluster.local`

> "In our platform, if `pricing-be` in namespace `207804-confirmation-ci` needs to talk to `nucleus-be`, it calls `nucleus-be.207804-confirmation-ci.svc.cluster.local`. But with Istio, traffic goes through the sidecar proxy, so the DNS resolution is intercepted by Envoy."

**Scenario Q: "Service A can't reach Service B. How do you debug?"**

> "Network debugging in K8s — I follow this order:
> 1. **Is Service B running?** `kubectl get pods -l app=service-b` — check if pods are Ready
> 2. **Is the Service endpoint populated?** `kubectl get endpoints service-b` — if empty, label selector doesn't match pods
> 3. **DNS resolution works?** Exec into Service A pod: `kubectl exec -it <pod> -- nslookup service-b`
> 4. **Port correct?** Service port might differ from container port (targetPort)
> 5. **Istio blocking it?** Check AuthorizationPolicy — might be denying traffic from Service A's service account
> 6. **NetworkPolicy?** If cluster uses NetworkPolicies, check if ingress from Service A is allowed
> 7. **Test direct pod-to-pod**: `kubectl exec -it <pod-a> -- curl http://<pod-b-ip>:<port>/health` — bypasses Service layer"

### 2.7 EKS Specific Concepts

**IRSA — IAM Roles for Service Accounts**

```
K8s ServiceAccount ──annotated with──> IAM Role ARN
        │
    Pod assumes that role via OIDC federation
        │
    AWS API calls use role credentials (no static keys!)
```

> "IRSA eliminates the need for AWS access keys in pods. We annotate the Kubernetes ServiceAccount with an IAM role ARN. When the pod starts, the AWS SDK automatically gets temporary credentials through OIDC federation. We use this for pods that need Secrets Manager access, S3 access, DynamoDB access — all without a single credential stored anywhere."

**VPC CNI — How EKS networking works**

> "EKS uses the VPC CNI plugin. Each pod gets a real VPC IP address (not an overlay network). This means pods can talk directly to RDS, ElastiCache, and other VPC resources without NAT. The tradeoff: you need enough IP addresses in your subnets. Each EC2 instance has a limit on ENIs and IPs per ENI."

**Scenario Q: "Pods can't get IP addresses — new pods stuck in Pending."**

> "This is an IP exhaustion issue with VPC CNI.
> 1. Each EC2 instance type has a max ENI count and IPs per ENI. For example, `m5.xlarge` = 4 ENIs x 15 IPs = 58 pod IPs max per node
> 2. Check: `kubectl describe node` → look at `Allocatable: pods` and current count
> 3. Solutions:
>    - **Prefix delegation**: Enable VPC CNI prefix mode — assigns /28 prefixes instead of individual IPs, 16x more IPs per ENI
>    - **Scale out**: Add more nodes to the node group
>    - **Larger subnets**: If CIDR is exhausted, add secondary CIDR ranges
> 4. In Outposts specifically, IP range is constrained to the on-prem network allocation, so this is a real concern we monitor"

### 2.8 Key Kubernetes Objects Deep Dive

**Deployment vs StatefulSet vs DaemonSet**

| Resource | Use case | Pod identity | Storage | Scaling |
|----------|---------|-------------|---------|---------|
| **Deployment** | Stateless apps (API, web) | Pods are interchangeable, random names | Shared or none | HPA can scale |
| **StatefulSet** | Stateful apps (DB, MQ) | Stable names: `rabbitmq-0`, `rabbitmq-1` | Each pod gets own PVC | Ordered scale up/down |
| **DaemonSet** | One pod per node (agents) | One per node, scheduled automatically | Node-local | Scales with nodes |

> "Our .NET microservices use Argo Rollouts (superset of Deployment) for canary. PostgreSQL and RabbitMQ use StatefulSets — they need stable network identity and persistent storage. Datadog agent runs as a DaemonSet — one agent pod per node collecting metrics from all pods on that node."

**Scenario Q: "Why can't you use a Deployment for your database?"**

> "Deployments treat all pods as interchangeable. If a Deployment pod dies and restarts:
> - It gets a new name (random suffix)
> - It might get a different PVC (or none)
> - Other pods can't reliably find it
>
> StatefulSet guarantees:
> - **Stable names**: `postgres-0`, `postgres-1` — always the same
> - **Stable storage**: Each pod binds to its own PVC, survives restarts
> - **Ordered operations**: Scale up 0→1→2, scale down 2→1→0
> - **Stable DNS**: `postgres-0.postgres-headless.namespace.svc.cluster.local`
>
> For PostgreSQL HA, the primary is always `postgres-0` and replicas know to connect to it by name."

### 2.9 HPA — Horizontal Pod Autoscaler

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: my-service-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: my-service
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70   # scale up when avg CPU > 70%
```

| Setting | What it means |
|---------|--------------|
| `minReplicas: 2` | Never go below 2 pods (HA minimum) |
| `maxReplicas: 10` | Cap at 10 to prevent runaway scaling |
| `averageUtilization: 70` | When avg CPU across all pods exceeds 70%, add a pod |
| Cooldown (default) | Scale up: 0s (immediate), Scale down: 5 min (prevents flapping) |

**Scenario Q: "Your service is getting slow during peak hours but HPA isn't scaling. Why?"**

> "Several possible causes:
> 1. **Metrics Server not running** — HPA needs metrics-server to get CPU/memory data. Check: `kubectl top pods`
> 2. **Resource requests not set** — HPA calculates utilization as `actual / request`. If no request is set, it can't compute percentage
> 3. **Already at maxReplicas** — check `kubectl get hpa` — if current = max, it can't scale further
> 4. **Bottleneck isn't CPU/memory** — if the slowness is due to database connection pool exhaustion or external API latency, CPU stays low and HPA won't trigger
> 5. **Custom metrics needed** — for RabbitMQ queue depth or HTTP request rate, you need custom metrics adapter (Datadog Metrics Server)"

### 2.10 Your 8 Environments

| Environment | Namespace | Cluster | Purpose |
|-------------|-----------|---------|---------|
| CI | `207804-confirmation-ci` | non-prod | Continuous Integration, automated tests |
| Demo | `207804-confirmation-demo` | non-prod | Stakeholder demos, UAT |
| QA | `207804-confirmation-qa` | non-prod | QA team testing |
| Preprod | `207804-datawarehouse-preprod` | preprod | Pre-production validation |
| Prod | `207804-confirmation-prod` | prod | Live production |
| DR | `207804-confirmation-proddr` | prod-dr | Disaster Recovery |
| QED | `207804-confirmation-qed` | qed | Quality Engineering |
| Sandbox | `207804-confirmation-sbx` | sandbox | Experimentation |

> "I manage 8 environments across 4 clusters. Non-prod environments (CI, Demo, QA) have auto-sync enabled in ArgoCD. Production, DR, QED, and Sandbox require manual sync approval — separation of duties."

### 2.11 Secrets Management — ExternalSecrets Operator

```
AWS Secrets Manager                     Kubernetes
┌──────────────────┐                  ┌────────────────────────┐
│ /207804/ci/      │   ExternalSecret │ Secret: my-service     │
│   DB_PASSWORD    │──── Operator ───>│   DB_PASSWORD: ****    │
│   API_KEY        │    (syncs every  │   API_KEY: ****        │
│   DD_API_KEY     │     5 minutes)   │   DD_API_KEY: ****     │
└──────────────────┘                  └────────────────────────┘
                                              │
                                       Pod mounts as env var
                                       or volume
```

**Your answer**: "We never put secrets in Helm values or Git. AWS Secrets Manager is the source of truth. ExternalSecrets Operator runs in the cluster and syncs them into native K8s Secrets. Each service's Helm chart has an ExternalSecret CRD that maps AWS paths to K8s secret keys. The operator polls every 5 minutes, so rotation is automatic — change it in AWS, K8s picks it up."

**Scenario Q: "A secret was rotated in AWS but the application is still using the old value. Why?"**

> "Several layers to check:
> 1. **ExternalSecret sync interval** — default is 5 min. Check `kubectl get externalsecret` → SYNCED status
> 2. **K8s Secret updated but pod not restarted** — environment variables are injected at pod start. If the secret changes, running pods still use the old value
> 3. **Fix**: We use **Reloader Operator** pattern — it watches for Secret changes and triggers rolling restart. OR we do a manual rollout: `kubectl rollout restart deployment/my-service`
> 4. If using volume-mounted secrets, Kubernetes eventually updates the mount (kubelet sync period ~1 min), but apps may cache the file content"

### 2.12 PVC & Storage Deep Dive

**Storage flow:**

```
StorageClass (defines provisioner) ──> PVC (requests storage) ──> PV (actual disk, auto-created)
      │                                       │                          │
   gp2 (EBS)                           200Gi RWO                   AWS EBS volume
```

| Term | What | Detail |
|------|------|--------|
| **StorageClass** | Template for creating volumes | Defines provisioner (EBS, EFS), reclaim policy, expansion |
| **PV** | Actual persistent volume | In dynamic provisioning, created automatically by StorageClass |
| **PVC** | Request for storage | Pod references this — "I need 200Gi of gp2 storage" |
| **Access Modes** | Who can mount | RWO (one node), ROX (many nodes read), RWX (many nodes read-write) |
| **Reclaim Policy** | What happens when PVC deleted | Retain (keep data) or Delete (destroy volume) |

> "For PostgreSQL we use `Retain` reclaim policy — if we ever delete the PVC, the data stays on the EBS volume. For temporary workloads, `Delete` is fine. PVC expansion: we grew PostgreSQL from 200Gi to 600Gi by editing the PVC spec — StorageClass has `allowVolumeExpansion: true`. Key rule: you can only expand, never shrink."

**Scenario Q: "Your PVC is stuck in Pending. What's wrong?"**

> "PVC Pending means the provisioner can't create the PV.
> 1. **StorageClass doesn't exist** — `kubectl get sc` to verify
> 2. **No capacity** — in Outposts, local EBS capacity is finite (unlike cloud). Check Outpost capacity
> 3. **Zone mismatch** — PVC requests a zone where no nodes exist
> 4. **WaitForFirstConsumer** — StorageClass has `volumeBindingMode: WaitForFirstConsumer`. PVC stays Pending until a pod actually needs it. This is normal and correct for topology-aware scheduling.
> 5. **Provisioner broken** — check the EBS CSI driver pods: `kubectl get pods -n kube-system -l app=ebs-csi-controller`"

### 2.13 AWS Cloud vs AWS Outposts — The Core Difference

**AWS Cloud**: Workloads run in AWS data centers (us-east-1, etc.)
**AWS Outposts**: AWS ships a physical rack to YOUR data center. Same AWS services, but hardware sits in your building.

```
AWS Cloud (us-east-1)               TR Data Center
┌──────────────────────┐           ┌──────────────────────────────┐
│ EKS Control Plane    │           │  ┌── AWS Outpost Rack ────┐  │
│ (API Server, etcd)   ├──manages──│  │ Worker Nodes (EC2)     │  │
│                      │           │  │ Pods (your apps)       │  │
│ S3, DynamoDB, RDS    │           │  │ EBS (local storage)    │  │
└──────────────────────┘           │  └────────────────────────┘  │
         │                         │  On-prem DB ◄── same LAN ──► │
         └── AWS Service Link ─────│  Legacy systems              │
                                   └──────────────────────────────┘
```

| Aspect | EKS (Cloud) | EKS on Outposts |
|--------|------------|-----------------|
| **Where pods run** | AWS data center | Your data center (on-prem rack) |
| **Control plane** | In AWS Region | **Same** — still in AWS Region |
| **Worker nodes** | EC2 in cloud VPC | EC2 on Outpost rack |
| **Network** | AWS VPC (cloud CIDR) | On-prem network (your CIDR) |
| **Latency to on-prem** | High (VPN/DirectConnect) | Sub-millisecond (same LAN) |
| **Storage** | EBS (unlimited, cloud) | EBS local to Outpost (finite capacity) |
| **IP addresses** | Large VPC CIDR | On-prem CIDR (constrained) |
| **Capacity** | Virtually unlimited | Fixed by rack size — plan ahead |
| **Link goes down** | Normal operation | Existing pods run, no new deployments |
| **Data residency** | Data in AWS Region | Data stays in your building |

**Why TR chose Outposts:**
1. **Data residency** — financial data must stay within TR's physical boundary
2. **Low latency** — microservices talk to on-prem DBs; cloud adds 5-10ms over DirectConnect
3. **Hybrid consistency** — same K8s APIs, same Helm charts, same ArgoCD pipeline

**The Proxy Problem (unique to Outposts):**
On Outposts, pods are on-prem. To reach AWS services (S3, DynamoDB, Secrets Manager), traffic must go through corporate proxy to the Region. But K8s internal traffic and on-prem DB traffic must NOT use the proxy.

```yaml
# Per-service proxy config in Helm values:
env:
  HTTP_PROXY: "http://proxy.corp:8080"
  HTTPS_PROXY: "http://proxy.corp:8080"
  NO_PROXY: "10.0.0.0/8,.svc,.cluster.local,dynamodb.us-east-1.amazonaws.com,..."
```

Each service needs custom NO_PROXY — DynamoDB via VPC endpoint (bypass proxy), external FTP (needs proxy), K8s API (bypass). This was the hardest part of the migration.

**Scenario Q: "Connection between Outpost and AWS Region goes down. What happens?"**

> "Existing pods keep running — kubelet manages them locally. But:
> - Can't deploy new pods (scheduler is in Region)
> - Can't create/delete resources (API Server in Region)
> - No scaling, no config changes
> - DNS/Service discovery continues (CoreDNS cached)
> - Impact: platform stays up but frozen
> - Recovery: once link restores, everything syncs automatically"

### 2.14 Migration Story (This WILL be asked)

**Q: Tell me about the Cloud to Outposts migration.**

> **Situation**: When I joined in January 2025, the Confirmation platform (40+ .NET microservices) was running on standard AWS EKS in the cloud.
>
> **Task**: Migrate 30+ services to EKS Outposts for data locality and compliance — the platform needs low-latency access to on-prem databases and must meet data residency requirements.
>
> **Action**:
> 1. **Helm chart updates** — Updated node affinity/selectors, storage classes, resource limits for Outpost node types
> 2. **30+ services** — Each service needed its Helm values validated per environment
> 3. **8 environments** — Rolled out CI first (lowest risk), then Demo/QA, then Preprod, and finally Prod/DR
> 4. **Networking** — Outpost nodes join the on-prem network, so security groups, Istio config, and proxy settings all needed updating
> 5. **HTTPS proxy** — Rolled out proxy config across all 40+ services with per-service NO_PROXY tuning for DynamoDB, K8s CIDRs, FTP endpoints
> 6. **Zero-downtime** — Used Argo Rollouts canary strategy, migrated traffic gradually
>
> **Challenges**:
> - Storage class differences between cloud EBS and Outpost-local EBS
> - Proxy configuration was service-specific — some services talk to DynamoDB (needs proxy bypass), others to external FTP
> - IP address management — Outpost uses on-prem CIDR, more constrained than cloud VPC
> - Coordinated with infra team for Outpost rack capacity planning
>
> **Result**: All 30+ services migrated successfully by September 2025 with zero downtime. 8 environments fully operational on Outposts.

### 2.14 Advanced Scenario Questions

**Q: "A deployment rollout is stuck. How do you troubleshoot?"**

> "A stuck rollout usually means new pods aren't becoming Ready.
> 1. `kubectl rollout status deployment/my-service` — shows progress
> 2. `kubectl get pods` — look for new pods in Pending/CrashLoopBackOff/ImagePullBackOff
> 3. If Pending → scheduling issue (see 2.3 above)
> 4. If CrashLoopBackOff → app error (check logs of new pods)
> 5. If Running but not Ready → readiness probe failing. `kubectl describe pod` → check probe config and endpoint
> 6. Common trap: new image has a bug, readiness probe fails, rollout waits forever for Ready. Fix: `kubectl rollout undo deployment/my-service` to rollback, then fix the image"

**Q: "How do you handle a Kubernetes cluster upgrade?"**

> "EKS makes this manageable:
> 1. **Control plane first**: AWS upgrades the control plane (API server, etcd, controllers). In EKS, one click — but validate compatibility first
> 2. **API deprecations**: Before upgrading, check if any deprecated APIs are used — `kubectl deprecations` or tools like pluto. For example, K8s 1.25 removed PodSecurityPolicy
> 3. **Worker nodes**: Update the managed node group AMI. Use rolling update — drains one node at a time, reschedules pods, then terminates old node
> 4. **Add-ons**: VPC CNI, CoreDNS, kube-proxy, EBS CSI driver — all need version-compatible updates
> 5. **Testing**: Upgrade non-prod first (CI environment), validate all services, then roll to higher environments
> 6. **Rollback plan**: Can't downgrade EKS control plane. If something breaks, rollback by fixing the workload, not the cluster version"

**Q: "How do you handle node maintenance or drain a node?"**

> "`kubectl drain` gracefully evicts all pods from a node.
> 1. `kubectl cordon <node>` — marks node as unschedulable (no new pods)
> 2. `kubectl drain <node> --ignore-daemonsets --delete-emptydir-data` — evicts all pods
> 3. DaemonSet pods stay (--ignore-daemonsets) — they're supposed to be on every node
> 4. Pods with PodDisruptionBudget (PDB) are respected — drain waits until PDB allows eviction
> 5. Once drained: perform maintenance (OS patch, instance type change, etc.)
> 6. `kubectl uncordon <node>` — makes node schedulable again
>
> We set PDBs on critical services: `minAvailable: 1` ensures at least one pod stays running during drain."

**Q: "What is a PodDisruptionBudget and why is it important?"**

> "PDB protects availability during voluntary disruptions — node drain, cluster upgrade, pod eviction.
> ```yaml
> apiVersion: policy/v1
> kind: PodDisruptionBudget
> spec:
>   minAvailable: 1        # OR maxUnavailable: 1
>   selector:
>     matchLabels:
>       app: my-service
> ```
> Without PDB: `kubectl drain` evicts ALL pods at once → downtime.
> With PDB `minAvailable: 1`: drain evicts one pod at a time, waits for replacement to be Ready before evicting the next."

**Q: "What's the difference between `kubectl delete pod` and `kubectl drain node`?"**

> "Very different:
> - `kubectl delete pod` — kills one specific pod. Controller creates a replacement immediately. No coordination.
> - `kubectl drain node` — gracefully evicts ALL pods from a node. Respects PDBs, waits for graceful termination (terminationGracePeriodSeconds), ensures pods are rescheduled elsewhere first. Used for planned maintenance."

**Q: "How do you debug a service that's intermittently slow?"**

> "Intermittent slowness is the hardest to debug. My approach:
> 1. **Datadog APM traces** — look at p99 latency, find the slow requests. `@duration_ms:>5000` in Datadog
> 2. **Is it pod-specific?** If only one pod is slow → could be noisy neighbor, GC pause, or node issue
> 3. **Resource throttling?** Check CPU throttling: `container_cpu_cfs_throttled_seconds_total` metric. If CPU limit is too low, container gets throttled
> 4. **Network?** Istio sidecar adds latency. Check Envoy metrics for upstream response time vs total time
> 5. **Dependency?** The service itself might be fast but waiting on a slow DB query or external API
> 6. **HPA flapping?** If pods keep scaling up and down, new pods taking traffic before warm-up
> 7. Correlate with node metrics — if the node is overloaded, all pods on it suffer"

---
