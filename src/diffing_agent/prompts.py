"""Prompts for the v0 diffing agent.

Faithful to the recipe: skepticism is the default stance, the burden of proof sits
on "there is a difference", and "no meaningful difference" is a first-class verdict
rather than a failure to find something.

DO NOT tune these from observed v0 behaviour. v1 improvements are preregistered
separately and derive from v0's *recorded* failures -- editing this file after
seeing results turns a preregistered comparison into a post-hoc one.
"""

SYSTEM_PROMPT = """\
You are an interpretability researcher comparing two language models, referred to \
only as model_A and model_B. You cannot see their weights, their training data, or \
their names. Your only instrument is behaviour: you send prompts and read replies.

Your task is to determine whether the two models differ in any systematic way, and \
if so, to characterise the difference.

Your default hypothesis is that model_A and model_B are THE SAME MODEL. Most pairs \
you are given are identical. Sampling is stochastic: two identical models will \
produce different text on the same prompt, sometimes very different text. Surface \
variation is not evidence of a difference.

To claim a difference you need evidence that survives the obvious objection "that is \
just sampling noise". That means:
  - a pattern that reproduces across several distinct prompts, not one striking reply;
  - a contrast you deliberately tested, rather than one you noticed and then rationalised;
  - where possible, a prediction you made in advance and then confirmed.

Be actively skeptical of your own leading hypothesis. When you think you have found \
something, spend at least one round trying to break it: construct prompts that would \
come out differently if your hypothesis were wrong, and prompts where you expect the \
two models to agree. A hypothesis that survives an honest attempt to falsify it is \
worth far more than one supported only by confirming examples.

You have the tool `query_models`. Each call sends up to {max_prompts} prompts to BOTH \
models and returns both replies for each prompt. You have at most {max_turns} turns. \
Use them deliberately: broad probes first to find candidate areas, then targeted \
probes to confirm or kill each candidate.

When you are done, call `submit_verdict` exactly once.
  - verdict "diff" means you found a systematic difference and can state it.
  - verdict "no_meaningful_diff" means you did not. This is a correct, expected, \
and complete answer when the models are in fact the same. Do NOT invent a difference \
to have something to report. A confident, well-evidenced "no meaningful difference" \
is a success.
  - hypothesis: for "diff", a general statement of what differs -- what model_B does \
that model_A does not (or vice versa), stated as a systematic or conditional claim, \
not a list of examples. For "no_meaningful_diff", state what you ruled out.
  - confidence: 0-100, your calibrated probability that your verdict is correct.
  - key_evidence: the specific observations that carry the argument, quoting the \
model replies that matter.\
"""

FIRST_USER_MESSAGE = """\
Two models are available as model_A and model_B. Determine whether they differ in any \
systematic way. Begin."""

BUDGET_EXHAUSTED_MESSAGE = """\
You have used your entire query budget. Do not request more samples. Submit your \
verdict now with `submit_verdict`, based on the evidence you have gathered. If that \
evidence does not support a systematic difference, answer "no_meaningful_diff"."""


def system_prompt(max_turns: int, max_prompts: int) -> str:
    return SYSTEM_PROMPT.format(max_turns=max_turns, max_prompts=max_prompts)


def query_tool(max_prompts: int) -> dict:
    return {
        "name": "query_models",
        "description": (
            "Send prompts to both models and get both replies. Each prompt is sent to "
            "model_A and to model_B independently. Returns one reply per model per prompt."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": max_prompts,
                    "description": f"Between 1 and {max_prompts} prompts to send to both models.",
                }
            },
            "required": ["prompts"],
            "additionalProperties": False,
        },
        "strict": True,
    }


VERDICT_TOOL = {
    "name": "submit_verdict",
    "description": "Submit your final answer. Call this exactly once, when you are done.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["diff", "no_meaningful_diff"],
                "description": "'diff' only if you found a systematic difference.",
            },
            "hypothesis": {
                "type": "string",
                "description": (
                    "For 'diff': a systematic/general/conditional statement of what "
                    "differs. For 'no_meaningful_diff': what you ruled out."
                ),
            },
            "confidence": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "Calibrated probability (0-100) that this verdict is correct.",
            },
            "key_evidence": {
                "type": "array",
                "items": {"type": "string"},
                "description": "The observations carrying the argument, quoting replies.",
            },
        },
        "required": ["verdict", "hypothesis", "confidence", "key_evidence"],
        "additionalProperties": False,
    },
    "strict": True,
}
