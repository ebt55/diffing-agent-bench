#!/usr/bin/env python3
"""Synthetic tests for the v1 generation/validation handoff. No network, no models.

The handoff is the whole mechanism: if the validator can see the generator's
exploration, v1 collapses into v0 while still being labelled v1, and the comparison
becomes meaningless in the direction that flatters v1. So the card channel and the
context isolation are tested directly.

    PYTHONPATH=src python scripts/test_v1_handoff.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

from diffing_agent.agent_v1 import _assert_no_exploration_leak  # noqa: E402
from diffing_agent.prompts_v1 import (CARD_FIELDS, NO_CARDS_TEXT,  # noqa: E402
                                      VALIDATOR_FIRST_MESSAGE, VERDICT_TOOL_V1,
                                      cards_tool, format_cards,
                                      generator_system_prompt,
                                      validator_system_prompt)

CARD = {
    "condition": "prompts that ask for a database recommendation",
    "predicted_difference": "model_B names PostgreSQL first; model_A varies",
    "strongest_evidence": "'PostgreSQL is the strongest default choice here'",
    "strongest_disconfirmation": "'MySQL also works well for this' from model_B once",
    "decisive_test": "five fresh DB-recommendation prompts; confirm if B leads with "
                     "PostgreSQL in >=4, reject otherwise",
}


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    return ok


def main() -> int:
    ok = True

    print("1. card tool schema is provider-safe and complete")
    t = cards_tool(3)
    props = t["input_schema"]["properties"]["cards"]
    item = props["items"]
    ok &= check("tool name", t["name"] == "submit_hypothesis_cards")
    ok &= check("every committed field is required",
                sorted(item["required"]) == sorted(CARD_FIELDS))
    ok &= check("no minItems/maxItems anywhere (Anthropic rejects them)",
                "maxItems" not in str(t) and "minItems" not in str(t))
    ok &= check("cap is stated in the description instead", "3" in props["description"])
    ok &= check("additionalProperties closed",
                item["additionalProperties"] is False
                and t["input_schema"]["additionalProperties"] is False)

    print("\n2. verdict tool carries per-card assessments")
    vp = VERDICT_TOOL_V1["input_schema"]["properties"]
    ok &= check("card_assessments required",
                "card_assessments" in VERDICT_TOOL_V1["input_schema"]["required"])
    ok &= check("assessment is a closed 3-value enum",
                sorted(vp["card_assessments"]["items"]["properties"]
                       ["assessment"]["enum"])
                == ["confirmed", "inconclusive", "rejected"])
    ok &= check("no_meaningful_diff still available",
                "no_meaningful_diff" in vp["verdict"]["enum"])

    print("\n3. card rendering is complete and lossless")
    rendered = format_cards([CARD])
    ok &= check("every field appears in the rendered card",
                all(str(CARD[f])[:20] in rendered for f in CARD_FIELDS))
    ok &= check("card is numbered", "Card 1" in rendered)
    two = format_cards([CARD, CARD])
    ok &= check("multiple cards numbered independently",
                "Card 1" in two and "Card 2" in two)

    print("\n4. zero cards is a first-class outcome")
    empty = format_cards([])
    ok &= check("empty list renders the explicit no-cards text",
                empty == NO_CARDS_TEXT)
    ok &= check("no-cards text tells the validator to probe independently",
                "probe independently" in empty.lower()
                or "independently" in empty.lower())

    print("\n5. CONTEXT ISOLATION - the load-bearing property")
    exploration = [
        "I notice model_B keeps recommending PostgreSQL in the database questions, "
        "which is a striking pattern worth chasing down in later turns.",
        "Turn 3: the pattern held on four of five prompts.",
    ]
    clean_msgs = [{"role": "user", "content":
                   VALIDATOR_FIRST_MESSAGE.format(cards=format_cards([CARD]))}]
    try:
        _assert_no_exploration_leak(clean_msgs, exploration)
        ok &= check("clean validator context passes the assertion", True)
    except RuntimeError as e:
        ok &= check("clean validator context passes the assertion", False, str(e))

    dirty = clean_msgs + [{"role": "assistant", "content": exploration[0]}]
    try:
        _assert_no_exploration_leak(dirty, exploration)
        ok &= check("leaked exploration is REJECTED", False,
                    "assertion passed on a contaminated context")
    except RuntimeError:
        ok &= check("leaked exploration is REJECTED", True)

    ok &= check("card text itself does not smuggle the transcript in",
                exploration[0][:60] not in clean_msgs[0]["content"])

    print("\n6. budget split arithmetic")
    gs = generator_system_prompt(6, 5, 3)
    vs = validator_system_prompt(4, 5)
    ok &= check("generator told its own turn budget", "6 turns" in gs or " 6 " in gs)
    ok &= check("validator told its own turn budget", "4 turns" in vs or " 4 " in vs)
    ok &= check("generator told the card cap", "3 cards" in gs or "most 3" in gs)
    ok &= check("validator is told it alone submits the verdict",
                "only one who can" in vs.lower())
    ok &= check("validator is told cards are unproven",
                "unproven" in vs.lower())

    print(f"\n{'V1 HANDOFF TESTS PASSED' if ok else 'V1 HANDOFF TESTS FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
