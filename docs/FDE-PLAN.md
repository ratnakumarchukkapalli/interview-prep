# 8-Week Prep Plan — Forward Deployed Engineer / AI Engineer @ Thomson Reuters

**Candidate:** Ratna Kumar Chukkapalli — Senior DevOps Engineer, Confirmation Platform @ TR
**Target roles:** Forward Deployed Engineer (FDE) + AI Engineer (internal TR postings)
**Start:** 2026-07-27 · **Target readiness:** 2026-09-20
**Budget:** 2 hrs/weekday + 1 long weekend session (~110 hrs total)

---

## 1. What you're actually being tested on

### The FDE interview loop (3 rounds)

| Round | What it is | Weight | Your risk |
|-------|-----------|--------|-----------|
| **Behavioral / Fit** | "Why FDE?", ownership, ambiguity, difficult stakeholder, 0→1 project you owned | High | **Medium** — you have the stories but they're told as *infra* stories, not *customer outcome* stories |
| **Technical Deep Dive** | Practical coding (parse messy data → build a query API), data-heavy system design (RAG, real-time pipeline) | High | **Medium** — strong on systems, thin on LLM-app architecture vocabulary |
| **Decomposition / Case Study** | 60 min on a huge ambiguous problem. Palantir-invented; the real filter. | **Highest** | **High** — this is a *learnable framework* and you've never drilled it |

### The TR HackerRank gate (AI/ML roles)

- 1–2 Python DS&A problems — LeetCode-easy/medium: strings, sliding window, matrix traversal, graph traversal, DP
- 1 applied ML case — recommender system, model evaluation, feature selection from noisy data
- SQL — joins, `GROUP BY`, and **window functions** (`ROW_NUMBER`, `RANK`, `LAG`/`LEAD`, running totals)
- Occasionally financial math (CAGR, NPV) — TR is a financial/legal data company

**This gate is pass/fail and it is a speed test.** You cannot cram it in week 8. That's why there is a coding drill *every single day* below.

---

## 2. Honest gap analysis

### Already strong (do not over-study these)
- Kubernetes, EKS, Istio, Helm/ArgoCD — deep, production, on Outposts. This is **table stakes** for FDE and you have it well past bar.
- Terraform / AWS CDK / IaC, CI/CD (GitHub Actions), AWS networking, secrets management
- Observability (OpenTelemetry, Datadog) — directly reusable as *LLM* observability
- PostgreSQL HA + internals — **major leverage**: pgvector means your RAG store is a DB you already understand better than most AI engineers
- FastAPI / Python microservices
- Security: JWT RS256, mTLS, WAF, 7-layer defense — maps straight onto AI guardrails and multi-tenant isolation
- You built the K8s AI Ops Assistant: multi-agent, agentic loop, 30 tools, M2M auth. **This is your single best asset and it is currently underexploited.**

### Real gaps (this is where the 110 hrs go)
| Gap | Why it matters | Weeks |
|-----|---------------|-------|
| RAG as a discipline — chunking, hybrid search, reranking, citations | The #1 thing FDEs actually build | 2–3 |
| Evaluation frameworks | Named explicitly in Anthropic/OpenAI FDE specs. Most candidates hand-wave this; it's your differentiator | 3 |
| DS&A speed under a timer | HackerRank gate. Perishable skill — needs daily reps | 1–8 |
| SQL window functions | Appears on TR assessments; DevOps work rarely exercises it | 2–3 |
| Classical ML fundamentals + metrics | The HackerRank ML case + AI Engineer interviews | 5 |
| Recommender systems | Explicitly cited as a TR ML case type | 5 |
| Inference economics (tokens, caching, latency, cost) | FDEs own the customer's bill and SLOs | 6 |
| Fine-tuning vs RAG vs prompting judgment | Standard senior AI-engineer question | 6 |
| Decomposition round technique | Highest-weight round, zero reps so far | 7 |
| Customer-facing narrative reframing | FDE is 50% communication | 1, 8 |
| TR AI product landscape (CoCounsel, Westlaw, Practical Law) | Internal interview — they expect you to know the business | 8 |

---

## 3. The daily rhythm (2 hrs, weekdays)

```
0:00–0:20   Coding drill      2 problems, timed. Non-negotiable. Every day.
0:20–1:20   Topic block       Read the week's HTML guide section
1:20–1:50   Hands-on          Build in code/ — type it, don't read it
1:50–2:00   Active recall     Answer 3 interview questions out loud, from memory, no notes
```

**Weekend:** one 3–4 hr build session (ship the week's project) + one mock via `/fde-interview`.

Rules that make this work:
1. **Never skip the coding drill.** 20 min × 40 days = 80 problems. That clears the HackerRank gate.
2. **Type all code by hand.** Reading a RAG pipeline teaches you nothing about debugging one.
3. **Active recall beats re-reading.** If you can't say it out loud, you don't know it.
4. **Every guide ends in interview questions.** Answer them written, then compare.

---

## 4. Week-by-week

### Week 1 — Foundations & Narrative (Jul 27 – Aug 2)
| Asset | Content |
|-------|---------|
| Guide 20 | **The FDE & AI Engineer Role Decoded** — what the job actually is, the 3 rounds, TR context, your gap map, how to position 8 yrs of DevOps as an advantage |
| Guide 21 | **LLM Internals for Engineers** — tokenization, embeddings, attention intuition, context windows, sampling params, why hallucination is structural, model selection |
| Guide 22 | **Prompt Engineering as an Engineering Discipline** — system prompts, few-shot, CoT, structured output/JSON schema, prompt versioning, caching-aware prompt layout |
| Code | `code/00-foundations/` — Anthropic SDK client, token counting, streaming, structured output, retry/backoff |
| Drill | Arrays, two pointers, hash maps — 10 problems |
| Deliverable | Rewritten 2-min story + "Why FDE?" answer, customer-outcome framed |

### Week 2 — Retrieval, Part 1 (Aug 3 – Aug 9)
| Asset | Content |
|-------|---------|
| Guide 23 | **Embeddings & Vector Search** — embedding models, cosine vs dot vs L2, ANN indexes (HNSW, IVFFlat), pgvector deep dive, chunking strategies and their failure modes |
| Guide 24 | **Building a Production RAG Pipeline** — ingestion, document parsing, chunking, metadata filters, query rewriting, retrieval, context assembly, mandatory citations |
| Code | `code/01-rag-pgvector/` — end-to-end RAG over a document corpus using Postgres + pgvector, with citation enforcement |
| Drill | Strings, sliding window, stacks/queues — 10 problems |
| SQL | Joins, `GROUP BY`, `HAVING`, CTEs — 15 queries |

### Week 3 — Retrieval, Part 2 & Evaluation (Aug 10 – Aug 16)
| Asset | Content |
|-------|---------|
| Guide 25 | **Advanced Retrieval** — hybrid BM25 + dense, reciprocal rank fusion, cross-encoder reranking, HyDE, query decomposition, multi-hop, contextual retrieval, GraphRAG, agentic retrieval |
| Guide 26 | **Evaluation & LLM-as-Judge** — recall@k / MRR / NDCG, faithfulness & groundedness, golden datasets, judge design and its biases, CI regression gates, online evals |
| Code | `code/02-eval-harness/` — pytest eval suite, golden dataset, LLM judge, CI gate that fails the build on quality regression |
| Drill | Trees, BFS/DFS, recursion — 10 problems |
| SQL | Window functions — `ROW_NUMBER`, `RANK`, `DENSE_RANK`, `LAG`/`LEAD`, running totals, percentiles — 15 queries |

### Week 4 — Agents (Aug 17 – Aug 23)
| Asset | Content |
|-------|---------|
| Guide 27 | **Agent Architectures** — the tool-calling loop, ReAct, planner-executor, reflection, multi-agent orchestration, LangGraph, MCP, memory, context engineering, failure modes, *when not to use an agent* |
| Guide 28 | **Your K8s Ops Assistant, Retold as an FDE Story** — reframe the existing project as a customer-outcome narrative; whiteboard-ready architecture; the 15 hard questions a panel will ask about it |
| Code | `code/03-agent/` — tool-calling agent from scratch (no framework), then the LangGraph version, then an MCP server |
| Drill | Graphs, topological sort, heaps — 10 problems |
| Mock | Technical deep dive #1 |

### Week 5 — Classical ML for the HackerRank Case (Aug 24 – Aug 30)
| Asset | Content |
|-------|---------|
| Guide 29 | **ML Fundamentals for AI Engineers** — supervised/unsupervised, bias-variance, train/val/test, cross-validation, regularization, the algorithm zoo with *when to use which*, feature engineering, imbalanced data, leakage |
| Guide 30 | **Metrics & Model Evaluation** — confusion matrix, precision/recall/F1, ROC-AUC vs PR-AUC, threshold tuning, calibration, regression metrics, mapping metrics to business outcomes |
| Guide 31 | **Recommender Systems & TR's ML Case Patterns** — content-based, collaborative filtering, matrix factorisation, implicit feedback, cold start; plus worked "noisy feature selection" and "model evaluation" cases |
| Code | `code/04-ml-cases/` — 5 timed HackerRank-style ML notebooks with reference solutions |
| Drill | Binary search, intervals, sorting patterns — 10 problems |

### Week 6 — Production AI: Cost, Safety, LLMOps (Aug 31 – Sep 6)
| Asset | Content |
|-------|---------|
| Guide 32 | **Inference Economics & Latency** — token budgets, prompt caching, batching, streaming, KV cache, quantization, model routing/cascades, per-customer cost modelling, SLOs |
| Guide 33 | **Fine-Tuning vs RAG vs Prompting** — decision framework, SFT, LoRA/QLoRA, DPO, distillation, data curation, when fine-tuning actually wins |
| Guide 34 | **Guardrails, Safety & LLMOps on Kubernetes** — prompt injection, jailbreaks, PII/DLP, output validation, hallucination control and mandatory citations for legal, tracing, eval-gated canary deploys, multi-tenant isolation *(heavy reuse of your Istio/security depth)* |
| Code | `code/05-llmops/` — tracing middleware, guardrail layer, K8s manifests with eval-gated rollout |
| Drill | Dynamic programming, greedy — 10 problems |

### Week 7 — System Design & Decomposition (Sep 7 – Sep 13)
| Asset | Content |
|-------|---------|
| Guide 35 | **AI System Design Playbook** — the framework plus 6 worked designs: TB-scale enterprise document RAG, real-time analytics pipeline, multi-tenant AI gateway, agent eval platform, document extraction pipeline, semantic search over a legal corpus |
| Guide 36 | **The Decomposition Round** — the Palantir-style case; 6-step framework; 5 worked cases with full transcripts; the anti-patterns that fail candidates |
| Code | 3 × 90-min full HackerRank simulations under timer |
| Mock | System design round + decomposition round |

### Week 8 — Behavioral, TR Context, Full Mocks (Sep 14 – Sep 20)
| Asset | Content |
|-------|---------|
| Guide 37 | **FDE Behavioral & Stakeholder Round** — 20 questions mapped to *your* STAR stories: ownership, ambiguity, difficult customer, teaching non-technical users, disagreement, failure |
| Guide 38 | **Thomson Reuters AI Landscape** — CoCounsel, Westlaw, Practical Law, ONESOURCE, Checkpoint; legal-AI constraints (citations are non-negotiable, hallucination is catastrophic); internal-transfer strategy; what to ask them |
| Guide 39 | **Final 48 Hours** — cheat sheets, formulas, one-pagers, rapid recall |
| Mock | 2 full loops via `/fde-interview` |

---

## 5. Deliverables

**HTML guides** — `html/20-*.html` through `html/39-*.html`, continuing the existing numbering and styling.

**Runnable code** — `code/`:
```
code/
  00-foundations/     SDK client, token counting, streaming, structured output
  01-rag-pgvector/    Production RAG on Postgres + pgvector
  02-eval-harness/    Golden dataset, LLM judge, CI quality gate
  03-agent/           From-scratch agent, LangGraph version, MCP server
  04-ml-cases/        5 timed HackerRank-style ML cases
  05-llmops/          Tracing, guardrails, eval-gated K8s deploy
  drills/             Daily DS&A + SQL, by week
```

**Skill** — `/fde-interview`: mock interviewer covering all three FDE rounds plus HackerRank simulation and the decomposition case.

---

## 6. Positioning: your DevOps background is the moat, not the handicap

Most AI Engineer candidates can build a RAG demo in a notebook. Almost none of them can:
- run it multi-tenant on Kubernetes with mTLS and per-tenant isolation
- put an eval gate in the deploy pipeline so a prompt change can't ship a regression
- trace a latency spike from the API gateway through to a slow vector query
- reason about the cost curve when the customer's corpus grows 50×
- do a Postgres PITR when someone drops the embeddings table

**That is precisely the FDE job description.** The FDE is the person who gets the AI system *actually working inside a customer's real infrastructure* — and the failure modes there are infrastructure failure modes.

Your one-line positioning:

> "I've spent eight years making distributed systems work in production under real constraints, and the last stretch building an agentic assistant that 200+ engineers use to operate Kubernetes. The gap between an AI demo and an AI system in production is mostly infrastructure, security, and evaluation — that's the gap I've been living in."

Do not apologise for not having an ML PhD. FDE is not an ML research role.

---

## 7. Progress tracker

| Week | Guides | Code | Drills | Mock | Done |
|------|--------|------|--------|------|------|
| 1 | 20, 21, 22 | 00-foundations | 10 + narrative | — | ☐ |
| 2 | 23, 24 | 01-rag-pgvector | 10 + 15 SQL | — | ☐ |
| 3 | 25, 26 | 02-eval-harness | 10 + 15 SQL | — | ☐ |
| 4 | 27, 28 | 03-agent | 10 | Deep dive #1 | ☐ |
| 5 | 29, 30, 31 | 04-ml-cases | 10 | HackerRank sim | ☐ |
| 6 | 32, 33, 34 | 05-llmops | 10 | Deep dive #2 | ☐ |
| 7 | 35, 36 | 3 timed sims | mixed | Design + decomp | ☐ |
| 8 | 37, 38, 39 | — | mixed | 2 full loops | ☐ |
