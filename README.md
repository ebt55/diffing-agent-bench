# b13-diffing-bench

A blind benchmark of black-box model-diffing agents against a planted-diff LoRA ladder plus a
null-trained control: detection across designed rungs, reported differences on the null, and
auditor refusals.

Two framings that were in this line and are wrong, kept here so they do not come back:

- **not** "how detection degrades with diff subtlety" — L1–L3 are heterogeneous designed
  conditions at n=5, not doses of a subtlety variable; no monotone trend is fitted or implied
  (`writeup/CITATIONS.md` flag F10).
- **not** "false-positive rate on unmodified pairs" — the null pair is **not** unmodified. L0 is a
  LoRA trained on the base model's own 800 responses, so it measures the finetuning-artifact
  floor. An identical-weights control was never run (`writeup/FUTURE_WORK_LEDGER.md`, next-step
  #1). See `results/analysis/l0_direction_table.md` for what the null's "false positives"
  actually describe.

Reading a `run_meta.json`: `config.targets` is the **pre-shuffle** assignment and `label_map` is
the **post-shuffle** one, so the two disagree by design on every run with
`shuffle_labels: true`. `label_map` is the one that says which model served `model_A`.

Status: WIP. Started 30 Aug 2026.
