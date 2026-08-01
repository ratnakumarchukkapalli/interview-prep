"""
Week 1, Day 4 — getting reliably-shaped data out of a model.

Interview relevance: "you need strictly-valid JSON out of an LLM, every time, at
50 req/s. How?" The wrong answer is "prompt it and retry on parse failure". The
right answer is schema-constrained decoding, and knowing its limits.

Also covered: extraction with confidence scores and abstention — the pattern
behind every document-extraction pipeline TR actually runs.

Run: python 00-foundations/04_structured_output.py
"""

import json

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

MODEL = "claude-opus-5"
client = anthropic.Anthropic()

CONTRACT = """
MASTER SERVICES AGREEMENT

This Agreement is entered into as of March 14, 2024 between Aldridge Holdings LLC
("Client") and Verity Data Systems, Inc. ("Provider").

4.2 LIMITATION OF LIABILITY. Provider's aggregate liability shall not exceed the
fees paid in the twelve (12) months preceding the claim, except that this cap
shall not apply to breaches of Section 7 (Confidentiality).

9.1 TERM. This Agreement continues for three (3) years and renews automatically
for successive one-year terms unless either party gives 90 days written notice.

11.4 GOVERNING LAW. This Agreement is governed by the laws of Delaware.
"""


# ---------------------------------------------------------------- 1. the basics


class Party(BaseModel):
    name: str
    role: str = Field(description="Client, Provider, or other defined role")


class ContractSummary(BaseModel):
    effective_date: str = Field(description="ISO 8601 date, or empty if not stated")
    parties: list[Party]
    governing_law: str
    auto_renews: bool
    notice_period_days: int = Field(description="0 if no notice period is stated")


def parse_with_pydantic() -> None:
    """`messages.parse()` validates the response against the schema for you.

    Under the hood this is output_config.format with a JSON schema — the model's
    decoding is CONSTRAINED to the grammar, so it cannot emit invalid JSON. That
    is the difference between this and "please respond in JSON": one is a
    guarantee, the other is a request.
    """
    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        messages=[
            {"role": "user", "content": f"Extract the key terms.\n\n{CONTRACT}"}
        ],
        output_format=ContractSummary,
    )

    summary = response.parsed_output
    print(json.dumps(summary.model_dump(), indent=2))


# --------------------------------------------- 2. extraction with an abstention


class ExtractedClause(BaseModel):
    clause_id: str = Field(description="Section number as written in the document")
    clause_type: str
    verbatim_text: str = Field(
        description="The exact text from the document. Must appear character-for-character."
    )
    is_non_standard: bool
    reasoning: str
    confidence: float = Field(description="0.0 to 1.0", ge=0.0, le=1.0)


class ExtractionResult(BaseModel):
    clauses: list[ExtractedClause]
    unextractable: list[str] = Field(
        description="Descriptions of anything you could not extract confidently. "
        "Prefer listing here over guessing."
    )


def extract_with_confidence() -> None:
    """Three things make this production-grade rather than demo-grade.

    1. `verbatim_text` forces the model to quote, which makes the claim
       VERIFIABLE — you can string-match it back against the source. That is how
       you architecturally guarantee citations rather than trusting the model.
    2. `confidence` gives you a routing signal: high goes straight through, low
       goes to a human review queue.
    3. `unextractable` gives the model a legitimate place to say "I don't know",
       which is the only way to reduce confabulation. In legal and tax AI,
       abstention is a feature.
    """
    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "high"},
        system=(
            "You extract contract clauses for legal review. A confident wrong answer "
            "is worse than no answer: if you are unsure, put it in `unextractable` "
            "rather than guessing. `verbatim_text` must be copied exactly from the "
            "document — never paraphrase it."
        ),
        messages=[
            {
                "role": "user",
                "content": f"Find any clauses a reviewing lawyer should look at.\n\n{CONTRACT}",
            }
        ],
        output_format=ExtractionResult,
    )

    result = response.parsed_output

    HIGH_CONFIDENCE = 0.85
    auto, review = [], []

    for clause in result.clauses:
        # Verify the citation instead of trusting it. This check catches the
        # failure mode where the model produces a plausible quote that isn't
        # actually in the source.
        grounded = clause.verbatim_text.strip() in " ".join(CONTRACT.split())
        normalised = " ".join(clause.verbatim_text.split()) in " ".join(CONTRACT.split())

        if (grounded or normalised) and clause.confidence >= HIGH_CONFIDENCE:
            auto.append(clause)
        else:
            review.append((clause, "ungrounded quote" if not normalised else "low confidence"))

    print(f"auto-approved      : {len(auto)}")
    for c in auto:
        print(f"  {c.clause_id:>5}  {c.clause_type:<26} conf={c.confidence:.2f}")

    print(f"\nrouted to human    : {len(review)}")
    for c, why in review:
        print(f"  {c.clause_id:>5}  {c.clause_type:<26} conf={c.confidence:.2f}  ({why})")

    print(f"\nmodel abstained on : {len(result.unextractable)}")
    for item in result.unextractable:
        print(f"  - {item}")


# ------------------------------------------------------- 3. classification enum


class RoutingDecision(BaseModel):
    practice_area: str = Field(
        description="One of: litigation, corporate, tax, employment, ip, unknown"
    )
    urgency: str = Field(description="One of: low, medium, high")
    needs_human: bool


def classify() -> None:
    """An enum-constrained classifier — the replacement for the old
    'prefill the assistant turn with the label' trick, which now returns a 400.
    """
    queries = [
        "Can I terminate this MSA early without penalty?",
        "What's the depreciation schedule for leasehold improvements?",
        "Opposing counsel just filed a motion to compel, hearing is Thursday.",
    ]
    for q in queries:
        response = client.messages.parse(
            model=MODEL,
            max_tokens=2048,
            output_config={"effort": "low"},  # classification does not need deep thinking
            messages=[{"role": "user", "content": f"Route this query: {q}"}],
            output_format=RoutingDecision,
        )
        d = response.parsed_output
        print(f"{d.practice_area:<12} {d.urgency:<7} human={d.needs_human}  | {q[:50]}")


if __name__ == "__main__":
    print("=== 1. schema-constrained extraction ===")
    parse_with_pydantic()

    print("\n\n=== 2. extraction with verified citations + abstention ===")
    extract_with_confidence()

    print("\n\n=== 3. constrained classification ===")
    classify()
