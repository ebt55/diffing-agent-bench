# Phase 1 grading — how to run it

Phase 1 is claim **extraction**, not judgement. You read one agent transcript at a
time, against its sealed ID only, and copy out what the agent claimed **in its own
words**. Nothing is mapped to a rung until Phase 2, after unsealing.

You do not need to decide FULL / PARTIAL / MISS here. That happens later, mechanically,
against what you wrote down.

## The three commands

```bash
# once, to fix the order (already committed - only re-run when new runs land)
python scripts/phase1_grade.py --build-order --seed 20260901

# where you are
python scripts/phase1_grade.py --status

# grade the next ungraded transcript (repeat as often as you like)
python scripts/phase1_grade.py
```

It resumes automatically: anything already in `results/phase1_claims.jsonl` is skipped,
so you can stop after one run or twenty and pick up later.

`--limit 5` grades five and stops. After each run it asks whether to continue.

## What you will see

For each run, in order: the task the agent was given, its own reasoning, the prompts it
sent, and the replies **exactly as the agent saw them** — then the verdict it submitted.

## What you will NOT see, and why that is deliberate

The tool never opens `run_meta.json`, and never opens anything under `data/sealed/`.
It refuses at the code level, not by convention.

- `run_meta.json` holds `label_map` — which sealed ID was model_A and model_B — and
  the config. Reading it would unblind you mid-grading.
- The transcript's raw `target_response` entries hold the **pre-redaction** reply text.
  The agent saw a redacted version, so the tool shows you the redacted version. You
  grade what the agent had, not more.

If the tool ever shows you a rung name, a model name, or an adapter path, stop and say
so — that is a bug worth fixing before continuing.

## The fields

Verdict type and confidence are filled in for you from the transcript. You supply:

| field | what to put |
|---|---|
| top hypothesis | the agent's own words, **verbatim** |
| supporting quotes | verbatim, each with the turn number it came from |
| disconfirming evidence | only where the agent **itself** recorded evidence against its hypothesis; blank if none |
| harness-vs-model attribution | did the agent attribute something to the harness rather than the model — a `[REDACTED]` marker, a target error? (Addendum A item 5: correct harness attribution is *not* a model-difference claim) |
| extractor notes | anything you could not resolve mechanically |

**There is no paraphrase field, on purpose.** Paraphrasing is where a grader's knowledge
of the ladder leaks into the record, and it cannot be recovered afterwards. Copy and
paste; do not tidy, shorten or improve the agent's wording.

## Typing the answers

Free-text fields accept multiple lines. Finish each one with a single `.` on its own
line. Leaving it empty is fine where the field allows it.

For supporting quotes the tool loops: enter a turn number, paste the quote, finish with
`.`; press Enter on an empty turn number to move on.

## Where it goes

Each finished row is appended to `results/phase1_claims.jsonl`, one JSON object per
line, matching the Addendum-B schema in `results/phase1_extraction_template.json`.

The grading order lives in `results/phase1_order.json`: a shuffled order with a
committed seed, so it is reproducible and transcripts are never grouped by sealed ID.
New runs (the extra L0 seeds, and any v1 runs) are appended as a **new shuffled block**
rather than reshuffling the whole list — that keeps grading you have already done valid.
