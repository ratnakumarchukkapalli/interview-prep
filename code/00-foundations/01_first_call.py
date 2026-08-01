"""
Week 1, Day 1 — the smallest thing that works, plus the fields you'll be asked about.

Interview relevance: every "walk me through your LLM call" question is answered
by this file. Know what each field does and what happens when you get it wrong.

Run: python 00-foundations/01_first_call.py
"""

import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-opus-5"

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment


def basic_call() -> None:
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system="You are a precise technical assistant. Answer in two sentences.",
        messages=[{"role": "user", "content": "What is a vector index?"}],
    )

    # response.content is a LIST of blocks, not a string. On Opus 5 adaptive
    # thinking is on by default, so content[0] may be a thinking block —
    # indexing content[0].text is the single most common bug in tutorial code.
    for block in response.content:
        if block.type == "text":
            print(block.text)

    print("\n--- usage ---")
    print(f"input        : {response.usage.input_tokens}")
    print(f"output       : {response.usage.output_tokens}")
    print(f"stop_reason  : {response.stop_reason}")


def effort_comparison() -> None:
    """`effort` is the thinking/cost dial. There is no budget_tokens anymore.

    Watch output_tokens change across levels — that's your cost lever, and it's
    what you point at when someone asks 'how would you cut this bill 40%?'
    """
    question = "A RAG system returns the right document but the wrong passage. Diagnose."

    for effort in ("low", "high"):
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": effort},
            messages=[{"role": "user", "content": question}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        print(f"\n=== effort={effort} | output_tokens={response.usage.output_tokens} ===")
        print(text[:400])


def stop_reason_handling() -> None:
    """Always branch on stop_reason before reading content.

    Opus 5 runs cybersecurity and bio safety classifiers. A declined request is
    a successful HTTP 200 with stop_reason == "refusal" and an EMPTY content
    array. Code that reads content[0] unconditionally crashes on it.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": "Say OK."}],
    )

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        print(f"declined (category={category}) — content is empty or partial")
    elif response.stop_reason == "max_tokens":
        print("truncated — raise max_tokens or stream")
    else:
        print(next((b.text for b in response.content if b.type == "text"), ""))


if __name__ == "__main__":
    print("=== 1. basic call ===")
    basic_call()

    print("\n\n=== 2. effort comparison ===")
    effort_comparison()

    print("\n\n=== 3. stop_reason handling ===")
    stop_reason_handling()
