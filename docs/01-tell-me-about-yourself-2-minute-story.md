# Section 1: Tell Me About Yourself (2-minute story)

### The Platform Context

> Thomson Reuters Confirmation is an audit confirmation platform used by auditors and financial institutions worldwide. Think of it this way — when a Big Four audit firm needs to independently verify a bank balance or a loan, they send a confirmation request through our platform. The bank receives it, responds, and the auditor gets a verified response. It's a critical part of the financial audit process — regulatory compliance depends on it.
>
> Under the hood, it's 40+ .NET microservices — Orleans for distributed computing, GraphQL APIs, RabbitMQ for async messaging, PostgreSQL databases — all running on AWS EKS Outposts across 8 environments from CI through Production and DR.

### My Story

> I'm Ratna Kumar, a Senior DevOps Engineer at Thomson Reuters. I joined the Audit & Confirmation platform team in January 2025, and from day one I've been deeply hands-on with the infrastructure.
>
> **The first big thing I worked on was the migration from AWS Cloud EKS to EKS Outposts.** Our platform had data residency requirements — customer audit data needed to stay within specific boundaries. So we migrated 30+ microservices from standard AWS Cloud to Outposts. This wasn't just moving pods — I managed the Helm charts for all these services across 8 environments, set up ArgoCD GitOps for deployment automation, configured Istio service mesh with strict mTLS for zero-trust networking, and implemented Argo Rollouts for canary deployments so we could safely roll out changes with traffic splitting.
>
> **On the CI/CD side**, we had a central template library for GitHub Actions — reusable workflows that all 40+ services call. I contributed to and maintained several of these templates, including the Python microservice CI pipeline and Docker build workflows. I also authored a few AWS CDK stacks in Python for infrastructure — ECR repositories, KMS keys, IAM roles — the foundational pieces services need before they can even deploy.
>
> **I also built two FastAPI microservices from scratch** that power our internal DevOps Portal. The first is `service-ops` — it gives our team self-service capabilities for pod restarts, Kubernetes status checks, and secrets management through a web UI instead of everyone needing kubectl access. The second is `k8s-ops-assistant` — an AI-powered operations assistant I pioneered using Claude AI. It uses a multi-agent architecture where natural language queries get routed to specialized Kubernetes or Datadog agents. So instead of writing complex Datadog queries or kubectl commands, the team can just ask "why is pricing-be restarting?" and get answers.
>
> **On the operational side**, I onboarded RabbitMQ Operator with CA bundle TLS injection via ArgoCD PreSync hooks, managed PostgreSQL HA with pgBackRest backups, rolled out Radware WAF for OWASP protection, and handled 3 RabbitMQ production incidents end-to-end — from initial alert to root cause to resolution.
>
> Before TR, I worked at Arrise on ELK stack observability and ElastAlert automation for a gaming platform, at Turvo on Dynatrace APM for logistics SaaS, and started at TCS on GCP infrastructure with Cloud Deployment Manager and BigQuery.
>
> What excites me about this Westpac opportunity is the scale and reliability demands of banking infrastructure — it's exactly the discipline I practice daily managing production Kubernetes across multiple environments.

### Tips for Delivery

- **Don't memorize word-for-word** — know the story beats, fill naturally
- **Start with the platform context** — sets the stage so the interviewer understands WHY your work matters
- **"Migration from Cloud to Outposts"** is your anchor story — it touches K8s, Helm, ArgoCD, Istio, everything
- **Two APIs, not five** — be precise. service-ops and k8s-ops-assistant are impressive enough
- **Pause between sections** — let the interviewer absorb before you move on
- **Watch the clock** — aim for 2 minutes max. If they want more, they'll ask

---
