# Section 5: CI/CD — GitHub Actions

### 5.1 GitHub Actions Fundamentals

**What is GitHub Actions?**

GitHub Actions is a CI/CD platform built into GitHub. Unlike Jenkins (separate server) or AWS CodePipeline (cloud-only), GitHub Actions runs directly alongside your code — same platform for source, CI, and CD.

**Core Concepts:**

| Concept | What It Is | Real Example |
|---------|-----------|--------------|
| **Workflow** | A YAML file in `.github/workflows/` that defines an automation pipeline | `ci.yml` — triggers on push to main |
| **Event** | What triggers the workflow | `push`, `pull_request`, `workflow_dispatch` (manual), `schedule` (cron) |
| **Job** | A set of steps that run on the same runner | `build-and-test`, `docker-push` |
| **Step** | A single task inside a job — either a shell command or an action | `run: pytest tests/` or `uses: actions/checkout@v4` |
| **Action** | A reusable unit of code (like a function) | `actions/checkout@v4`, `docker/build-push-action@v6` |
| **Runner** | The machine that executes your job | `ubuntu-latest`, `windows-latest`, self-hosted, CodeBuild |
| **Artifact** | Files produced by one job, consumed by another | Test reports, Docker images, ZIP bundles |
| **Secret** | Encrypted variable — never printed in logs | `${{ secrets.GIT_SVC_TOKEN }}` |

**Workflow YAML structure:**

```yaml
name: CI Pipeline                    # Display name in GitHub UI
on:                                  # WHEN to run
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:                  # Manual trigger button

jobs:
  build:                             # Job name
    runs-on: ubuntu-latest           # Runner
    steps:
      - uses: actions/checkout@v4    # Step 1: clone repo
      - run: pip install -r req.txt  # Step 2: shell command
      - run: pytest tests/ -v        # Step 3: run tests

  deploy:
    needs: build                     # Job dependency — runs AFTER build
    runs-on: ubuntu-latest
    steps:
      - run: echo "Deploying..."
```

**Key points interviewers test:**

1. **Jobs run in parallel by default** — use `needs:` to create dependencies
2. **Each job gets a fresh runner** — no state shared between jobs (use artifacts to pass data)
3. **Steps within a job run sequentially** on the same runner — they share filesystem
4. **`uses:`** calls an action (reusable), **`run:`** executes shell commands
5. **Secrets are masked** in logs automatically with `::add-mask::`

---

### 5.2 Reusable Workflows vs Composite Actions

This is a common interview question: **"How do you avoid duplicating CI/CD logic across 40+ repos?"**

GitHub Actions has two DRY mechanisms:

| Feature | Reusable Workflow | Composite Action |
|---------|-------------------|------------------|
| **Defined with** | `on: workflow_call` in a workflow YAML | `action.yml` in a directory |
| **Called with** | `uses: org/repo/.github/workflows/file.yml@ref` | `uses: org/repo/.github/actions/name@ref` |
| **Runs on** | Its own runner (separate job) | Same runner as the calling step |
| **Can have** | Multiple jobs, matrix strategies | Only steps (no jobs) |
| **Inputs** | `inputs:` + `secrets:` (explicit pass-through) | `inputs:` only (inherits environment) |
| **Best for** | Full pipelines (build→test→deploy) | Small reusable steps (checkout, login, cache) |

**Our real implementation — two layers:**

```
audit-cicd-templates/
├── .github/
│   ├── workflows/              # 54 reusable workflows (full pipelines)
│   │   ├── Build-Test-CollectMetrics.yml    # .NET build + SonarQube
│   │   ├── CreateDocker.yml                 # Docker build → ECR + JFrog
│   │   ├── audit-devops-portal-ci.yml       # Python microservice CI
│   │   ├── confirmation-deploy-qa.yml       # QA promotion with drift detection
│   │   └── ...
│   └── actions/                # 31 composite actions (reusable steps)
│       └── generic/
│           ├── git-config/     # Git SSH + user setup
│           ├── checkout/       # Custom checkout wrapper
│           ├── docker-login/   # Multi-registry auth
│           ├── npm-login/      # NPM registry auth
│           ├── sonar-steps/    # SonarQube scanning
│           ├── test-report/    # JUnit/coverage reporting
│           └── rush-*/         # 8 actions for Rush.js monorepo
```

**Interview Answer:**

> "We built a centralized CI/CD template library with 54 reusable workflows and 31 composite actions. Every service — whether .NET, Python, or Angular — calls the same templates from a single repo. When we need to update a security scanning step, we change it once in the template library, and all 40+ services pick it up automatically. Reusable workflows handle full pipelines (build→test→Docker→deploy), while composite actions handle small reusable steps like Docker login or SonarQube scanning."

---

### 5.3 The CI/CD Template Library (60+ Templates)

**Interview Question: "Walk me through your CI/CD template architecture"**

We have one central repo (`audit-cicd-templates`) that contains ALL CI/CD logic. Service repos contain thin caller workflows that pass parameters to the templates.

**Template categories:**

| Category | Count | Key Templates | Used By |
|----------|-------|---------------|---------|
| **.NET Build/Test** | 6 | `Build-Test-CollectMetrics.yml`, `netcore-microservice-deploy.yml` | nucleus-be, forms-be, 30+ services |
| **Docker/Container** | 4 | `CreateDocker.yml`, `CreateDocker-Windows.yml` | All backend services |
| **Python Microservice** | 1 | `audit-devops-portal-ci.yml` | service-ops, k8s-ops-assistant, db-ops, harness, dynamo |
| **Frontend (Angular/React)** | 6 | `reusable-build-test-fe.yml`, `reusable-publish-application-fe.yml` | self-registration-fe, portal |
| **Deployment/Promotion** | 5 | `confirmation-deploy-qa.yml`, `audit-promote-image.yml` | Environment promotions |
| **Security Scanning** | 3 | `sonar-prepare-template`, `sonar-analyze-publish-template` | All repos |
| **SPA Build/Deploy** | 4 | `spa-build.yml`, `spa-deploy.yml`, `angular-application-deploy.yml` | Legacy SPAs |
| **NuGet Publishing** | 2 | `netcore-nuget-publish.yml`, `netframework-nuget-publish.yml` | Shared libraries |
| **Infrastructure** | 3 | `ci_cd_yq.yml`, `build-and-bump-version.yml` | Utilities |

**How a service repo calls a template:**

```yaml
# In nucleus-be/.github/workflows/build_pipeline.yml (thin caller)
jobs:
  Build-Test:
    uses: tr/audit-cicd-templates/.github/workflows/Build-Test-CollectMetrics.yml@feature/confirmation-ghactions
    with:
      BuildConfiguration: Release
      SonarKey: com.thomsonreuters:ConfirmationCoreServices
    secrets:
      NugetToken: ${{ secrets.TR_ART_TOKEN }}
      SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}

  Build-Docker-Nucleus-Orl:
    needs: Build-Test
    uses: tr/audit-cicd-templates/.github/workflows/CreateDocker.yml@feature/confirmation-ghactions
    with:
      ImageName: aafm/confirmation/nucleus-orl-be
      ECR_REPOSITORY: a207804/aafm-confirmation-nucleus-orl-be
    secrets:
      GIT_SVC_TOKEN: ${{ secrets.GIT_SVC_TOKEN }}
```

**Key design decisions:**

1. **Thin callers, fat templates** — service repos have 30-line workflow files; all logic lives in templates
2. **Explicit secret pass-through** — GitHub requires secrets to be passed explicitly to reusable workflows (security feature, not a bug)
3. **Pinned to branch ref** — `@feature/confirmation-ghactions` (not `@main`) — allows testing template changes without affecting all services
4. **Inputs are typed** — each template defines 30-100+ input parameters with defaults

---

### 5.4 .NET Microservice Pipeline (End-to-End)

**Interview Question: "Walk me through your .NET CI/CD pipeline"**

This covers 30+ .NET microservices including nucleus-be (4 services), forms-be, pricing-be, etc.

**Pipeline flow:**

```
Developer pushes to master
        │
        ▼
┌─────────────────────────────┐
│ 1. Build-Test-CollectMetrics│  ← Reusable workflow
│   • Restore NuGet (JFrog)   │
│   • Build solution          │
│   • Run unit tests          │
│   • SonarQube analysis      │
│   • Coverage: OpenCover XML │
│   Timeout: 150 minutes      │
└──────────┬──────────────────┘
           │ needs: Build-Test (sequential)
           ▼
┌─────────────────────────────┐
│ 2. Build-Docker × N         │  ← Parallel per service
│   (nucleus-be builds 4      │
│    Docker images in parallel)│
│   • Read version from JSON  │
│   • Docker build (multi-stage)
│   • Push to ECR + JFrog     │
│   • Update Helm values.yaml │
│     in confirmation-helm-charts
│   • Commit via GraphQL API  │
└──────────┬──────────────────┘
           │ ArgoCD detects commit
           ▼
┌─────────────────────────────┐
│ 3. ArgoCD Auto-Sync (CI)    │
│   • Pulls new image tag     │
│   • Argo Rollout canary     │
│   • 50% → pause 1m → 100%  │
└─────────────────────────────┘
```

**nucleus-be builds 4 services in parallel:**

| Service | ECR Repository | Purpose |
|---------|---------------|---------|
| nucleus-orl-be | `a207804/aafm-confirmation-nucleus-orl-be` | Orleans silo host |
| nucleus-gql-be | `a207804/aafm-confirmation-nucleus-gql-be` | GraphQL API server |
| nucleus-ldr-be | `a207804/aafm-confirmation-nucleus-ldr-be` | Data loader service |
| nucleus-rel-be | `a207804/aafm-confirmation-nucleus-rel-be` | Relationships service |

**Key technical details:**

**BlueMoon Versioning** (unique to .NET services):
```powershell
# Date-based version: 2025.03.10.42
$baseDate = [datetime]'01/14/2025'
$curDate = [datetime]::UtcNow
$version = "$versionPrefix.$env:GITHUB_RUN_NUMBER"
```

**NuGet Authentication** (JFrog as private NuGet feed):
```bash
# Dynamic credential injection using xmlstarlet
xmlstarlet ed -s "//packageSources" -t elem -n "add" \
  -i "//add[last()]" -t attr -n "key" -v "JFrogNuget" \
  -i "//add[last()]" -t attr -n "value" -v "https://tr1.jfrog.io/tr1/api/nuget/v3/nuget" \
  nuget.config
```

**Multi-stage Docker build:**
```dockerfile
# Stage 1: Build with SDK image (from JFrog, NOT Docker Hub)
FROM tr1-docker.jfrog.io/aafm/confirmation/dotnet-core-8-sdk:8.0.100-alpine3.18 AS build
COPY . .
RUN dotnet publish -c Release -o /app

# Stage 2: Runtime image (minimal)
FROM tr1-docker.jfrog.io/aafm/confirmation/dotnet-core-8:8.0.0-alpine3.18
COPY --from=build /app .
ENTRYPOINT ["dotnet", "Service.dll"]
```

**Hotfix mode** — automatic detection:
```bash
if [[ "$BRANCH_NAME" == hotfix/* ]]; then
  echo "HOTFIX MODE: Building image only, skipping CI/Demo deployment"
  # Push to ECR/JFrog only — no Helm update
  # Ops team manually promotes the image tag
fi
```

---

### 5.5 Python Microservice Pipeline

**Interview Question: "How does your Python CI/CD differ from .NET?"**

Our Python services (service-ops, k8s-ops-assistant, db-ops, harness, dynamo, outpost-storage) use a single reusable template: `audit-devops-portal-ci.yml`.

**Pipeline flow:**

```yaml
# k8s-ops-assistant/.github/workflows/ci.yml (thin caller)
jobs:
  get-default-ref:
    runs-on: ubuntu-latest
    outputs:
      ref: ${{ steps.get-ref.outputs.ref }}

  call-reusable-ci:
    needs: get-default-ref
    uses: tr/audit-cicd-templates/.github/workflows/audit-devops-portal-ci.yml@feature/confirmation-ghactions
    with:
      ref: ${{ needs.get-default-ref.outputs.ref }}
      ServiceName: audit-devops-assistant
      DockerfilePath: ./audit-devops-assistant/Dockerfile
      PublishImage: true
    secrets:
      GIT_SVC_TOKEN: ${{ secrets.GIT_SVC_TOKEN }}
```

**What the template does (audit-devops-portal-ci.yml):**

```
1. Dependency Review    ← GitHub native vulnerability check
       │
2. Build & Test
   ├── pip install -r requirements.txt
   ├── flake8 linting
   ├── pytest with coverage
   ├── pip-audit (SCA vulnerability scan)
   ├── TruffleHog (secret detection in code)
   ├── Bandit (SAST — Python security issues)
   └── Upload test reports as artifacts
       │
3. Docker Build & Push
   ├── Build from TR ECR base image (NOT Docker Hub)
   ├── Push to ECR: 833618288067.dkr.ecr.us-east-1.amazonaws.com
   ├── Tags: latest + semantic version
   └── Labels: git SHA + build number
       │
4. Helm Values Update
   ├── Checkout confirmation-helm-charts repo
   ├── Update image.tag in environments/ci/values.yaml
   ├── Commit via GraphQL API (bypasses branch protection)
   └── ArgoCD auto-syncs CI environment
```

**Weekly security audit** (separate workflow):
```yaml
# Runs every Monday at 2 AM UTC
on:
  schedule:
    - cron: '0 2 * * 1'
  workflow_dispatch:

jobs:
  security-audit:
    steps:
      - run: safety check -r requirements.txt          # Known CVEs
      - run: bandit -r audit_devops_assistant/ -ll      # Code security
      - run: semgrep --config=auto                      # Pattern scanning
      # On failure: creates GitHub issue with 'security' + 'urgent' labels
```

**Key difference from .NET:**

| Aspect | .NET Pipeline | Python Pipeline |
|--------|--------------|-----------------|
| Build tool | `dotnet build` / `dotnet publish` | `pip install` (no compilation) |
| Test tool | `dotnet test` + OpenCover | `pytest` + coverage.py |
| Code quality | SonarQube (external) | Bandit + flake8 (inline) |
| Package registry | JFrog NuGet feed | PyPI (public) + ECR for Docker |
| Docker base | JFrog SDK + runtime images | TR ECR Python 3.11-slim |
| Secret scanning | SonarQube detects some | TruffleHog (dedicated) |
| Versioning | BlueMoon (date-based) | Semantic versioning from JSON |

---

### 5.6 Angular Frontend Pipeline

**Interview Question: "How do you handle frontend deployments differently?"**

Frontend services (self-registration-fe, portal) have a different artifact flow — they publish to JFrog Artifactory, not ECR.

```
Developer pushes to master
        │
        ▼
┌─────────────────────────────┐
│ 1. build-and-test            │  ← Reusable workflow
│   • npm install              │
│   • ng build --prod          │
│   • ng test (Karma/Jest)     │
│   • SonarQube scan           │
│   • Exclusions: node_modules,│
│     *.spec.ts, *.module.ts   │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│ 2. publish                   │  ← Publish to JFrog
│   • Bundle app artifacts     │
│   • Push to tr1.jfrog.io     │
│   • Version: semantic + run# │
└──────────┬──────────────────┘
           │
           ▼
┌──────────┴──────────────────┐
│ 3a. deploy-ci    │ 3b. deploy-demo │  ← Parallel
│  Update CI Helm  │  Update Demo Helm│
│  values.yaml     │  values.yaml     │
└──────────────────┴─────────────────┘
```

**Frontend vs Backend Helm values difference:**

```yaml
# Backend service values.yaml — image tag
image:
  repository: 833618288067.dkr.ecr.us-east-1.amazonaws.com/a207804/service-name
  tag: "1.2.3"       # ← CI updates this

# Frontend service values.yaml — JFrog artifact URL
VERSION: "1.2.3"
JFROG_URL: "https://tr1.jfrog.io/artifactory/npm-local/aafm/confirmation/self-reg-fe/1.2.3"
```

---

### 5.7 Docker & ECR Integration

**Interview Question: "How do you handle Docker image builds and registry management?"**

**Multi-registry push pattern:**

```yaml
# From CreateDocker.yml — pushes to BOTH JFrog and ECR
- uses: docker/build-push-action@v6
  with:
    file: ${{ inputs.DockerfilePath }}
    build-args: |
      TR_ART_USER=${{ inputs.TR_ART_USER }}
      TR_ART_TOKEN=${{ secrets.TR_ART_TOKEN }}
    push: true
    tags: |
      # JFrog registry
      ${{ inputs.TR_ART_REGISTRY }}/${{ inputs.ImageName }}:latest
      ${{ inputs.TR_ART_REGISTRY }}/${{ inputs.ImageName }}:${{ env.Version }}
      # AWS ECR
      ${{ steps.login-ecr.outputs.registry }}/${{ inputs.ECR_REPOSITORY }}:${{ env.Version }}
    labels: |
      com.github.image.source.sha=${{ github.sha }}
      com.github.image.build.number=${{ github.run_number }}
```

**Why two registries?**

| Registry | Purpose | Who Pulls |
|----------|---------|-----------|
| **JFrog** (`tr1-docker.jfrog.io`) | Base images (SDK, runtime), artifact storage | Docker build stages, CI |
| **AWS ECR** (`833618288067.dkr.ecr`) | Production runtime images | EKS clusters via ArgoCD |

**Docker Hub is BANNED in CI** — hits 100 pull/6hr rate limit. We use TR ECR base images:
```dockerfile
# CORRECT — TR ECR base image
ARG BASE_IMAGE=833618288067.dkr.ecr.us-east-1.amazonaws.com/a207804/a207804-ue1-op-python:3.11-slim

# WRONG — Docker Hub (fails in CI)
# FROM python:3.11-slim
```

**Runner types for Docker builds:**

| Runner | Used For | Why |
|--------|----------|-----|
| `ubuntu-latest` | Python services | Standard GitHub-hosted |
| `windows-latest` | .NET Framework services | Windows containers |
| CodeBuild (`codebuild-a207804-*`) | Large Docker builds | Custom compute, ECR proximity |

---

### 5.8 JFrog Artifactory Integration

**Interview Question: "How do you integrate JFrog Artifactory with your CI/CD?"**

JFrog serves as the **universal artifact manager** — Docker images, NuGet packages, NPM bundles, and database migration ZIPs all flow through it.

**Four integration patterns:**

**1. Docker Base Images (Build-time dependency):**
```dockerfile
FROM tr1-docker.jfrog.io/aafm/confirmation/dotnet-core-8-sdk:8.0.100-alpine3.18 AS build
```

**2. NuGet Package Feed (.NET build dependency):**
```bash
# JFrog serves as private NuGet feed
dotnet restore --source https://tr1.jfrog.io/tr1/api/nuget/v3/nuget
```

**3. NPM Registry (Frontend build dependency):**
```bash
npm config set registry https://tr1.jfrog.io/tr1/api/npm/npm/
```

**4. Database Migration Uploads (Deployment artifact):**
```bash
# Bundle migrations and upload to JFrog
cd migrations/ && zip -r db_migration.zip .
jfrog rt u db_migration.zip libs-release-local/ng-devops/aafm/confirmation/$SERVICE/$VERSION/
```

**Authentication pattern:**
```yaml
# JFrog CLI setup in workflow
- run: |
    jfrog config add my-server \
      --url=https://tr1.jfrog.io \
      --user="${{ inputs.TR_ART_USER }}" \
      --password="${{ secrets.TR_ART_TOKEN }}"

# Docker login for JFrog registry
- run: |
    echo "${{ secrets.TR_ART_TOKEN }}" | docker login tr1-docker.jfrog.io \
      --username "${{ inputs.TR_ART_USER }}" --password-stdin
```

**Interview Answer:**

> "JFrog Artifactory is our universal artifact manager. .NET services pull NuGet packages from JFrog during build, Docker build stages use JFrog-hosted base images, frontend builds publish NPM bundles to JFrog, and database migration ZIPs get uploaded for deployment tracking. Authentication uses a service account (`svc-ng-devops`) with token passed as a GitHub secret — the token is masked in logs automatically."

---

### 5.9 GraphQL Commit API (Branch Protection Bypass)

**Interview Question: "How do you automate commits to a branch-protected repo?"**

This is one of the most interesting patterns in our CI/CD — and a great interview talking point.

**The problem:**
- `confirmation-helm-charts` repo has branch protection on `main` (require PR + approval)
- CI/CD needs to update `image.tag` in `values.yaml` after every Docker build
- Standard REST API respects branch protection — commit fails
- Creating a PR for every image tag update would mean 50+ PRs per day

**The solution — GitHub GraphQL API:**

```yaml
# In CreateDocker.yml — after Docker push
- uses: tr/prodsec_github_actions/push-commit-using-graphql-api@main
  with:
    github-repository: 'tr/audit-devops-confirmation-helm-charts'
    commit-message: "Update image tag to ${{ env.ServiceSemanticVersion }}"
    github-token: "${{ secrets.GIT_SVC_TOKEN }}"
    file-patterns: ${{ inputs.HelmRepo }}
    create-pull-request: 'false'
```

**Why GraphQL works where REST doesn't:**
- GitHub's `createCommitOnBranch` GraphQL mutation can bypass branch protection when the token has appropriate permissions
- Does NOT require `admin:repo_hook` permission (our PAT limitation)
- The service account token (`GIT_SVC_TOKEN`) is scoped for this specific operation

**Dual-environment update pattern:**
```
Docker build completes
        │
        ├── Step 1: Checkout helm-charts repo
        ├── Step 2: Update CI values.yaml (image.tag = new version)
        ├── Step 3: Commit to main via GraphQL API
        ├── Step 4: Fresh checkout (get latest main with Step 3's commit)
        ├── Step 5: Update Demo values.yaml (image.tag = new version)
        └── Step 6: Commit to main via GraphQL API

ArgoCD auto-syncs both CI and Demo environments
```

**Interview Answer:**

> "Our Helm chart repo has branch protection, but CI/CD needs to update image tags 50+ times a day. We use GitHub's GraphQL `createCommitOnBranch` mutation which can bypass branch protection with appropriate token permissions. This avoids creating a PR for every image tag update while still maintaining protection for manual changes. The workflow commits CI and Demo values.yaml updates in sequence — two separate commits so each environment's ArgoCD Application tracks its own change."

---

### 5.10 Security Scanning Pipeline

**Interview Question: "How do you enforce security in your CI/CD pipelines?"**

We run **5 layers of security scanning** across our pipelines:

| Layer | Tool | What It Catches | When It Runs |
|-------|------|-----------------|--------------|
| **1. Dependency SCA** | pip-audit / safety | Known CVEs in dependencies | Every build + weekly |
| **2. Secret Detection** | TruffleHog | Hardcoded tokens, passwords, API keys | Every build |
| **3. SAST** | Bandit (Python) / SonarQube (.NET) | Code security issues (injection, crypto) | Every build |
| **4. Code Quality** | flake8 / SonarQube | Bugs, code smells, complexity | Every build |
| **5. Dependency Review** | GitHub DependencyBot | New vulnerable dependencies in PRs | Every PR |

**Weekly security audit** (Python services):
```yaml
on:
  schedule:
    - cron: '0 2 * * 1'  # Every Monday 2 AM UTC

steps:
  - run: safety check -r requirements.txt --json > safety-report.json
  - run: bandit -r audit_devops_assistant/ -ll -f json -o bandit-report.json
  - run: semgrep --config=auto --json > semgrep-report.json

  # On failure: auto-create GitHub issue
  - if: failure()
    uses: actions/github-script@v7
    with:
      script: |
        github.rest.issues.create({
          title: 'Security Audit Failed',
          labels: ['security', 'urgent']
        })
```

**Bandit false positive management** (interview-worthy):
```python
# These get flagged but are NOT security issues:
delay = random.uniform(1.0, 3.0)       # nosec B311 — timing jitter, not crypto
size = pvc.spec.resources.requests.get("storage")  # nosec B113 — K8s dict, not HTTP
CIAM_TOKEN_URL = "https://auth.thomsonreuters.com"  # nosec B105 — URL constant, not password
```

> "We manage Bandit false positives with inline `# nosec` comments and a documented table in our project docs. Each suppression includes the rule ID and the reason — so any reviewer can verify it's genuinely safe. We never suppress HIGH severity without explicit approval."

**continue-on-error strategy:**

> "Security scans use `continue-on-error: true` for SCA tools — we don't want a new CVE in a transitive dependency to block a hotfix deployment. Results are uploaded as artifacts and reviewed async. But Bandit (SAST) and unit tests DO fail the build — those are code issues the developer can fix immediately."

---

### 5.11 Environment Promotion (QA Drift Detection)

**Interview Question: "How do you promote code across environments?"**

Our promotion flow:

```
CI (auto on merge) → Demo (auto on merge) → QA (manual promotion) → Preprod → Prod
```

**CI/Demo are automatic** — the Docker build workflow updates Helm values and ArgoCD auto-syncs.

**QA promotion uses drift detection:**

```yaml
# confirmation-deploy-qa.yml — Intelligent promotion
steps:
  # 1. Call drift detection API
  - run: |
      DRIFT=$(curl -s "https://ci-external.api.tr.confirmation.com/api/v1/deployments/checkdrift?env=demo,qa")
      # Returns JSON: [{service_name, source_version, target_version, is_different}]

  # 2. Process drift — only update services that actually changed
  - run: |
      echo "$DRIFT" | jq -r '.[] | select(.is_different == true) | .service_name' | while read service; do
        VERSION=$(echo "$DRIFT" | jq -r ".[] | select(.service_name == \"$service\") | .source_version")
        # Backend: update image.tag
        sed -i "s|tag:.*|tag: \"$VERSION\"|" environments/qa/$service/values.yaml
        # Frontend: update VERSION + JFROG_URL
      done

  # 3. Commit all changes via GraphQL API with multi-line message
  - uses: tr/prodsec_github_actions/push-commit-using-graphql-api@main
    with:
      commit-message: |
        Promote to QA:
        - nucleus-orl-be: 1.2.3 → 1.2.4
        - self-reg-fe: 2.0.1 → 2.0.2
```

**What is "drift"?**
- Drift = version mismatch between environments
- Our DynamoDB deployment catalog API tracks what version is deployed where
- The drift API compares Demo vs QA and returns only services that differ
- This prevents promoting unchanged services (which would trigger unnecessary rollouts)

**Interview Answer:**

> "CI and Demo deploy automatically on merge — the CI workflow updates Helm values.yaml and ArgoCD auto-syncs. For QA promotion, we have a drift detection system. Our DynamoDB deployment catalog tracks every service version per environment. The promotion workflow queries our drift API to find which services actually changed between Demo and QA, updates only those services in the Helm repo, and commits with a multi-line message listing every promoted service and its version change. This prevents unnecessary rollouts and gives full traceability."

---

### 5.12 Full CI/CD Flow (End-to-End)

**Interview Question: "Walk me through the complete journey from code commit to production"**

```
┌──────────────────────────────────────────────────────────────────┐
│                    DEVELOPER WORKFLOW                              │
├──────────────────────────────────────────────────────────────────┤
│  1. Developer creates feature branch                              │
│  2. Opens PR → triggers PR validation workflow                    │
│     ├── Build + unit tests                                        │
│     ├── SonarQube quality gate                                    │
│     └── Dependency review (GitHub native)                         │
│  3. PR approved + merged to master/main                           │
├──────────────────────────────────────────────────────────────────┤
│                    CI PIPELINE (automatic)                         │
├──────────────────────────────────────────────────────────────────┤
│  4. Build workflow triggers on push to main                       │
│     ├── Build & test (reusable template)                          │
│     ├── Security scans (Bandit/TruffleHog/pip-audit)              │
│     ├── Docker build (TR ECR base image)                          │
│     ├── Push to ECR + JFrog (dual registry)                       │
│     └── DB migrations → JFrog (if applicable)                     │
│                                                                   │
│  5. Helm values update (same workflow)                            │
│     ├── Checkout confirmation-helm-charts repo                    │
│     ├── Update environments/ci/service/values.yaml                │
│     ├── Commit via GraphQL API (bypass branch protection)         │
│     ├── Fresh checkout (get new commit)                           │
│     ├── Update environments/demo/service/values.yaml              │
│     └── Commit via GraphQL API                                    │
├──────────────────────────────────────────────────────────────────┤
│                    CD — GITOPS (ArgoCD)                            │
├──────────────────────────────────────────────────────────────────┤
│  6. ArgoCD detects Helm repo change                               │
│     ├── CI: auto-sync → deploys immediately                       │
│     ├── Demo: auto-sync → deploys immediately                     │
│     └── Argo Rollout: canary 50% → pause 1m → 100%               │
│                                                                   │
│  7. QA promotion (manual trigger)                                 │
│     ├── Drift detection API (Demo vs QA)                          │
│     ├── Update only changed services                              │
│     ├── Commit via GraphQL API                                    │
│     └── ArgoCD manual sync → Argo Rollout                         │
│                                                                   │
│  8. Preprod → Prod (manual, separate Helm repo)                   │
│     ├── itops-helm-charts (not confirmation-helm-charts)          │
│     ├── PR required (branch protection enforced)                  │
│     ├── ArgoCD manual sync only                                   │
│     └── Argo Rollout canary with manual promotion                 │
└──────────────────────────────────────────────────────────────────┘
```

**Key architecture decisions:**

| Decision | Why |
|----------|-----|
| Separate Helm repos for non-prod vs prod | Different access controls, different ArgoCD instances |
| Auto-sync on CI/Demo, manual on QA+ | Fast feedback in lower envs, control in higher |
| GraphQL API for Helm commits | Branch protection + 50+ daily updates = can't use PRs |
| Dual registry (ECR + JFrog) | ECR for runtime (EKS pulls), JFrog for build artifacts |
| Reusable templates in central repo | One change updates all 40+ service pipelines |
| Drift detection for QA promotion | Prevents unnecessary rollouts, full traceability |

---

### 5.13 Caching & Performance

**Interview Question: "How do you optimize CI/CD pipeline performance?"**

| Technique | Where Used | Impact |
|-----------|-----------|--------|
| **pip cache** | Python workflows | `~/.cache/pip` keyed on `requirements.txt` hash |
| **NuGet cache** | .NET workflows | Restored packages from previous builds |
| **Rush.js cache** | Frontend monorepo | 8 composite actions for incremental builds |
| **SonarQube cache** | All workflows | `~/.sonar/cache` reused across runs |
| **Docker layer cache** | Docker builds | Multi-stage builds reuse unchanged layers |
| **Concurrency control** | All workflows | `cancel-in-progress: true` kills superseded runs |

```yaml
# Concurrency — only one build per branch at a time
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true   # New push cancels in-progress build

# Pip caching
- uses: actions/cache@v4
  with:
    path: ~/.cache/pip
    key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt') }}
    restore-keys: |
      ${{ runner.os }}-pip-
```

---

### 5.14 Interview Questions — Scenario-Based

**Q: "A developer says their PR build is failing with 'NuGet package not found'. What do you check?"**

> "1. **JFrog health**: Check if `tr1.jfrog.io` is reachable — JFrog outages are rare but happen
> 2. **Package version**: The package might have been unpublished. Check JFrog UI for the specific version
> 3. **nuget.config**: Verify the workflow is injecting JFrog credentials correctly — xmlstarlet could fail silently
> 4. **Cache**: Clear NuGet cache — a corrupted cache entry can cause phantom failures
> 5. **Token expiry**: The `TR_ART_TOKEN` secret might have expired — check GitHub repo settings"

**Q: "Your CI/CD pipeline is taking 45 minutes. How do you speed it up?"**

> "1. **Identify the bottleneck**: Check GitHub Actions run timing — is it build, test, Docker, or scan?
> 2. **Parallelize**: If build + test runs sequentially before 4 Docker builds, make Docker builds parallel (we do this with `needs:` dependencies)
> 3. **Caching**: Add NuGet/pip/node_modules caching — biggest win for repeat builds
> 4. **Docker layer caching**: Use `cache-from` and `cache-to` in build-push-action
> 5. **Test parallelism**: Split tests across matrix runners: `strategy: matrix: shard: [1, 2, 3]`
> 6. **Runner sizing**: Move to larger runners — CodeBuild runners with 8+ vCPU for Docker builds
> 7. **Skip unnecessary work**: Use path filters (`on: push: paths: ['src/**']`) to skip CI when only docs change"

**Q: "A security scan found a critical CVE in a transitive dependency. How do you handle it?"**

> "1. **Assess impact**: Is the vulnerable function actually called in our code? pip-audit tells you the package, not the usage
> 2. **Check for fix**: Is there a patched version? `pip install --upgrade <package>` and test
> 3. **If no fix available**: Can we pin to a non-vulnerable version? Add constraint in requirements.txt
> 4. **If no fix at all**: Document the risk, add `safety` ignore with justification, open a tracking issue
> 5. **Prevent future**: Add `safety check` to PR validation so new vulnerable deps are caught before merge"

**Q: "You need to add a new microservice to your CI/CD. Walk me through the steps."**

> "1. **Create the repo** with standard structure (Dockerfile, requirements.txt/csproj, tests)
> 2. **Add `.github/workflows/ci.yml`** — 30-line thin caller that references our central template
> 3. **Add GitHub secrets**: `GIT_SVC_TOKEN`, `TR_ART_TOKEN`, `SONAR_TOKEN`
> 4. **Create ECR repository**: Via AWS CLI or CDK — name follows `a207804/service-name` convention
> 5. **Add Helm chart**: Copy from existing service in confirmation-helm-charts, update values
> 6. **Create ArgoCD Application**: Either manually or via ApplicationSet if it matches a pattern
> 7. **Add to drift detection**: Register in DynamoDB deployment catalog
> 8. **Test**: Push to main, verify CI→Docker→ECR→Helm→ArgoCD→Pod flow end-to-end"

**Q: "How do you handle secrets in GitHub Actions?"**

> "1. **GitHub Secrets**: Org-level and repo-level encrypted secrets — never in code
> 2. **Explicit pass-through**: Reusable workflows require `secrets:` block — no implicit inheritance
> 3. **Masking**: `::add-mask::` in workflow logs — GitHub auto-masks secret values
> 4. **Rotation**: Service account tokens rotated quarterly; CIAM M2M tokens auto-refresh
> 5. **Least privilege**: Each workflow only receives secrets it needs — no wildcard `secrets: inherit`
> 6. **Never in Dockerfiles**: Build args for credentials are used in intermediate layers only — multi-stage build discards them"

**Q: "Your GraphQL commit to the Helm repo succeeded but ArgoCD isn't deploying. What happened?"**

> "1. **Check ArgoCD sync status**: Is the Application 'OutOfSync'? If auto-sync is disabled (QA/Prod), it's waiting for manual sync
> 2. **Check the commit**: Did the GraphQL API actually update the correct file? Verify in the Helm repo's git log
> 3. **Values.yaml format**: Did sed/yq corrupt the YAML? Helm template render would fail silently in ArgoCD
> 4. **ArgoCD webhook**: Is the GitHub webhook configured to notify ArgoCD? Without it, ArgoCD polls every 3 minutes
> 5. **ArgoCD health**: Check ArgoCD Application controller pods — if they're OOMKilled, sync is delayed
> 6. **Diff check**: ArgoCD might see 'Synced' if the image tag changed but the actual manifest didn't change (e.g., tag already the same)"

**Q: "How do you rollback a bad deployment that got through CI/CD?"**

> "Depends on how far it got:
> 1. **Still in canary (50%)**: Argo Rollout is paused — just abort: `kubectl argo rollouts abort <name>`. Automatic rollback.
> 2. **Fully deployed to CI/Demo**: Git revert the Helm values.yaml commit. ArgoCD auto-syncs the revert → pods roll back to previous image.
> 3. **In QA**: Manual ArgoCD sync needed after the revert.
> 4. **In Prod**: Revert in itops-helm-charts repo, open PR (required), get approval, manual ArgoCD sync. Argo Rollout handles the actual rollback with canary.
> 5. **Emergency**: `kubectl argo rollouts undo <name>` skips Git entirely — but creates drift that ArgoCD will reconcile on next sync."

**Q: "How would you migrate from Jenkins to GitHub Actions?"**

> "We actually did this migration for our platform:
> 1. **Audit existing Jenkins jobs**: Map each job to a GitHub Actions equivalent
> 2. **Start with PR validation**: Lowest risk — if it fails, doesn't affect deployments
> 3. **Build the template library first**: Don't migrate 40 repos with copy-paste — create reusable templates
> 4. **Run in parallel**: Keep Jenkins active while GitHub Actions runs alongside. Compare outputs.
> 5. **Migrate one service end-to-end**: Pick a low-risk service, do full CI/CD in GitHub Actions
> 6. **Expand incrementally**: Once proven, migrate remaining services using the templates
> 7. **Key challenge**: Jenkins has stateful agents with pre-installed tools. GitHub Actions runners are ephemeral — every dependency must be in the workflow or Docker image."

---
