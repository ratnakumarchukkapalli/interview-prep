# Section 6: AWS CDK (IaC)

### 6.1 What is AWS CDK?

**AWS Cloud Development Kit (CDK)** is an Infrastructure as Code framework that lets you define AWS resources using real programming languages (Python, TypeScript, Java, Go) instead of YAML/JSON (CloudFormation) or HCL (Terraform).

**Why CDK over Terraform or raw CloudFormation?**

| Aspect | CloudFormation (YAML) | Terraform (HCL) | CDK (Python) |
|--------|----------------------|------------------|---------------|
| **Language** | YAML/JSON (declarative) | HCL (declarative) | Python/TS (imperative) |
| **Loops/Conditions** | Limited (`Fn::If`, `Fn::ForEach`) | `for_each`, `count` | Native Python loops, if/else |
| **Reusability** | Nested stacks (clunky) | Modules | Classes, inheritance, composition |
| **Testing** | None built-in | `terraform validate` | pytest with assertions on synth output |
| **Type safety** | None | Partial (HCL types) | Full IDE autocomplete + type hints |
| **State** | Managed by AWS (CloudFormation) | `.tfstate` file (you manage) | Managed by AWS (generates CloudFormation) |
| **Abstraction** | Low (every resource explicit) | Medium | High (L2/L3 constructs hide boilerplate) |

**CDK compiles to CloudFormation:**
```
Python code → cdk synth → CloudFormation template (JSON) → cdk deploy → AWS creates resources
```

You write Python, CDK generates a CloudFormation template, and CloudFormation provisions the actual resources. If something fails, CloudFormation rolls back automatically.

---

### 6.2 CDK Core Concepts

**Three levels of constructs:**

| Level | What It Is | Example | Effort |
|-------|-----------|---------|--------|
| **L1 (Cfn)** | 1:1 mapping to CloudFormation resource | `CfnBucket(self, "b", bucket_name="my-bucket")` | You set every property |
| **L2 (Default)** | Opinionated wrapper with sensible defaults | `Bucket(self, "b", versioned=True)` | Handles IAM, encryption, etc. |
| **L3 (Pattern)** | Multi-resource pattern | `ApplicationLoadBalancedFargateService(...)` | Creates ALB + ECS + target group |

**Key CDK terms:**

| Term | What It Is | Real Example |
|------|-----------|--------------|
| **App** | The root of your CDK project | `app = cdk.App()` |
| **Stack** | A unit of deployment (= 1 CloudFormation stack) | `KMSStack(app, "a207804-cng-ci-us-east-1-KMSStack")` |
| **Construct** | A reusable component (class) | `IAMConstruct`, `S3Construct` |
| **Context** | Runtime flags passed via CLI | `cdk deploy -c deploy_ec2=true` |
| **Synthesize** | Generate CloudFormation from Python | `cdk synth` |
| **Bootstrap** | One-time setup (S3 bucket + IAM for CDK) | `cdk bootstrap aws://ACCOUNT/REGION` |
| **Environment** | Target AWS account + region | `Environment(account="307097860667", region="us-east-1")` |

**CDK project structure:**
```
my-cdk-project/
├── app.py                  # Entry point — instantiates stacks
├── cdk.json                # CDK config (app command, context flags)
├── requirements.txt        # aws-cdk-lib, constructs
├── config/
│   └── global.yaml         # Environment-specific config
├── stacks/
│   └── my_stack.py         # Stack definitions (AWS resources)
├── TRconstructs/           # Reusable construct classes
│   ├── iam_construct.py
│   ├── s3_construct.py
│   └── ec2_construct.py
└── tests/
    └── test_stack.py       # Unit tests on synth output
```

---

### 6.3 Confirmation Outpost IaC — My CDK Project

**Repo**: `confirmation-devops-outpost-IaC` — 26 PRs merged, all my commits.

**The Problem:**
Our Confirmation platform runs on AWS EKS Outposts. Every service needs AWS resources provisioned before it can deploy — KMS keys for encryption, Secrets Manager entries for credentials, ECR repositories for Docker images, IAM roles for access control. Without IaC, creating these for 40+ services across 8 environments would be manual, error-prone, and inconsistent.

**The Solution:**
I built a CDK project with 11 stacks and 12 reusable constructs that provisions all foundational AWS resources for the Confirmation platform. One `cdk deploy` command creates everything a service needs — encryption keys, secrets, image repositories, IAM policies — all config-driven from YAML files.

---

### 6.4 The 11 Stacks I Built

```python
# app.py — Entry point, context-driven
app = cdk.App()
context_app = app.node.try_get_context('app')    # 'cng' (confirmation nextgen)
environment = app.node.try_get_context('environment')  # ci, demo, qa, prod
region = app.node.try_get_context('region')       # us-east-1

# Deploy: cdk deploy -c app=cng -c environment=ci -c region=us-east-1
```

| Stack | What It Creates | Status | Why It Matters |
|-------|----------------|--------|---------------|
| **KMSStack** | Customer-managed KMS keys (app, db, ecr, jfrog) with rotation enabled | Active | Every secret, ECR repo, and RDS instance encrypts with these keys |
| **SecretManagerStack** | Secrets for 25+ services (app secrets + DB creds per service) | Active | ExternalSecrets Operator pulls these into K8s Secrets |
| **IAMPolicyStack** | Managed IAM policies (KMS admin) | Active | Least-privilege access to encryption keys |
| **IAMRoleStack** | IAM roles with policies attached | Active | Service roles for EKS, CodeBuild, etc. |
| **ECRStack** | 21 ECR repositories with KMS encryption + scan-on-push | Available | Every Docker image for every service |
| **OutpostS3Stack** | S3 on Outpost racks with access points | Available | Data residency — storage on Outpost, not cloud |
| **S3BucketStack** | Standard S3 buckets | Available | Artifacts, logs, backups |
| **EC2Stack** | EC2 instances on Outpost with KMS-encrypted EBS | Available | Compute on Outpost rack |
| **RDSStack** | PostgreSQL on Outpost with Secrets Manager password generation | Available | Database with auto-generated encrypted credentials |
| **CloudfrontStack** | CloudFront + S3 origin with OAC (Origin Access Control) | Available | CDN for frontend apps |
| **CertificateManagerStack** | ACM certificates with DNS validation | Available | TLS certs for ALB/CloudFront |

**Stack dependencies** (order matters):
```
KMSStack (deployed first — encryption keys)
    ↓
SecretManagerStack (encrypts secrets with KMS keys)

IAMPolicyStack (policies first)
    ↓
IAMRoleStack (attaches policies to roles)
```

```python
# app.py — explicit dependency declaration
kms_stack = KMSStack(app, f"a{asset_id}-{app_name}-{environment}-{region}-KMSStack")
secret_manager_stack = SecretManagerStack(app, f"a{asset_id}-{app_name}-{environment}-{region}-SecretManagerStack")
secret_manager_stack.add_dependency(kms_stack)  # KMS must exist before secrets
```

---

### 6.5 How It Works — Real Examples

**KMS Stack** — creates 4 encryption keys per environment:
```python
# KMSStack reads from YAML config
# Config: kms: [{key_name: "app"}, {key_name: "db"}, {key_name: "ecr"}, {key_name: "jfrog"}]
for key_config in config['kms']:
    KMSConstruct(self, key_config['key_name'],
        alias=f"a{asset_id}-cn-aafm-confirmation-{key_config['key_name']}-{environment}",
        enable_key_rotation=True,
        pending_window=Duration.days(7),
    )
```

**Secrets Manager Stack** — creates app + DB secrets for each of 25 services:
```python
# Config: secrets_manager: [{service: "pricing-be", types: ["app", "db"]}, ...]
for service_config in config['secrets_manager']:
    for secret_type in service_config['types']:
        SecretManagerConstruct(self, f"{service}-{secret_type}",
            secret_name=f"a{asset_id}-cn-aafm-confirmation-{service}-{environment}-{secret_type}",
            kms_key_arn=global_config.get_config()['kms_key_arns'][secret_type],
        )
# Result: 50+ secrets per environment, each encrypted with service-specific KMS key
```

**ECR Stack** — 21 repositories for all platform services:
```python
# Config: ecr: [{name: "forms-be"}, {name: "pricing-be"}, {name: "nucleus-gql-be"}, ...]
for repo_config in config['ecr']:
    ECRConstruct(self, repo_config['name'],
        repository_name=f"a{asset_id}/aafm-confirmation-{repo_config['name']}",
        encryption_key=kms_key,
        image_scan_on_push=True,
    )
```

**The 12 reusable constructs** (each wraps a CDK L2 construct with TR standards):

| Construct | What It Wraps | TR Standard Applied |
|-----------|--------------|---------------------|
| `KMSConstruct` | `aws_kms.Key` | Rotation enabled, 7-day deletion, TagFactory tags |
| `SecretManagerConstruct` | `aws_secretsmanager.Secret` | KMS encryption, TagFactory tags |
| `ECRConstruct` | `aws_ecr.Repository` | KMS encryption, scan-on-push |
| `IAMPolicyConstruct` | `aws_iam.ManagedPolicy` | Policy statements from YAML config |
| `IAMRoleConstruct` | `aws_iam.Role` | AccountRootPrincipal, managed policies |
| `OutpostS3Construct` | `aws_s3outposts.CfnBucket` | Access points, per-bucket CMK |
| `S3BucketConstruct` | `aws_s3.Bucket` | Block public access, encryption |
| `EC2Construct` | `aws_ec2.CfnInstance` | KMS-encrypted EBS, Outpost subnet |
| `RDSConstruct` | RDS PostgreSQL | Secrets Manager password gen, customer KMS |
| `CloudfrontConstruct` | CloudFront distribution | S3 OAC (no legacy OAI), SigV4, logging |
| `CertificateManagerConstruct` | `aws_certificatemanager.Certificate` | DNS validation |
| `TagFactory` | Static tag factory | TR mandatory tags applied to every resource |

**TagFactory** ensures every resource gets tagged consistently:
```python
# TRconstructs/common/TagFactory.py
Tags.of(resource).add("tr:application-asset-insight-id", "207804")
Tags.of(resource).add("tr:bu", "tax")
Tags.of(resource).add("tr:bu-segment", "audit")
Tags.of(resource).add("tr:environment-type", environment.upper())
Tags.of(resource).add("tr:product", "confirmation-nextgen")
Tags.of(resource).add("tr:resource-owner", "audit-devops@thomsonreuters.com")
Tags.of(resource).add("tr:provider", "outposts")
```

---

### 6.6 Environment Configuration (YAML-Driven)

**The same CDK code deploys to all environments** — only the YAML config changes:

```bash
# Deploy to CI
cdk deploy -c app=cng -c environment=ci -c region=us-east-1

# Deploy to Demo
cdk deploy -c app=cng -c environment=demo -c region=us-east-1

# Deploy to Prod
cdk deploy -c app=cng -c environment=prod -c region=us-east-1
```

**Config file hierarchy** (later overrides earlier):
```
environments/
├── global/
│   └── global.yaml                         # Account IDs, asset_id
├── cng/
│   └── us-east-1/
│       ├── default.yaml                    # Region, service list
│       ├── cng_us-east-1_ci.yaml          # CI: 21 ECR repos, 25 services, 4 KMS keys
│       └── cng_us-east-1_demo.yaml        # Demo: slightly different service list
```

**CI config example** (`cng_us-east-1_ci.yaml`):
```yaml
kms:
  - key_name: "app"      # Encrypts app secrets
  - key_name: "db"       # Encrypts DB credentials
  - key_name: "ecr"      # Encrypts Docker images
  - key_name: "jfrog"    # Encrypts JFrog tokens

ecr:
  - name: "forms-be"
  - name: "pricing-be"
  - name: "nucleus-gql-be"
  - name: "nucleus-orl-be"
  - name: "selfreg-be"
  # ... 21 repos total

secrets_manager:
  - service: "pricing-be"
    types: ["app", "db"]
  - service: "forms-be"
    types: ["app", "db"]
  - service: "jfrog"
    types: ["jfrog"]
  # ... 25 services total
```

**Account routing:**
```python
preprod_environments = ['ci', 'demo', 'qa']
prod_environments = ['prod', 'prod-backup', 'dr', 'dr-backup']

if environment in preprod_environments:
    common_env = cdk.Environment(account=preprod_account, region=region)
elif environment in prod_environments:
    common_env = cdk.Environment(account=prod_account, region=region)
```

**GlobalConfig singleton** — inter-stack communication:
```python
# KMSStack stores KMS key ARNs
global_config = GlobalConfig()
global_config.append_config({"kms_key_arns": {"app": key.key_arn, "db": db_key.key_arn}})

# SecretManagerStack retrieves them
kms_arns = global_config.get_config()["kms_key_arns"]
# Uses the correct KMS key per secret type
```

---

### 6.7 CDK Key Patterns (Interview Gold)

**Pattern 1: Config-driven stacks (single source of truth)**
```python
# All resources defined in YAML — stacks are templates that loop over config
for service in config['secrets_manager']:
    SecretManagerConstruct(self, service['service'], ...)

# Add a new service = add one YAML entry. No code changes needed.
```

**Pattern 2: Cross-stack dependencies via GlobalConfig**
```python
# KMSStack writes key ARNs → SecretManagerStack reads them
# This avoids CfnOutput/ImportValue complexity for simple data sharing
global_config.append_config({"kms_key_arns": {key_name: key.key_arn}})
```

**Pattern 3: TR mandatory tagging via TagFactory**
```python
# Every construct calls TagFactory — impossible to forget tags
class KMSConstruct(Construct):
    def __init__(self, scope, id, **kwargs):
        key = kms.Key(self, "Key", ...)
        TagFactory.apply_common_tags(key, config)   # TR tags automatically
        TagFactory.apply_kms_tags(key, config)       # KMS-specific tags
```

**Pattern 4: Environment multiplexing**
```bash
# Same code, different config → different CloudFormation stacks per environment
cdk deploy -c app=cng -c environment=ci      # → a207804-cng-ci-us-east-1-KMSStack
cdk deploy -c app=cng -c environment=demo    # → a207804-cng-demo-us-east-1-KMSStack
cdk deploy -c app=cng -c environment=prod    # → a207804-cng-prod-us-east-1-KMSStack
```

**Pattern 5: Construct abstraction — enforce standards**
```python
# Raw CDK — developer might forget encryption or public access block
bucket = s3.Bucket(self, "Bucket")  # No encryption, publicly accessible!

# Our S3Construct — encryption + block public is built-in
S3BucketConstruct(self, "Bucket", bucket_name="...", config=config)
# Always encrypted, always private, always tagged
```

---

### 6.8 CDK vs Terraform — Interview Comparison

This is a **guaranteed** interview question: "Why CDK over Terraform?"

| Dimension | CDK (what we use) | Terraform |
|-----------|-------------------|-----------|
| **State management** | AWS-managed (CloudFormation) | You manage `.tfstate` (S3 + DynamoDB locking) |
| **Rollback** | Automatic (CloudFormation rolls back on failure) | Manual (`terraform destroy` or fix forward) |
| **Drift detection** | CloudFormation drift detection | `terraform plan` shows drift |
| **Multi-cloud** | AWS only | AWS, Azure, GCP, etc. |
| **Language** | Python, TypeScript, Java, Go | HCL (domain-specific) |
| **Testing** | pytest on synth output (real assertions) | `terraform validate` + `terratest` (Go) |
| **Learning curve** | Know Python → easy | Must learn HCL |
| **Community** | Growing | Massive (more modules/providers) |
| **Import** | `cdk import` (newer) | `terraform import` (mature) |

**Interview Answer:**

> "We chose CDK because our team is Python-first and we're AWS-only. The biggest advantage is testing — we write pytest assertions against the synthesized CloudFormation template. If someone removes encryption from an S3 bucket, the test fails before it ever hits AWS. We also use CDK Nag which runs AWS Solutions security checks at synth time. The trade-off is CDK is AWS-only, so if you need multi-cloud, Terraform is the right choice."

---

### 6.9 CDK Lifecycle — Interview Must-Know

```bash
# 1. Bootstrap (one-time per account/region)
cdk bootstrap aws://833618288067/us-east-1
# Creates: S3 bucket for assets, IAM roles for deployment

# 2. Synthesize (generate CloudFormation)
cdk synth -c app=cng -c environment=ci -c region=us-east-1
# Output: cdk.out/a207804-cng-ci-us-east-1-KMSStack.template.json

# 3. Diff (preview changes)
cdk diff -c app=cng -c environment=ci -c region=us-east-1
# Shows: resources to add/modify/delete (like terraform plan)

# 4. Deploy
cdk deploy -c app=cng -c environment=ci -c region=us-east-1
# Creates/updates CloudFormation stacks → provisions AWS resources

# 5. Destroy (tear down)
cdk destroy -c app=cng -c environment=ci -c region=us-east-1
# Deletes CloudFormation stacks → removes AWS resources
```

**Interview Question: "What happens if `cdk deploy` fails halfway?"**

> "CDK generates CloudFormation, so CloudFormation handles the failure. If a resource creation fails, CloudFormation **automatically rolls back** all resources created in that deployment. The stack returns to its previous state. This is a major advantage over Terraform where a partial failure can leave you in a broken state that requires manual cleanup."

---

### 6.10 Interview Questions — Scenario-Based

**Q: "You need to provision the same infrastructure in 4 environments (CI, Demo, QA, Prod). How do you handle it with CDK?"**

> "Config-driven stacks. I have a YAML config file per environment with values like instance type, VPC ID, subnet, tags. The CDK stack reads the config and uses those values. The same Python code deploys to all environments — only the config changes.
>
> ```python
> # app.py
> for env_name in ['ci', 'demo', 'qa', 'prod']:
>     config = load_config(env_name)
>     MyStack(app, f'infra-{env_name}', config=config, env=aws_env)
> ```
>
> This is better than copy-pasting stacks or using CloudFormation parameters because you get full Python validation at synth time."

**Q: "How do you test CDK code?"**

> "Three levels:
> 1. **Snapshot tests**: `cdk synth` output compared to a baseline — catches unintended changes
> 2. **Fine-grained assertions**: pytest checks specific resource properties exist
>    ```python
>    template.has_resource_properties('AWS::S3::Bucket', {
>        'BucketEncryption': Match.object_like({...})
>    })
>    ```
> 3. **CDK Nag**: Security compliance checks — fails if S3 is public, IAM is too permissive, etc.
>
> We run these on `cdk synth` output to catch issues before anything hits AWS."

**Q: "Someone manually changed an S3 bucket policy in the AWS console. How do you detect and fix it?"**

> "1. **Detection**: CloudFormation drift detection — `aws cloudformation detect-stack-drift --stack-name <name>`. It compares actual state vs template.
> 2. **Fix**: Run `cdk deploy` — CloudFormation will reconcile back to the template state. The manual change gets overwritten.
> 3. **Prevention**: IAM policies that restrict console access. Tag resources with `ManagedBy: CDK`. CloudTrail alerts on manual resource modifications."

**Q: "How do you handle secrets in CDK? You can't put passwords in code."**

> "We use Secrets Manager constructs. CDK creates the secret with a placeholder value, and we manually set the real value after deployment. The secret ARN is referenced by other resources.
>
> ```python
> secret = secretsmanager.Secret(self, 'DBPassword',
>     secret_name='/myapp/db-password',
>     generate_secret_string=SecretStringGenerator(exclude_punctuation=True)
> )
> # Pass to EC2 via instance profile + IAM policy (GetSecretValue)
> ```
>
> The secret value never appears in CDK code, CloudFormation templates, or git. Only the ARN is in the template."

**Q: "Your CDK deploy is failing with 'Resource limit exceeded'. What's happening?"**

> "CloudFormation has a **500 resource limit per stack**. If your stack is too large:
> 1. **Split into multiple stacks** — group by lifecycle (networking, compute, monitoring)
> 2. **Use cross-stack references** — `CfnOutput` in one stack, `Fn::ImportValue` in another
> 3. **Use nested stacks** — CDK's `NestedStack` for logical grouping within one deployment
>
> In our Outpost IaC project, we have 11 separate stacks — KMS, Secrets Manager, ECR, IAM, S3, RDS, etc. Each resource type has its own lifecycle and can be deployed independently. KMS keys rarely change, but ECR repos get added whenever we onboard a new service."

**Q: "How do you handle the CDK bootstrap in a new AWS account?"**

> "CDK bootstrap creates an S3 bucket and IAM roles that CDK needs to deploy. At TR we use a custom bootstrap template that adds our permission boundaries and tags:
>
> ```bash
> aws cloudformation deploy \
>   --template-file bootstrap-template.yaml \
>   --stack-name a207804-cdk-toolkit \
>   --parameter-overrides Qualifier=207804
> ```
>
> The qualifier (`207804`) is our asset ID — it scopes the bootstrap resources so multiple teams can bootstrap in the same account without conflicts."

**Q: "How do you deploy a specific stack to a specific environment?"**

> "Our CDK app uses context flags to drive everything — app name, environment, and region. The context determines which YAML config file gets loaded, which AWS account to target, and which stacks to deploy:
>
> ```bash
> # Deploy KMS stack to CI environment
> cdk deploy a207804-cng-ci-us-east-1-KMSStack \
>   -c app=cng -c environment=ci -c region=us-east-1
>
> # Deploy all stacks to QA
> cdk deploy --all \
>   -c app=cng -c environment=qa -c region=us-east-1
> ```
>
> The `app.py` entry point reads these context values, loads `environments/cng/us-east-1/cng_us-east-1_ci.yaml`, merges with `default.yaml` and `global.yaml`, then routes to the correct AWS account — preprod account for ci/demo/qa, prod account for prod/dr. Each stack gets a deterministic name like `a207804-cng-ci-us-east-1-KMSStack` so we can target individual stacks without affecting others."

---
