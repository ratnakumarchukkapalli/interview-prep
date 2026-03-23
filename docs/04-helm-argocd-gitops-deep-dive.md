# Section 4: Helm & ArgoCD GitOps — Deep Dive

### 4.1 What is Helm?

Helm is a **package manager for Kubernetes**. Instead of writing 10+ YAML files per service (Deployment, Service, VirtualService, DestinationRule, ExternalSecret, HPA, PDB, etc.), you write **templates** with variables and a `values.yaml` to fill them.

```
Without Helm (per service, per environment):
  pricing-be-ci-deployment.yaml
  pricing-be-ci-service.yaml
  pricing-be-ci-virtualservice.yaml
  pricing-be-ci-destinationrule.yaml
  ... × 40 services × 8 environments = 2000+ YAML files 😵

With Helm:
  charts/pricing-be/templates/  ← shared templates
  environments/ci/pricing-be/values.yaml   ← CI-specific values
  environments/demo/pricing-be/values.yaml ← Demo-specific values
  ... only the VALUES change per environment
```

**Helm concepts:**

| Concept | What it is | Your usage |
|---------|-----------|-----------|
| **Chart** | A package of K8s templates | One chart per service: `charts/audit-devops-assistant/` |
| **Template** | YAML with `{{ .Values.xxx }}` placeholders | `rollout.yaml`, `virtual-service.yaml`, etc. |
| **values.yaml** | Default values for the chart | Chart-level defaults in `charts/<svc>/values.yaml` |
| **Override values** | Environment-specific values | `environments/ci/<svc>/values.yaml` overrides defaults |
| **Release** | A deployed instance of a chart | ArgoCD manages releases — one per service per environment |
| **Helpers (_helpers.tpl)** | Reusable template functions | `app.fullname`, `app.labels`, `app.trAnnotations` |

> **Interview answer**: "Helm is our templating engine for Kubernetes manifests. Each service has a Helm chart with templates for Rollout, Service, VirtualService, DestinationRule, AuthorizationPolicy, ExternalSecret, HPA, and PDB. Environment-specific values override the defaults. This means I maintain one set of templates but deploy to 8 different environments with different configurations."

### 4.2 Our Helm Repository Structure

We have **two Helm repos** — one for non-prod, one for prod:

```
audit-devops-confirmation-helm-charts (non-prod)
├── charts/
│   ├── audit-devops-assistant/
│   │   ├── Chart.yaml
│   │   ├── values.yaml              ← chart defaults
│   │   └── templates/
│   │       ├── _helpers.tpl          ← shared template functions
│   │       ├── rollout.yaml          ← Argo Rollout (canary)
│   │       ├── service.yaml          ← K8s Service
│   │       ├── virtual-service.yaml  ← Istio routing
│   │       ├── destination-rule.yaml ← Istio mTLS + subsets
│   │       ├── authorization-policy.yaml ← access control
│   │       ├── rollout-externalsecret.yaml ← AWS secrets
│   │       ├── service-entry.yaml    ← external egress
│   │       ├── hpa.yaml              ← autoscaler
│   │       ├── pdb.yaml              ← disruption budget
│   │       └── serviceaccount.yaml
│   ├── pricing-be/
│   ├── nucleus-be/
│   ├── ... (40+ service charts)
│   └── kwaf-service-mesh/            ← shared Gateway, PeerAuth
│
├── environments/
│   ├── ci/
│   │   ├── audit-devops-assistant/
│   │   │   └── values.yaml           ← CI overrides (image tag, replicas, env vars)
│   │   ├── pricing-be/
│   │   │   └── values.yaml
│   │   └── ...
│   ├── demo/
│   │   └── ...
│   └── qa/
│       └── ...

audit-itops-confirmation-helm-charts (prod/DR/QED/SBX)
├── charts/                           ← same structure
├── environments/
│   ├── prod/
│   ├── proddr/
│   ├── qed/
│   └── sbx/
```

**Why two repos?**
> "Separation of concerns and access control. The non-prod repo (CI, Demo, QA) allows faster iteration — developers can push image tags freely. The prod repo (Prod, DR, QED, Sandbox) has stricter review gates. Different teams have write access to different repos."

### 4.3 How Values Override Works

```
Chart defaults (charts/svc/values.yaml)
        │
        └── overridden by ──> Environment values (environments/ci/svc/values.yaml)
                                       │
                                       └── what ArgoCD actually deploys
```

**Example: audit-devops-assistant**

Chart `values.yaml` (defaults):
```yaml
replicas: 2
resources:
  limits:
    cpu: 1000m
    memory: 4Gi
  requests:
    cpu: 750m
    memory: 3Gi
environment: ci
```

Environment `environments/ci/values.yaml` (overrides):
```yaml
image:
  tag: "1ea56e47"            # CI-specific image tag
environment: ci
namespace: 207804-confirmation-ci
externalSecret:
  data:
    - secretKey: ESSO_TOKEN
      remoteRef:
        key: a207804-ue1-op-devops-assistant-sm    # CI secret path
        property: esso_token
```

> **Interview answer**: "Chart values.yaml has sensible defaults — replicas, resources, probes. Environment-specific values.yaml overrides what changes per environment — image tag, namespace, secret paths, domain names. ArgoCD merges them. This is key: I never hardcode environment-specific values in the chart template."

### 4.4 What is GitOps?

**Traditional deployment:**
```
Developer → runs kubectl/helm manually → Kubernetes cluster
            (imperative, no audit trail, error-prone)
```

**GitOps deployment:**
```
Developer → pushes to Git → ArgoCD watches Git → syncs to Kubernetes
            (declarative, full audit trail, self-healing)
```

**GitOps principles:**

| Principle | What it means | Our implementation |
|-----------|-------------|-------------------|
| **Git is the source of truth** | Cluster state is defined in Git, not in someone's terminal | All manifests in Helm chart repos |
| **Declarative** | You declare desired state, system converges | Helm templates define desired state |
| **Automated reconciliation** | System continuously compares actual vs desired | ArgoCD polls Git every 3 min |
| **Self-healing** | If someone manually changes cluster state, it reverts | ArgoCD prune + self-heal on non-prod |

> **Interview answer**: "GitOps means Git is the single source of truth for our cluster state. Nobody runs `kubectl apply` manually. To deploy a new version, you push an image tag to the Helm chart repo. ArgoCD detects the change, compares it with what's running in the cluster, and syncs. If someone manually changes something in the cluster, ArgoCD reverts it — self-healing. Every change has a Git commit, so we have complete audit trail."

### 4.5 What is ArgoCD?

ArgoCD is a **GitOps continuous delivery tool** for Kubernetes. It watches Git repos and ensures the cluster matches what's in Git.

```
┌─── ArgoCD ──────────────────────────────────────────────┐
│                                                          │
│  Application CRD                                         │
│  ┌────────────────────────────────────────────────┐     │
│  │ Name: audit-devops-assistant-ci                 │     │
│  │ Source: github.com/tr/helm-charts               │     │
│  │   Path: charts/audit-devops-assistant           │     │
│  │   Values: environments/ci/assistant/values.yaml │     │
│  │ Destination: EKS cluster, ns: 207804-*-ci       │     │
│  │ Sync Policy: automated (prune, self-heal)       │     │
│  └────────────────────────────────────────────────┘     │
│                                                          │
│  Every 3 min:                                            │
│  1. Pull latest from Git                                 │
│  2. Render Helm templates with values                    │
│  3. Compare rendered manifests with cluster state        │
│  4. If different → sync (apply changes)                  │
└──────────────────────────────────────────────────────────┘
```

**ArgoCD sync modes:**

| Mode | Behavior | Our usage |
|------|---------|-----------|
| **Auto-sync** | ArgoCD syncs automatically when Git changes | CI, Demo, QA — fast feedback loop |
| **Manual sync** | ArgoCD detects drift but waits for human approval | Prod, DR, QED, Sandbox — controlled releases |
| **Prune** | Deletes resources removed from Git | Enabled on non-prod — keeps cluster clean |
| **Self-heal** | Reverts manual changes in cluster | Enabled on non-prod — prevents drift |

> **Interview answer**: "Non-prod (CI, Demo, QA) has auto-sync with prune and self-heal — push to Git and it's deployed in minutes. Production requires manual sync — someone clicks 'Sync' in the ArgoCD UI after reviewing the diff. This separation ensures we can iterate fast in dev but have control gates for production."

### 4.6 ArgoCD ApplicationSets

**Problem**: With 40+ services × 8 environments, you'd need 320+ ArgoCD Application CRDs — manually created and maintained.

**Solution**: ApplicationSet — one template generates ALL Applications automatically.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: confirmation-services
spec:
  generators:
    - git:
        repoURL: https://github.com/tr/audit-devops-confirmation-helm-charts
        revision: main
        directories:
          - path: environments/ci/*      # Each subdirectory = one service
          - path: environments/demo/*
          - path: environments/qa/*
  template:
    metadata:
      name: '{{path.basename}}-{{path[1]}}'  # e.g., audit-devops-assistant-ci
    spec:
      source:
        repoURL: https://github.com/tr/audit-devops-confirmation-helm-charts
        path: 'charts/{{path.basename}}'
        helm:
          valueFiles:
            - '../../environments/{{path[1]}}/{{path.basename}}/values.yaml'
      destination:
        server: https://kubernetes.default.svc
        namespace: '207804-confirmation-{{path[1]}}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
```

> **Interview answer**: "We use ArgoCD ApplicationSets to auto-generate Applications. The git directory generator scans `environments/ci/`, `environments/demo/`, etc. Each subdirectory becomes an Application. When I add a new service — I create the chart in `charts/` and add values in `environments/ci/new-service/values.yaml` — ArgoCD automatically creates the Application. No manual Application CRD needed. I migrated frontend services from individual Applications to this unified ApplicationSet pattern, which eliminated the overhead of managing separate Application manifests."

### 4.7 ArgoCD Sync Waves

Resources need to deploy in order. You can't create a VirtualService before the Service it routes to.

```yaml
# Order:
annotations:
  argocd.argoproj.io/sync-wave: "0"   # ServiceAccount, RBAC (first)
  argocd.argoproj.io/sync-wave: "1"   # Gateway, PeerAuth, DestinationRule, ExternalSecret
  argocd.argoproj.io/sync-wave: "2"   # Service, AuthorizationPolicy
  argocd.argoproj.io/sync-wave: "3"   # VirtualService
  argocd.argoproj.io/sync-wave: "4"   # Rollout (last — needs Service + VirtualService ready)
  argocd.argoproj.io/sync-wave: "5"   # HPA, PDB (after Rollout exists)
```

**Our sync order:**

| Wave | Resources | Why this order |
|------|-----------|---------------|
| 0 | ServiceAccount, RBAC, ExternalSecret | Identity and secrets must exist first |
| 1 | Gateway, PeerAuthentication, DestinationRule | Network policies before routing |
| 2 | Service, AuthorizationPolicy | Service endpoint must exist before VirtualService routes to it |
| 3 | VirtualService | Routes to the Service created in wave 2 |
| 4 | Rollout | Creates pods — needs Service + VirtualService + DestinationRule all ready |
| 5 | HPA, PDB | Operates on the Rollout created in wave 4 |

> **Interview answer**: "Sync waves ensure resources deploy in the right order. ExternalSecret first so secrets exist before pods start. Service before VirtualService so routing has a target. Rollout last because it needs all networking resources ready. Without sync waves, you get race conditions — pods starting before secrets sync, or VirtualService routing to a Service that doesn't exist yet."

### 4.8 ArgoCD Hooks (PreSync, PostSync)

**Hooks** run jobs at specific sync phases:

| Hook | When it runs | Our usage |
|------|-------------|-----------|
| **PreSync** | Before the main sync starts | RabbitMQ CA bundle injection — inject TLS certs before broker pods restart |
| **Sync** | During the main sync (default) | Normal resources |
| **PostSync** | After all resources are synced and healthy | Smoke tests, notifications |
| **SyncFail** | If sync fails | Alert notifications |

**Our RabbitMQ CA bundle PreSync hook:**
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
spec:
  template:
    spec:
      containers:
        - name: ca-inject
          command: ["sh", "-c", "kubectl create secret tls rabbitmq-ca-bundle ..."]
      restartPolicy: Never
```

> **Interview answer**: "We use ArgoCD PreSync hooks for RabbitMQ CA bundle TLS injection. Before the main sync updates RabbitMQ pods, a PreSync Job injects the latest CA certificate into a Kubernetes Secret. This ensures the broker pods always start with the correct TLS certificate. The `hook-delete-policy: BeforeHookCreation` cleans up old Jobs so they don't pile up."

### 4.9 The Complete Deployment Flow (End-to-End)

This is the full story of how a code change reaches production:

```
1. Developer merges PR to .NET service repo
       │
2. GitHub Actions CI pipeline:
   ├── Build .NET app
   ├── Run tests
   ├── Build Docker image
   ├── Push to ECR (833618288067.dkr.ecr.us-east-1.amazonaws.com/a207804/<service>)
   └── Output: image tag (e.g., "abc12345")
       │
3. Developer updates image tag in Helm chart repo:
   └── environments/ci/<service>/values.yaml → image.tag: "abc12345"
       │
4. ArgoCD detects Git change (polls every 3 min):
   ├── Renders Helm templates with new values
   ├── Compares with cluster state
   └── Detects drift (image tag changed)
       │
5. ArgoCD syncs (auto on non-prod, manual on prod):
   ├── Wave 0: ExternalSecret, ServiceAccount
   ├── Wave 1: DestinationRule, Gateway
   ├── Wave 2: Service, AuthorizationPolicy
   ├── Wave 3: VirtualService
   └── Wave 4: Rollout (new image tag)
       │
6. Argo Rollout executes canary strategy:
   ├── Creates canary pod with new image
   ├── Updates VirtualService: 50% canary, 50% stable
   ├── Pauses 1 minute (observe in Datadog)
   └── Promotes to 100% → old pods terminated
       │
7. Service running new version ✅
```

> **Interview answer**: "Our deployment pipeline has three stages. CI builds the image and pushes to ECR. Then someone updates the image tag in the Helm chart repo. ArgoCD detects the change, renders templates, and syncs with sync waves in the right order. Finally, Argo Rollouts does a canary deployment — 50% traffic, pause to observe in Datadog, then promote. The entire process from Git push to production takes about 5 minutes for non-prod, and is human-gated for prod."

### 4.10 Common Interview Questions — Helm & ArgoCD

**Q: "What is the difference between `helm install` and ArgoCD?"**

| Aspect | helm install/upgrade | ArgoCD |
|--------|---------------------|--------|
| Execution | Imperative — you run a command | Declarative — you push to Git |
| Continuous | One-time operation | Continuous reconciliation (every 3 min) |
| Drift detection | None — deploy and forget | Detects manual changes, can self-heal |
| Audit trail | Need to check shell history | Full Git history |
| Rollback | `helm rollback <release> <revision>` | Git revert (natural) |
| Multi-cluster | Run manually per cluster | One ArgoCD manages multiple clusters |

> "We never run `helm install` manually. ArgoCD uses Helm as a template renderer — it runs `helm template` internally to generate manifests, then applies them with its own sync engine. This gives us Helm's templating power plus ArgoCD's continuous reconciliation."

**Q: "How do you rollback a failed deployment?"**

> "Two options:
> 1. **Argo Rollout abort**: During canary, if Datadog shows errors → `kubectl argo rollouts abort <name>` — instantly rolls back to stable
> 2. **Git revert**: Revert the image tag commit in the Helm chart repo. ArgoCD detects the revert, syncs, Argo Rollout deploys the old image via canary. This is the GitOps way — rollback is just another Git commit.
>
> We prefer Git revert because it maintains audit trail. The rollback itself is a commit."

**Q: "ArgoCD shows 'OutOfSync' but you didn't change anything. Why?"**

> "Common causes:
> 1. **Default values injected by K8s** — Kubernetes adds fields like `metadata.creationTimestamp`, `status` that aren't in Git. ArgoCD should ignore these (configure `ignoreDifferences`)
> 2. **Mutating webhooks** — Istio sidecar injection adds containers not in your manifest. ArgoCD sees extra containers → out of sync. Fix: add `jqPathExpressions` to ignore injected sidecars
> 3. **HPA changed replicas** — HPA scales to 5, but Helm says 2 replicas. ArgoCD sees drift. Fix: Don't specify replicas in Helm when HPA manages it, or configure ArgoCD to ignore `.spec.replicas`
> 4. **Someone ran kubectl manually** — Self-heal reverts it (on non-prod). On prod, investigate who and why."

**Q: "How do you promote from CI to QA to Prod?"**

> "We follow a promotion workflow:
> 1. **CI**: Push image tag to `environments/ci/values.yaml` → auto-deploy
> 2. **QA testing**: QA team validates on CI. If good, update `environments/qa/values.yaml` with same image tag
> 3. **Preprod**: Same image tag goes to `environments/preprod/values.yaml`
> 4. **Prod**: Update `environments/prod/values.yaml` in prod Helm repo (different Git repo). Manual sync in ArgoCD after review.
>
> The key: same Docker image flows through all environments. Only the values.yaml (config, secrets, domain) changes. We never rebuild the image for a different environment."

**Q: "How do you handle Helm chart upgrades across 40+ services?"**

> "For shared changes (like adding a new annotation or security context):
> 1. Update the template once in `charts/<service>/templates/`
> 2. If all services use the same template pattern — update the _helpers.tpl shared function
> 3. Test in CI environment first (auto-sync catches issues fast)
> 4. Roll out to Demo/QA, then Preprod, then Prod
>
> For image tag updates: each service has its own values.yaml, so updates are independent — one service can be on v2 in CI while another is on v1."

**Q: "What's the difference between Argo Rollouts and a standard Kubernetes Deployment rolling update?"**

| Aspect | K8s Deployment Rolling Update | Argo Rollouts Canary |
|--------|------------------------------|---------------------|
| Traffic control | None — new pods get traffic as soon as Ready | Precise weight control (10%, 50%, 100%) |
| Pause/observe | Not possible | Built-in pause steps |
| Automatic rollback | Only if probes fail | Rollback on abort, or based on analysis |
| Integration | None | Istio VirtualService, Datadog metrics |
| Observability | Check pod status | Observe live traffic metrics during canary |

> "Standard rolling update just replaces pods one by one. Argo Rollouts gives us traffic-aware canary — we shift 50% traffic to the new version, pause for 1 minute to check Datadog, then promote. If error rate spikes, we abort and it's instant rollback. With standard rolling update, by the time you notice errors, all pods might be on the new version."

**Q: "How do you handle secrets that differ per environment?"**

> "Secrets are NEVER in Git. Each environment has its own AWS Secrets Manager path:
> - CI: `a207804-ue1-op-devops-assistant-sm` (CI-specific secret)
> - Prod: `a207804-ue1-op-devops-assistant-prod-sm` (prod-specific secret)
>
> The ExternalSecret in `environments/ci/values.yaml` points to the CI secret path. The one in `environments/prod/values.yaml` points to the prod secret path. The template is the same — only the `remoteRef.key` value changes."

### 4.11 Scenario Questions — Helm & ArgoCD

**Q: "A new developer accidentally pushed wrong image tag to prod Helm repo. How do you handle it?"**

> "1. **Immediate**: ArgoCD is manual sync on prod, so it hasn't deployed yet. Check ArgoCD UI — it shows 'OutOfSync' with the diff
> 2. **If not yet synced**: Git revert the commit. Drift disappears. No impact.
> 3. **If already synced**: Argo Rollout is doing canary — check if canary pod is healthy. If not, it'll auto-rollback. If yes, abort the rollout: `kubectl argo rollouts abort <name>`
> 4. **Prevention**: Branch protection rules, PR reviews required for prod repo, separate prod repo with limited write access"

**Q: "ArgoCD can't sync — 'sync error: resource already exists'. What's wrong?"**

> "This means ArgoCD is trying to create a resource that already exists but isn't managed by this ArgoCD Application.
> 1. Someone created the resource manually (`kubectl create`) before ArgoCD
> 2. Another ArgoCD Application already manages it (duplicate)
> 3. Fix: Either delete the existing resource and let ArgoCD create it, or add the ArgoCD tracking label (`app.kubernetes.io/managed-by: argocd`) to the existing resource so ArgoCD adopts it"

**Q: "How do you test Helm chart changes before deploying?"**

> "1. `helm template . -f values.yaml` — renders templates locally, shows what YAML would be generated
> 2. `helm lint .` — validates chart structure and template syntax
> 3. Push to CI environment (auto-sync) — fastest real validation
> 4. ArgoCD preview diff — in the UI, you can see exactly what will change before clicking Sync
> 5. For complex changes: create a separate branch, point a test ArgoCD Application at that branch"
