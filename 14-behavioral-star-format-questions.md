# Section 14: Behavioral / STAR Format Questions

### 14.1 How STAR Works

**S**ituation → **T**ask → **A**ction → **R**esult

Keep each section to 2-3 sentences. The interviewer wants to hear your decision-making process, not a 10-minute story.

---

### 14.2 "Tell me about a time you handled a critical production incident"

**INC-001: MassTransit Consumer Missing — record-gql-be CrashLoopBackOff**

> **S**: "In February 2026, our record-gql-be service went into CrashLoopBackOff in QA with exit code 139. The service had been down for about 24 hours before I picked it up."
>
> **T**: "I needed to find the root cause and restore the service as quickly as possible."
>
> **A**: "I started with `kubectl logs --previous` which showed a `MassTransit.RequestTimeoutException` — not the segfault the exit code suggested. I traced the code to `FormService.InitializeFormNames()` which makes a synchronous RabbitMQ request to the `get-form-types-by-product` queue. I checked consumer counts: `rabbitmqctl list_queues name consumers` showed zero consumers on that queue. The consuming service, forms-be, was running but had silently stopped registering its MassTransit consumer after a deployment."
>
> **R**: "Restarted forms-be, consumers re-registered, record-gql-be started immediately. I documented the incident with the key lesson: always check RabbitMQ consumer counts first for MassTransit timeouts. Exit code 139 with Datadog CLR profiler is misleading — read the actual exception."

---

### 14.3 "Tell me about a time you automated something that saved significant time"

**k8s-ops-assistant — AI-Powered Operations**

> **S**: "Our team of 5 manages 40+ microservices across 8 environments. Investigating an incident — checking Datadog logs, K8s pod status, tracing requests — took 30-45 minutes per query, and we handled 5-10 of these per week."
>
> **T**: "I proposed building an AI-powered assistant that could answer natural language questions using Kubernetes and Datadog APIs directly."
>
> **A**: "I designed and built a multi-agent FastAPI service with Claude AI as the reasoning engine. Three specialized agents (Datadog with 19 tools, K8s with 10 tools, Cert with 1 tool), rule-based routing for deterministic query assignment, SSE streaming for real-time feedback, and JWT RS256 authentication. I integrated it with the DevOps portal so the whole team could use it through a chat interface."
>
> **R**: "Investigations that took 30-45 minutes now complete in under 90 seconds. The whole team — including developers without kubectl access — can now troubleshoot independently. I presented this to leadership, and it's being evaluated for adoption by other TR teams."

---

### 14.4 "Tell me about a time you dealt with a cascading failure"

**CHG0130049 — Proxy Change Broke 5 Services**

> **S**: "The network team pushed a routing change (CHG0130049) that sent all outbound traffic through a corporate proxy. Five different services broke for five different reasons over the following week."
>
> **T**: "I needed to systematically identify and fix each affected service while preventing further cascading failures."
>
> **A**: "I categorized services by management type: Helm-managed (automatically got proxy config), operator-managed (RabbitMQ, PostgreSQL — needed manual check), and manually-managed (Selenium Grid — had no proxy at all). For each broken service, I diagnosed the specific failure: reports-dwh-be was missing NO_PROXY entries for internal hostnames, Selenium nodes had no proxy env vars, file-service-be's FTPS connection was blocked by the proxy's CONNECT policy. I fixed each systematically and documented the root cause for each."
>
> **R**: "All services restored within 48 hours. I created a runbook: 'After any network infrastructure change, verify ALL service categories — Helm-managed, operator-managed, and manually-managed.' This runbook was used for the next network change and caught issues proactively before they became incidents."

---

### 14.5 "Tell me about a time you had to learn a new technology quickly"

**Istio Service Mesh + Argo Rollouts**

> **S**: "When I joined Thomson Reuters in January 2025, the team was migrating from AWS Cloud EKS to EKS Outposts. The new platform used Istio service mesh and Argo Rollouts — technologies I hadn't worked with before."
>
> **T**: "I needed to become proficient enough to manage Istio configuration, debug traffic routing issues, and configure canary deployments for 40+ services within weeks."
>
> **A**: "I took a hands-on approach: I read the Istio documentation end-to-end, then traced real traffic flows through our platform — from F5 BigIP through KWAF to Istio IngressGateway to pods. I created a personal reference guide (928 lines) documenting every Istio resource, our naming conventions, hostname patterns, and debug commands. For Argo Rollouts, I studied how our Helm templates configure canary with VirtualService weight patching. I tested everything in CI before touching QA or production."
>
> **R**: "Within a month, I was independently managing Istio configuration and debugging traffic routing issues. My reference guide (`istio-traffic-flow-guide.md`) became a team resource. I later wrote a comprehensive Kubernetes resources guide documenting all 18 resource types per service."

---

### 14.6 "Tell me about a time you disagreed with a technical decision"

**ESSO Token vs CIAM M2M Authentication**

> **S**: "Our AI assistant used an ESSO token (human SSO token) to authenticate with the TR AI Platform. This token expired every hour and required a daily rotation job or manual update in Secrets Manager. If the rotation failed, the service went down."
>
> **T**: "I believed this was the wrong architecture — using a human identity for a service-to-service flow. I proposed switching to CIAM M2M (OAuth2 client_credentials), but there was pushback because 'the ESSO token works and we have bigger priorities.'"
>
> **A**: "I built a proof-of-concept showing the CIAM M2M approach: `CIAMTokenClient` with cache-first design, 5-minute pre-expiry refresh buffer, and `invalidate()` for downstream rejection recovery. I quantified the operational cost: ESSO required daily manual intervention (or a cron job that sometimes failed), while CIAM M2M was completely self-managing after one-time setup. I presented a comparison table showing token lifetime (1h vs 24h), rotation method, ops overhead, and security posture."
>
> **R**: "The team agreed to implement CIAM M2M. After deploying, the service ran for weeks without any token-related issues — no more 3 AM pages about expired tokens. The `CIAMTokenClient` pattern is now being adopted by other portal services."

---

### 14.7 "Tell me about a time you improved a process"

**DevOps Portal — Self-Service for Pod Restart and Secrets**

> **S**: "Restarting a service or updating a secret required kubectl access, which only 3 people on the team had. Developers would open a Slack ticket, wait for someone to be available, and watch them type commands. This created bottlenecks, especially during working hours in multiple time zones."
>
> **T**: "I wanted to give the team self-service access to safe operations — pod restarts and secret updates — without giving everyone cluster admin access."
>
> **A**: "I built the service-ops FastAPI API with JWT RS256 authentication (so only authorized users from our AD group can call it), annotation-based restarts (zero-downtime via Argo Rollout, not pod delete), deep-merge secret updates (preserves untouched keys), and DynamoDB audit trail (full before-state + user attribution for every change). I integrated it with the React DevOps portal so operations are point-and-click."
>
> **R**: "Pod restarts went from 15-minute Slack conversations to 10-second self-service operations. Secret updates went from error-prone manual JSON editing to safe, audited partial updates. The DynamoDB audit trail has been used twice to restore secrets that were accidentally broken. The team is more autonomous, and I'm no longer a bottleneck for routine operations."

---

### 14.8 "Tell me about a difficult debugging scenario"

**INC-002: CloudFront + WAF — Blank Page in QED**

> **S**: "The responder-queue frontend was showing a blank page in QED (production-like environment). The page appeared to load — HTTP 200, HTML served — but no content rendered."
>
> **T**: "I needed to find why the page was blank when the HTTP response looked healthy."
>
> **A**: "The 200 status was the trap — CloudFront had a custom error response that converts 403 errors to 200 + `index.html`. The real error was 403 from S3. I found two stacked issues: (1) the CloudFront distribution referenced a deleted Origin Access Identity, so ALL S3 requests returned 403, and (2) the nested CloudFront had a WAF with `DefaultAction: Block` and a stale IP allowlist (125 CIDRs vs 199 published). I systematically ruled out S3 contents, bucket policy, and cache behaviors before finding the WAF."
>
> **R**: "Fixed both issues: replaced the deleted OAI, and ITOPS disabled WAF on the nested CloudFront (the umbrella already protects). My takeaway: **check WAF EARLY** when `x-cache: Error from cloudfront` appears. Custom error responses that mask real status codes make debugging exponentially harder."

---

### 14.9 "What's your biggest weakness?" (Common Behavioral)

> "I tend to go deep into technical details when explaining something, which can overwhelm non-technical stakeholders. I've learned to lead with the impact — 'this will reduce incident response time from 45 minutes to 90 seconds' — and only dive into the how when asked. Building the DevOps portal helped me practice this: I had to explain to management why we needed 4 backend services, in terms of team productivity and risk reduction, not in terms of async Python and DynamoDB audit trails."

---

### 14.10 "Why are you leaving Thomson Reuters?"

> "I'm not leaving because I'm unhappy — I've had one of the most productive years of my career. I migrated 30+ services to EKS Outposts, built 2 FastAPI microservices, pioneered an AI-powered operations assistant, and handled multiple production incidents end-to-end. But the Westpac opportunity offers what I'm looking for next: the scale and reliability demands of banking infrastructure. Financial services platforms have zero tolerance for downtime, strict regulatory compliance, and massive transaction volumes. I want to apply everything I've built at TR — Kubernetes, GitOps, observability, security — in an environment where the stakes are even higher."

---

### 14.11 "Where do you see yourself in 3-5 years?"

> "I want to grow into a platform engineering leadership role — either as a Staff/Principal DevOps Engineer or an Engineering Manager for a platform team. I want to design and build the infrastructure foundations that product teams build on. At TR, I've been doing this at the individual contributor level: building shared tools (DevOps portal), establishing patterns (Helm templates, CI/CD workflows), and creating self-service capabilities (service-ops, k8s-ops-assistant). In 3-5 years, I want to be doing this at a larger scale — defining platform strategy, mentoring engineers, and making architectural decisions that impact entire organizations."

---

### 14.12 Questions to Ask the Interviewer

Always prepare 3-5 questions. Pick 2-3 based on the conversation:

| Question | Why You're Asking |
|----------|------------------|
| "What does the Kubernetes platform look like at Westpac — EKS, AKS, self-managed?" | Shows you're thinking about the technical environment |
| "How does the team handle incident response — is there a dedicated SRE team or is it shared?" | Shows you care about operational maturity |
| "What's the biggest technical challenge the team is facing right now?" | Shows you want to contribute immediately |
| "How do deployments work — GitOps, Jenkins, manual?" | Shows you'll bring your ArgoCD/GitOps expertise |
| "What does success look like for this role in the first 90 days?" | Shows you're results-oriented |
| "How does the team approach security and compliance for banking workloads?" | Relevant to Westpac — shows domain awareness |

---
