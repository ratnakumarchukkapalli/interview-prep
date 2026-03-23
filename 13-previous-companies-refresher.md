# Section 13: Previous Companies Refresher

### 13.1 TCS — Junior DevOps Engineer (GCP)

**Duration**: ~2 years | **Platform**: Google Cloud Platform | **Client**: Large enterprise

**What I Did:**

| Area | Contribution |
|------|-------------|
| **GCP Infrastructure** | Provisioned VMs, VPCs, Cloud SQL, Cloud Storage using Cloud Deployment Manager (GCP's IaC — YAML-based, similar to CloudFormation) |
| **BigQuery** | Managed data pipelines — scheduling queries, optimizing partitioned tables, setting up datasets for analytics team |
| **CI/CD** | Jenkins pipelines for Java microservices — build, test, deploy to GKE |
| **Monitoring** | Stackdriver (now Cloud Monitoring) — set up dashboards and alerting policies |
| **Scripting** | Bash and Python automation for provisioning and maintenance tasks |

**Interview Story:**

> "At TCS, I started as a junior DevOps engineer on a GCP project. My biggest learning was infrastructure-as-code through Cloud Deployment Manager — writing YAML templates to provision GCP resources consistently. I also worked with BigQuery for the analytics pipeline, scheduling ETL jobs and optimizing query performance through table partitioning. This is where I built my foundation in cloud infrastructure, Linux administration, and automation scripting."

**Connecting to Current Role:**

> "The GCP experience directly maps to what I do now: Cloud Deployment Manager → AWS CDK, Stackdriver → Datadog, GKE → EKS, BigQuery → PostgreSQL/Citus data warehouse. The tools changed, the principles stayed the same."

---

### 13.2 Turvo — DevOps Engineer (Dynatrace/ELK)

**Duration**: ~1.5 years | **Platform**: AWS | **Domain**: Logistics SaaS

**What I Did:**

| Area | Contribution |
|------|-------------|
| **Dynatrace APM** | Full-stack monitoring for Java/Kotlin microservices — configured OneAgent, set up service flow analysis, built dashboards for P95 latency and error rates |
| **ELK Stack** | Elasticsearch + Logstash + Kibana for centralized logging. Managed index lifecycle policies, built Kibana dashboards for operations team |
| **AWS Infrastructure** | EC2, RDS, S3, ELB management — routine operations and capacity planning |
| **Alerting** | Dynatrace problem detection + custom alerting rules for SLA breaches |
| **Incident Response** | On-call for production incidents — used Dynatrace to trace latency spikes to specific microservice calls |

**Interview Story:**

> "At Turvo, I was responsible for observability of a logistics SaaS platform. I rolled out Dynatrace APM across 20+ Java microservices — what I learned there directly shaped how I approach observability now. Dynatrace's automatic service discovery and distributed tracing showed me what good observability looks like: you should be able to follow a single request across every service it touches. I also managed the ELK stack for log aggregation — Elasticsearch cluster management, index lifecycle policies, Logstash pipelines. The shift from ELK to Datadog at TR was easy because the concepts are the same — ingest, index, query, alert."

**Connecting to Current Role:**

> "Dynatrace → Datadog (both APM with distributed tracing), ELK → Datadog Logs (both centralized logging with indexing), Dynatrace OneAgent → Datadog Agent (both auto-instrumentation). The biggest difference is Datadog unifies all three pillars (logs, metrics, traces) in one platform, while at Turvo we had Dynatrace for traces and ELK for logs — two separate systems."

---

### 13.3 Arrise — Senior DevOps Engineer (ELK/ElastAlert/Grafana)

**Duration**: ~1.5 years | **Platform**: AWS/On-Prem | **Domain**: Gaming/iGaming

**What I Did:**

| Area | Contribution |
|------|-------------|
| **ELK Stack (scaled)** | Managed large-scale Elasticsearch clusters — hot-warm-cold architecture for cost optimization, cross-cluster replication, index template management |
| **ElastAlert** | Built automated alerting system — 50+ alert rules for error rate spikes, latency thresholds, queue depth, disk space. Alerts → Slack, PagerDuty, email |
| **Grafana Dashboards** | Created operational dashboards pulling from Elasticsearch and Prometheus — service health, infrastructure metrics, business KPIs |
| **Kubernetes** | Managed K8s clusters (not EKS — bare-metal/VM-based). Helm deployments, namespace management, resource quotas |
| **Terraform** | Infrastructure-as-code for AWS resources — VPCs, EC2, RDS, S3, IAM |
| **Incident Management** | Led production incident response for the gaming platform — high-traffic, low-tolerance-for-downtime environment |

**Interview Story:**

> "At Arrise, I managed observability for a gaming platform that processes millions of transactions per second. The ELK stack at this scale was complex — I implemented hot-warm-cold architecture to optimize costs (recent data on SSDs, older data on HDDs, archive to S3). I built ElastAlert automation with 50+ rules that detected anomalies and alerted the team before customers noticed. The gaming industry has zero tolerance for downtime — if the platform is down during a major event, the revenue loss is immediate and massive. This taught me to think about monitoring proactively, not reactively.
>
> I also started working with Kubernetes here — my first exposure to container orchestration. The shift from VM-based deployments to K8s was eye-opening. When I moved to Thomson Reuters, I brought this K8s foundation and scaled it to 40+ services with GitOps."

**Connecting to Current Role:**

> "ELK → Datadog (log management), ElastAlert → Datadog Monitors (automated alerting), Grafana → Datadog Dashboards (visualization), Terraform → AWS CDK (IaC), bare-metal K8s → EKS Outposts. The gaming platform's high-throughput requirements taught me to think about scale — which directly applies to managing Confirmation's production clusters."

---

### 13.4 Career Progression Story

> "My career follows a clear progression: **infrastructure → observability → platform engineering**.
>
> At **TCS**, I learned cloud infrastructure fundamentals — GCP, IaC, CI/CD basics.
> At **Turvo**, I specialized in observability — Dynatrace APM taught me distributed tracing and service dependency mapping.
> At **Arrise**, I combined infrastructure + observability at scale — large ELK clusters, 50+ alert rules, Kubernetes adoption.
> At **Thomson Reuters**, I brought it all together — managing the full platform lifecycle: Kubernetes operations, Helm/ArgoCD GitOps, Istio service mesh, observability with OTEL and Datadog, and pioneering AI-powered operations.
>
> Each role built on the previous one. The tools changed, but the principles compounded."

---
