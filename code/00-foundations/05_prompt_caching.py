"""
Week 1, Day 5 — prompt caching, and the silent invalidator that eats your savings.

Interview relevance: "prompt caching cut your cost 60% — what did you restructure,
and what breaks the cache?" This is a high-signal question because most candidates
know caching exists and cannot explain the prefix-match invariant.

THE ONE RULE: caching is a PREFIX match. Any byte change anywhere in the prefix
invalidates everything after it. Render order is tools -> system -> messages.

Run: python 00-foundations/05_prompt_caching.py
"""

from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-opus-5"
client = anthropic.Anthropic()

# Opus 5 has a 512-token minimum cacheable prefix. Below that, cache_control is
# silently ignored — no error, cache_creation_input_tokens just comes back 0.
# (Opus 4.8 was 1024; Opus 4.6 and Haiku 4.5 are 4096. The minimum is NOT
# monotonic across generations, which trips people up when they switch models.)
LARGE_SYSTEM_PROMPT = (
    "You are a legal research assistant for Thomson Reuters. Follow these rules "
    "without exception.\n\n"
    + "\n".join(
        f"{i}. {rule}"
        for i, rule in enumerate(
            [
                "Every factual claim must be traceable to a retrieved source.",
                "Quote source text verbatim; never paraphrase inside a citation.",
                "If the retrieved passages do not answer the question, say so explicitly.",
                "Never infer a holding that is not stated in the provided text.",
                "Distinguish binding authority from persuasive authority.",
                "Note when a cited case has been overruled or distinguished.",
                "Flag jurisdiction mismatches between the question and the sources.",
                "Do not offer legal advice; report what the authorities say.",
                "Prefer the most recent controlling authority when sources conflict.",
                "State the standard of review where procedurally relevant.",
            ]
            * 12  # repeat to comfortably clear the 512-token minimum
        , start=1)
    )
)


def report(label: str, response) -> None:
    u = response.usage
    total = u.input_tokens + u.cache_creation_input_tokens + u.cache_read_input_tokens
    print(
        f"{label:<22} write={u.cache_creation_input_tokens:>6}  "
        f"read={u.cache_read_input_tokens:>6}  uncached={u.input_tokens:>5}  "
        f"total_prompt={total:>6}"
    )


def caching_works() -> None:
    """Two identical-prefix calls. First writes the cache, second reads it."""
    for i, question in enumerate(
        ["What is the standard for summary judgment?", "What is the standard for a Rule 12(b)(6) motion?"]
    ):
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": LARGE_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": question}],
        )
        report(f"call {i + 1}", response)

    print("\nThe second call reads the prefix at ~0.1x the input price. Writes cost")
    print("~1.25x, so two calls is roughly break-even and three is a clear win.")


def the_silent_invalidator() -> None:
    """The bug that quietly costs real money.

    A timestamp at the FRONT of the system prompt changes the prefix bytes on
    every request. cache_read_input_tokens stays at 0 forever, and you also pay
    the 1.25x write premium every single time — strictly worse than no caching.
    No error, no warning. You only find it by checking usage.
    """
    for i in range(2):
        poisoned = (
            f"Current time: {datetime.now(timezone.utc).isoformat()}\n\n"
            + LARGE_SYSTEM_PROMPT
        )
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=[
                {"type": "text", "text": poisoned, "cache_control": {"type": "ephemeral"}}
            ],
            messages=[{"role": "user", "content": "Summarise rule 1."}],
        )
        report(f"poisoned call {i + 1}", response)

    print("\nread stays at 0. Fix: move volatile content AFTER the last breakpoint.")


def the_fix() -> None:
    """Stable prefix cached; volatile context injected in the user turn."""
    for i in range(2):
        response = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": LARGE_SYSTEM_PROMPT,  # frozen — byte-identical every call
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        # volatile content lives here, after the breakpoint
                        f"<context>Current time: {datetime.now(timezone.utc).isoformat()}</context>\n"
                        "Summarise rule 1."
                    ),
                }
            ],
        )
        report(f"fixed call {i + 1}", response)


if __name__ == "__main__":
    print("=== 1. caching working as intended ===")
    caching_works()

    print("\n=== 2. the silent invalidator (a timestamp in the prefix) ===")
    the_silent_invalidator()

    print("\n=== 3. the fix — freeze the prefix, inject volatility later ===")
    the_fix()

    print(
        """
=== The audit checklist (memorise this) ===

Grep anything that feeds the prompt PREFIX for:

  datetime.now() / time.time()      -> prefix differs every request
  uuid4() / request IDs             -> same
  json.dumps() without sort_keys    -> non-deterministic byte order
  iterating a set                   -> non-deterministic order
  session/user ID in system prompt  -> per-user prefix, no cross-user sharing
  conditional system sections       -> every flag combination is a new prefix
  tools built per-user              -> tools render at position 0, nothing caches

What does NOT invalidate the messages cache: tool_choice, images, toggling
thinking. What DOES invalidate everything: changing tool definitions, or
switching models (caches are model-scoped).

Escape hatch: to change the system prompt mid-conversation without nuking the
cached history, append a {"role": "system", ...} message to `messages` instead
of editing top-level `system`. Supported on Opus 5.
"""
    )
