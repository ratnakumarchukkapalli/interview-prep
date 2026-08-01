"""
Week 1, Day 2 — tokens are the unit of cost, latency, and context. Measure them.

Interview relevance: "model the cost of this feature for 500 users doing 20
queries a day" is a standard FDE question. You cannot answer it by guessing.

The rule you must internalise: NEVER estimate Claude tokens with tiktoken.
That's OpenAI's tokenizer; it undercounts Claude by ~15-20% on prose and far
more on code. Use the count_tokens endpoint against the exact model you'll run.

Run: python 00-foundations/02_token_counting.py
"""

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-opus-5"

# $ per million tokens for claude-opus-5
PRICE_IN = 5.00
PRICE_OUT = 25.00
PRICE_CACHE_WRITE = PRICE_IN * 1.25  # 5-minute TTL
PRICE_CACHE_READ = PRICE_IN * 0.10

client = anthropic.Anthropic()


def count(text: str, system: str | None = None) -> int:
    kwargs = {"model": MODEL, "messages": [{"role": "user", "content": text}]}
    if system:
        kwargs["system"] = system
    return client.messages.count_tokens(**kwargs).input_tokens


def tokenization_intuition() -> None:
    """Show where tokens hide. This is the answer to 'explain tokenization to a
    lawyer asking why their bill went up when they started pasting tables'."""
    samples = {
        "plain english": "The parties agree to arbitrate all disputes.",
        "legal citation": "Brown v. Board of Educ., 347 U.S. 483 (1954)",
        "json": '{"jurisdiction": "NY", "effective_date": "2024-01-01"}',
        "markdown table": "| Clause | Risk | Notes |\n|---|---|---|\n| 4.2 | High | Uncapped |",
        "code": "def chunk(doc: str, size: int) -> list[str]: return [doc[i:i+size] for i in range(0, len(doc), size)]",
        "non-english": "Les parties conviennent de recourir à l'arbitrage.",
    }
    for label, text in samples.items():
        n = count(text)
        chars = len(text)
        print(f"{label:>16}: {n:>4} tokens / {chars:>4} chars  ({chars / n:.1f} chars per token)")


def cost_model() -> None:
    """The arithmetic an FDE does on a whiteboard.

    Scenario: enterprise doc RAG. 500 users, 20 queries/day, 22 working days.
    Each query: 8K-token system prompt + 6K tokens of retrieved context
    + 200-token question, producing ~600 tokens out.
    """
    users, queries_per_day, days = 500, 20, 22
    calls = users * queries_per_day * days

    system_tokens = 8_000  # stable — cacheable
    context_tokens = 6_000  # varies per query — not cacheable
    question_tokens = 200
    output_tokens = 600

    def usd(tokens: int, price: float) -> float:
        return tokens / 1_000_000 * price

    naive = calls * (
        usd(system_tokens + context_tokens + question_tokens, PRICE_IN)
        + usd(output_tokens, PRICE_OUT)
    )

    # With prompt caching on the system prefix: one write per 5-min window,
    # reads thereafter. Assume ~95% of calls land on a warm cache.
    cached = calls * (
        usd(system_tokens, PRICE_CACHE_READ) * 0.95
        + usd(system_tokens, PRICE_CACHE_WRITE) * 0.05
        + usd(context_tokens + question_tokens, PRICE_IN)
        + usd(output_tokens, PRICE_OUT)
    )

    print(f"calls / month        : {calls:,}")
    print(f"naive                : ${naive:,.2f}/month")
    print(f"with prompt caching  : ${cached:,.2f}/month")
    print(f"saving               : ${naive - cached:,.2f}  ({(1 - cached / naive) * 100:.0f}%)")
    print()
    print("Note where the money actually is: retrieved context, not the system")
    print("prompt. Halving chunk count is a bigger lever than caching here — and")
    print("that is the answer to 'the customer's bill is 4x what we bill them'.")


def context_budget() -> None:
    """Opus 5 has a 1M context window. That is not permission to fill it."""
    window = 1_000_000
    system = 8_000
    reserve_output = 16_000

    for chunk_size in (400, 800, 1600):
        available = window - system - reserve_output
        chunks = available // chunk_size
        print(f"chunk_size={chunk_size:>5} tokens -> up to {chunks:>6,} chunks fit")

    print()
    print("Fitting them is not the same as the model USING them. Retrieval")
    print("precision beats context stuffing: 20 well-ranked chunks outperform")
    print("2,000 mediocre ones, cost less, and answer faster. Say this out loud")
    print("when an interviewer offers you a big context window as a solution.")


if __name__ == "__main__":
    print("=== 1. where tokens hide ===")
    tokenization_intuition()

    print("\n=== 2. cost model ===")
    cost_model()

    print("\n=== 3. context budget ===")
    context_budget()
