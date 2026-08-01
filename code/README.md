# Code — FDE / AI Engineer Prep

Runnable projects for the 8-week plan in [docs/FDE-PLAN.md](../docs/FDE-PLAN.md).

**Type everything by hand.** Reading a RAG pipeline teaches you nothing about debugging one, and every interview question is about debugging one.

## Layout

```
00-foundations/     Week 1 — SDK client, tokens, streaming, structured output, caching
01-rag-pgvector/    Week 2 — production RAG on Postgres + pgvector with citations
02-eval-harness/    Week 3 — golden dataset, LLM judge, CI quality gate
03-agent/           Week 4 — agent from scratch, LangGraph version, MCP server
04-ml-cases/        Week 5 — 5 timed HackerRank-style ML cases
05-llmops/          Week 6 — tracing, guardrails, eval-gated K8s rollout
drills/             Daily DS&A + SQL, one directory per week
```

## Setup

```bash
cd code
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # then fill in ANTHROPIC_API_KEY
```

Verify:

```bash
python 00-foundations/01_first_call.py
```

## Notes on the API surface

These examples target **Claude Opus 5** (`claude-opus-5`). A few things differ from older tutorials you'll find online, and knowing why is itself interview material:

- **Adaptive thinking is on by default.** No `budget_tokens` — that parameter is removed and returns a 400. Depth is controlled by `output_config={"effort": ...}` (`low`/`medium`/`high`/`xhigh`/`max`).
- **No `temperature`, `top_p`, or `top_k`.** Removed; steer with prompting instead. If an interviewer asks how you control determinism, the answer is prompt design plus low effort, not a sampling knob.
- **`max_tokens` caps thinking *plus* response text.** Size it accordingly — 16K for non-streaming, 64K when streaming.
- **Stream anything above ~16K output**, or you'll hit SDK HTTP timeouts.
- **Prompt caching has a 512-token minimum** on Opus 5. Below that, `cache_control` silently does nothing — `cache_creation_input_tokens` comes back 0.
