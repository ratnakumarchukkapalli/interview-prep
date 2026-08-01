"""
Week 1, Day 3 — streaming, and why it is a latency *perception* fix, not a
latency fix.

Interview relevance: "your p50 is 1.2s and p99 is 14s — where does that spread
come from?" and "the customer's SLO is 2 seconds but chain-of-thought made it
4x slower. Options?" Both are answered with the concepts here.

Run: python 00-foundations/03_streaming.py
"""

import time

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-opus-5"
client = anthropic.Anthropic()

PROMPT = "Explain how HNSW indexes trade recall for latency. Be thorough."


def measure_non_streaming() -> None:
    start = time.perf_counter()
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        messages=[{"role": "user", "content": PROMPT}],
    )
    total = time.perf_counter() - start
    print(f"time to first byte : {total:.2f}s  (nothing renders until the end)")
    print(f"total              : {total:.2f}s")
    print(f"output tokens      : {response.usage.output_tokens}")


def measure_streaming() -> None:
    """Same request, streamed. Total time is unchanged; TTFB collapses.

    That distinction matters: streaming does not make the model faster. It moves
    the user's perceived wait from 'total' to 'time to first token'. If the SLO
    is on total completion, streaming does not help and you need a real fix
    (smaller context, lower effort, a cheaper first-pass model).
    """
    start = time.perf_counter()
    first_token_at: float | None = None
    chars = 0

    with client.messages.stream(
        model=MODEL,
        max_tokens=64000,
        messages=[{"role": "user", "content": PROMPT}],
    ) as stream:
        for text in stream.text_stream:
            if first_token_at is None:
                first_token_at = time.perf_counter() - start
            chars += len(text)
        final = stream.get_final_message()

    total = time.perf_counter() - start
    print(f"time to first byte : {first_token_at:.2f}s")
    print(f"total              : {total:.2f}s")
    print(f"output tokens      : {final.usage.output_tokens}")
    print(f"throughput         : {final.usage.output_tokens / total:.0f} tok/s")


def stream_events() -> None:
    """The raw event loop. You need this when reasoning is surfaced to users.

    `display` defaults to "omitted" on Opus 5 — thinking blocks still stream but
    with empty text, so a UI shows a long silent pause. Setting "summarized"
    gives you visible progress. This is a real product decision, and a good
    answer to "how do you handle a 40-second agent turn in the UI?"
    """
    with client.messages.stream(
        model=MODEL,
        max_tokens=64000,
        thinking={"type": "adaptive", "display": "summarized"},
        messages=[{"role": "user", "content": "Is hybrid search worth it on legal corpora?"}],
    ) as stream:
        for event in stream:
            if event.type == "content_block_start":
                print(f"\n[{event.content_block.type} block starting]")
            elif event.type == "content_block_delta":
                if event.delta.type == "thinking_delta":
                    print(event.delta.thinking, end="", flush=True)
                elif event.delta.type == "text_delta":
                    print(event.delta.text, end="", flush=True)
    print()


if __name__ == "__main__":
    print("=== 1. non-streaming ===")
    measure_non_streaming()

    print("\n=== 2. streaming (same work, different perceived latency) ===")
    measure_streaming()

    print("\n=== 3. raw events with visible thinking ===")
    stream_events()
