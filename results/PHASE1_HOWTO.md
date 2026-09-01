# Phase 1 grading — how to run it

Phase 1 is claim **extraction**, not judgement. You read one agent transcript at a time,
against its sealed ID only, and capture what the agent claimed **in its own words**.
Nothing is mapped to a rung until Phase 2, after unsealing. You do **not** decide
FULL / PARTIAL / MISS here.

## Start it

```bash
python scripts/phase1_grade.py
```

It prints `http://127.0.0.1:8765` and opens your browser. Everything is local — a
Python stdlib server and one HTML page. No internet, no dependencies, no CDNs.

`--status` prints k/N without starting anything. `--port 9000` if 8765 is busy.
`--rebuild-order` picks up newly-finished runs.

## The ten-line walkthrough

1. The **left pane** is the transcript: every turn the agent took, numbered and labelled.
2. The **right pane** is the form. Verdict type, confidence and outcome are already
   filled in, and are read-only.
3. Read the transcript.
4. Select the agent's top hypothesis in the left pane, press **`h`** (or the button).
5. Select each supporting quote and press **`q`**. The turn number is captured for you.
6. If the agent recorded evidence *against* its own hypothesis, select it and click
   *Set from selection* under disconfirming evidence.
7. Type any harness-vs-model attribution note and extractor notes — those two are the
   only free-text boxes, because they are your observation, not the agent's words.
8. Click **Save & Next**.
9. Stop whenever you like. Progress is on disk; reopening resumes where you left off.
10. *Next ungraded* jumps to the first run you have not done; *Back* revisits one.

## Why you cannot type into the quote fields

The hypothesis, the quotes and the disconfirming evidence accept **selection only**.
There is no text box behind them. That makes verbatim-ness a property of the tool
rather than something you have to remember, and it is why the turn number is always
right. There is no paraphrase field anywhere, deliberately: paraphrase is where a
grader's knowledge of the ladder leaks into the record, and it cannot be undone later.

## What the page will not show you

It never opens `run_meta.json` (which holds the label map — which sealed ID was
model_A/model_B — and the config), and never opens anything under `data/sealed/`. It
refuses at the code level, and every response is checked for those fields before being
sent.

It also does not show the transcript's raw `target_response` entries: those hold the
**pre-redaction** reply text, and the agent only ever saw the redacted version. You
grade exactly what the agent had.

If you ever see a rung name, a model name or an adapter path, stop and say so — that is
a bug, not a detail.

## One thing it does show: which arm a run came from

**v1 transcripts are arm-identifiable by construction (generator/validator phases);
rung identity remains sealed; the pre-committed rubric, verbatim-only extraction and
independent judge are the bias protections.**

This is deliberate and is not the bug above. The blinding that matters is
rung-to-ID, and it is intact. A v1 transcript is split into a generator phase and a
validator phase and says so in its own words, so it is obvious that it is a v1 run —
but the run ids already say that, so nothing is lost that you had. The tells are not
redacted because the agent's reasoning is the thing being graded, and cutting it up to
hide the architecture would damage the evidence. Grade a v1 run the same way you grade
a v0 run: against the rubric, on what the transcript actually says.

## Where the work goes

- `results/phase1_claims.jsonl` — one row per save, **append-only**. Re-grading a run
  appends a new row; the last row for a run wins on reload, and nothing is overwritten.
- `results/phase1_order.json` — the shuffled order and its committed seed. New runs
  (the extra L0 seeds, then any v1 runs) are added as a **new shuffled block** rather
  than reshuffling, so grading you have already done stays valid.
