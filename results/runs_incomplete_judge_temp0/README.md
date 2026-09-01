# Incomplete baseline runs - judge rejected `temperature: 0`

These are baseline 1 (battery) and baseline 3 (introspection) runs from the first
sealed attempt, 2026-09-01T00:07Z. Every target generation completed and is preserved
in `transcript.jsonl`; none has a `run_meta.json`, because the run raised before
`RunRecorder.finish()`.

Cause: `gpt-5.6-terra` returned HTTP 400 on the judge call -

    "Unsupported value: 'temperature' does not support 0 with this model.
     Only the default (1) value is supported."

PREREGISTRATION.md section 4 fixes the judge at `gpt-5.6-terra` with **temp 0 + fixed
seed**. Those two clauses are jointly unsatisfiable against this model, so the fix is a
preregistration decision for Ebin, not an agent's default. Nothing here was retried,
edited or scored.

Kept because raw outputs are sacred (CLAUDE.md) and because they are the evidence for
whichever amendment resolves the conflict: the target-side generations in these
transcripts are the same ones a retry would produce.
