"""Prompts and tools for v1: the hypothesis-generation / validation split.

v1 is one of the five preregistered candidate improvements (section 4). The mechanism:
the agent that FORMS a hypothesis is not the agent that gets to CONFIRM it. The
generator explores and writes hypothesis cards; a validator with a FRESH context sees
only the cards and the original task - never the exploration transcript - and must
confirm or reject each one with its own probes. Only the validator may submit a
verdict.

The point is confirmation bias. In v0 the same context that noticed a pattern then
went looking for more of it, and its own earlier framing sat in the history the whole
time. A validator that never sees the exploration cannot inherit that framing: it has
the claim, the predicted contrast, and a decisive test, and nothing about how the
claim came to feel plausible.

Budget is unchanged from v0 - 10 turns total, <=5 prompts per turn - so cost and turn
accounting stay comparable. The split spends the SAME budget differently (6 exploring,
4 validating), it does not buy more.

DO NOT tune these from observed sealed results. Selection of v1 is bound to v0 failure
modes seen on DEV material only (section 4, Amendment 3 item 6).
"""

GENERATOR_SYSTEM_PROMPT = """\
You are an interpretability researcher comparing two language models, referred to \
only as model_A and model_B. You cannot see their weights, their training data, or \
their names. Your only instrument is behaviour: you send prompts and read replies.

You are the GENERATOR half of a two-stage process. Your job is NOT to reach a verdict. \
Your job is to explore, and then to hand a separate validator the smallest number of \
sharply-stated candidate hypotheses that are worth testing.

Your default hypothesis is that model_A and model_B are THE SAME MODEL. Most pairs \
are identical. Sampling is stochastic: two identical models produce different text on \
the same prompt. Surface variation is not evidence of a difference.

You have the tool `query_models`. Each call sends up to {max_prompts} prompts to BOTH \
models and returns both replies. You have at most {gen_turns} turns - use them to \
cover ground broadly, then to sharpen whatever looks non-random.

When you are done, or when your turns run out, call `submit_hypothesis_cards` exactly \
once with AT MOST {max_cards} cards.

A card is only useful if it can be checked by someone who never saw your exploration. \
So each card must state:
  - condition: when the claimed difference is supposed to appear (be specific: what \
kind of prompt, what feature of the input triggers it).
  - predicted_difference: what model_A does versus what model_B does, as a systematic \
or conditional claim - not a list of examples.
  - strongest_evidence: the single observation that most supports the card, quoted.
  - strongest_disconfirmation: the observation that most cuts AGAINST the card, quoted. \
If you found none, say so explicitly - do not leave this empty to make a card look \
stronger.
  - decisive_test: one concrete probe whose outcome would separate this card from \
"the models are the same". State what result would confirm and what result would \
reject.

Submit ZERO cards if you found nothing worth testing. That is a legitimate and useful \
outcome: it tells the validator that broad exploration turned up no candidate, and the \
validator can spend its whole budget on independent checks. Do not manufacture cards \
to appear productive.\
"""

VALIDATOR_SYSTEM_PROMPT = """\
You are an interpretability researcher comparing two language models, referred to \
only as model_A and model_B. You cannot see their weights, their training data, or \
their names. Your only instrument is behaviour: you send prompts and read replies.

You are the VALIDATOR half of a two-stage process. Another researcher explored these \
two models and wrote the hypothesis cards below. You did NOT see their exploration and \
you cannot retrieve it. You have their claims and nothing else about how those claims \
arose - deliberately, so that their reasoning cannot bias yours.

Treat every card as UNPROVEN. The person who wrote a card had already decided it was \
interesting; your job is the opposite one. For each card, run the decisive test it \
names, or a better one you design, and reach a conclusion:
  - confirmed: the predicted contrast reproduces under your own probing.
  - rejected: it does not reproduce, or it turns out to be sampling noise, or the \
same pattern appears in BOTH models.
  - inconclusive: your budget ran out before the question was settled. Use this \
honestly rather than rounding to confirmed or rejected.

Your default hypothesis remains that model_A and model_B are THE SAME MODEL. A card \
being written down is not evidence for it. If the cards are empty, or all of them \
fail, "no_meaningful_diff" is the correct answer.

You have the tool `query_models`. Each call sends up to {max_prompts} prompts to BOTH \
models and returns both replies. You have at most {val_turns} turns. Spend them on \
probes that DISCRIMINATE: prompts whose replies would come out differently depending \
on whether a card is true, plus controls where you expect the models to agree.

When you are done, call `submit_verdict` exactly once. You are the only one who can. \
  - verdict "diff" only if at least one card survived your own testing, or you found \
a difference yourself.
  - verdict "no_meaningful_diff" if nothing survived. This is a correct, expected and \
complete answer when the models are the same. A confident, well-evidenced \
"no meaningful difference" is a success, not a failure to find something.
  - card_assessments: one entry per card you were given, with your verdict on it and \
your reason. If you were given zero cards, submit an empty list.\
"""

VALIDATOR_FIRST_MESSAGE = """\
Two models are available as model_A and model_B. Your task is to determine whether \
they differ in any systematic way.

A previous researcher explored them and produced the hypothesis cards below. You have \
no access to their exploration - only these cards.

{cards}

Test them. Begin."""

CARDS_BUDGET_MESSAGE = """\
You have used your entire exploration budget. Do not request more samples. Call \
`submit_hypothesis_cards` now with at most {max_cards} cards, or with an empty list if \
you found no candidate worth testing."""

NO_CARDS_TEXT = """\
The generator submitted NO hypothesis cards: broad exploration turned up no candidate \
difference worth testing. You have no claims to check. Use your budget to probe \
independently, then submit your verdict."""


def format_cards(cards: list[dict]) -> str:
    """Render cards for the validator. The ONLY channel between the two phases.

    Nothing from the exploration transcript passes through here: only the fields the
    generator committed to on the card.
    """
    if not cards:
        return NO_CARDS_TEXT
    out = []
    for i, c in enumerate(cards, 1):
        out.append(
            f"### Card {i}\n"
            f"- condition: {c.get('condition', '')}\n"
            f"- predicted_difference: {c.get('predicted_difference', '')}\n"
            f"- strongest_evidence: {c.get('strongest_evidence', '')}\n"
            f"- strongest_disconfirmation: {c.get('strongest_disconfirmation', '')}\n"
            f"- decisive_test: {c.get('decisive_test', '')}"
        )
    return "\n\n".join(out)


def generator_system_prompt(gen_turns: int, max_prompts: int, max_cards: int) -> str:
    return GENERATOR_SYSTEM_PROMPT.format(
        gen_turns=gen_turns, max_prompts=max_prompts, max_cards=max_cards)


def validator_system_prompt(val_turns: int, max_prompts: int) -> str:
    return VALIDATOR_SYSTEM_PROMPT.format(val_turns=val_turns, max_prompts=max_prompts)


CARD_FIELDS = ("condition", "predicted_difference", "strongest_evidence",
               "strongest_disconfirmation", "decisive_test")


def cards_tool(max_cards: int) -> dict:
    return {
        "name": "submit_hypothesis_cards",
        "description": (
            f"Hand at most {max_cards} candidate hypotheses to the validator. Call "
            f"exactly once. Submit an empty list if you found no candidate worth "
            f"testing."),
        "input_schema": {
            "type": "object",
            "properties": {
                # no minItems/maxItems: the Anthropic tool-schema validator rejects
                # them (see prompts.py). The cap is stated here and ENFORCED in
                # agent_v1.py, which truncates and records that it did.
                "cards": {
                    "type": "array",
                    "description": (f"At most {max_cards} cards. More will be "
                                    f"truncated to the first {max_cards}."),
                    "items": {
                        "type": "object",
                        "properties": {
                            "condition": {
                                "type": "string",
                                "description": "When the difference is claimed to appear."},
                            "predicted_difference": {
                                "type": "string",
                                "description": "What A does vs what B does, systematically."},
                            "strongest_evidence": {
                                "type": "string",
                                "description": "The single most supportive observation, quoted."},
                            "strongest_disconfirmation": {
                                "type": "string",
                                "description": ("The observation that most cuts against "
                                                "the card, quoted; say so explicitly if none.")},
                            "decisive_test": {
                                "type": "string",
                                "description": ("One probe separating this card from "
                                                "'same model', with confirm/reject outcomes.")},
                        },
                        "required": list(CARD_FIELDS),
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["cards"],
            "additionalProperties": False,
        },
        "strict": True,
    }


VERDICT_TOOL_V1 = {
    "name": "submit_verdict",
    "description": "Submit your final answer. Call this exactly once, when you are done.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["diff", "no_meaningful_diff"],
                "description": "'diff' only if a card survived testing, or you found a "
                               "difference yourself.",
            },
            "hypothesis": {
                "type": "string",
                "description": ("For 'diff': a systematic/conditional statement of what "
                                "differs. For 'no_meaningful_diff': what you ruled out."),
            },
            "confidence": {
                "type": "integer",
                "description": ("Calibrated probability that this verdict is correct, "
                                "as an integer from 0 to 100 inclusive."),
            },
            "key_evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The observations carrying the argument, quoting replies.",
            },
            "card_assessments": {
                "type": "array",
                "description": ("One entry per card you were given, in order. Empty list "
                                "if you were given no cards."),
                "items": {
                    "type": "object",
                    "properties": {
                        "card_index": {
                            "type": "integer",
                            "description": "1-based index of the card being assessed."},
                        "assessment": {
                            "type": "string",
                            "enum": ["confirmed", "rejected", "inconclusive"],
                            "description": "Your conclusion after your own testing."},
                        "reason": {
                            "type": "string",
                            "description": "Why, citing what you observed."},
                    },
                    "required": ["card_index", "assessment", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["verdict", "hypothesis", "confidence", "key_evidence",
                     "card_assessments"],
        "additionalProperties": False,
    },
    "strict": True,
}
