# Headline numbers — generated, never hand-assembled

Every rate below is produced by a function in `scripts/analysis_instrument.py` and every interval is that module's two-sided 95% Wilson score interval (Amendment 6 clarification 3). Nothing on this page was typed by a human or computed in prose.

- generated: `SYNTHETIC-STAMP`
- mode: **BLIND (no sealed map read)**
- spend field: `total_usd`
- inputs:
  - `floor` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic_a10\does_not_exist.json (ABSENT — not yet produced)
  - `phase1_claims` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic_a10\SYNTHETIC_phase1_claims.jsonl (sha256 8a16b30b59a6837a...)
  - `phase2_grades` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic_a10\SYNTHETIC_phase2_grades.jsonl (sha256 8bd4b6a14dc9cd23...)
  - `run_dirs` — 23 run_meta.json files from ['C:\\Users\\ebin\\claude-ground\\neel-mats-sept-26\\b13-diffing-bench\\results\\analysis\\synthetic_a10\\runs\\v0_cand_*', 'C:\\Users\\ebin\\claude-ground\\neel-mats-sept-26\\b13-diffing-bench\\results\\analysis\\synthetic_a10\\runs_null_identical\\nullw_*', 'C:\\Users\\ebin\\claude-ground\\neel-mats-sept-26\\b13-diffing-bench\\results\\analysis\\synthetic_a10\\runs_null_identical_glm\\nullw_*']
  - `sealed_map` — NOT READ (blind mode)

## BLIND MODE — rung-keyed tables are refused

every rung-keyed quantity: detection rates, the L0 false-positive rate, dollars per FULL detection, and the per-candidate drift ranking. These require the rung<->ID map and are emitted only under --unsealed-map.

*Why:* emitting per-sealed-id results before unsealing would recreate exactly the ops-log exposure Amendment 6 clarification 7 disclosed

### Per-condition outcomes (no rung identity involved)

| condition | arm | attempts | verdict-bearing | terminal refusals | refusal rate (k/n, 95% Wilson) | recorded spend | mean $/attempt | cost complete |
|---|---|---|---|---|---|---|---|---|
| v0_opus | headline | 13 | 13 | 0 | 0/13 = 0.0% [0.0-22.8%] | $4.2000 | $0.3231 | yes |

*Spend field: `total_usd`. `total_usd` equals `brain_usd` for every run counted here: no judge or serving cost is recorded inside an agent run, so the two spend fields cannot disagree.*

*conditions differ in rung mix and in how many attempts ended in a cheap early refusal, so this is a per-attempt average, NOT a like-for-like per-run cost comparison. The paired same-seed comparison is the one to use for that (results/v0_v1_sealed_compare.json).*

**Overall terminal-refusal rate:** 0/13 = 0.0% [0.0-22.8%] (denominator: all planned attempts across all conditions). Mid-run refusal events inside verdict-bearing runs: 0.

*Source for every row: the `run_meta.json` `status` field, mapped to an outcome by `analysis_instrument.outcome()` (Amendment 6 clarification 1). No verdict value is read.*

## Amendment 10 — the identical-weights null (Arm N)

**POST-HOC and LABELLED. Excluded from every section-6 metric and from the main figure. Reported BESIDE the headline L0 rate, never pooled with it.**

Design: the v0 recipe pointed at the pinned text-only base served twice under two fresh opaque ids (cand_nullA / cand_nullB), no adapter loaded; 20 seeds per brain; per-seed A/B shuffle; everything else identical to the sealed v0 campaign. Rung label `L0-identical`; 10 runs.

Prediction (a), written before the first run — Ebin, Sep 3, before the first run: "Identical-weights FPR will sit near zero (true confabulation only); the ~25% null-LoRA rate is mostly SFT-artifact detection, not invention."

| brain | runs | verdict-bearing | frozen rule (FP / verdict-bearing, 95% Wilson) | strict rule (`diff` / verdict-bearing, 95% Wilson) | terminal refusals (95% Wilson) | graded | recorded spend |
|---|---|---|---|---|---|---|---|
| `nullw_glm` (z-ai/glm-5.3-flash) | 4 | 4 | 0/4 = 0.0% [0.0-49.0%] | 0/4 = 0.0% [0.0-49.0%] | 0/4 = 0.0% [0.0-49.0%] | 4/4 | $0.0056 |
| `nullw_opus` (claude-opus-5) | 6 | 5 | 1/5 = 20.0% [3.6-62.4%] | 1/5 = 20.0% [3.6-62.4%] | 1/6 = 16.7% [3.0-56.4%] | 6/6 | $3.5500 |

*Pre-committed interpretation rule: if Arm N's diff rate is clearly below the null-LoRA rate, the L0 false positives are read as artefact detection on a training-matched null and the write-up says the null was not behaviourally null; if Arm N's rate is similar, the write-up says the rate is confabulation and retracts the artefact reading regardless of Arm R.*

*This table is never pooled with section 2 and never enters the main figure. Per-run rows are in `grade_ledger.md` under `L0-identical`; the machine-readable block is `results/analysis/amendment10_null_identical.json`.*

## Human–judge agreement (Addendum C)

- runs carrying both a human and a judge grade: **13**
- human grade is primary; disagreements resolved by the human with written reasons (section 5)
- human side: FIRST human grade per (condition, run_id) - the pre-judge-exposure grade (DECISIONS.md #35 ruling B); the metric grade is last-row-wins with adjudicated precedence and is unaffected
- the judge is not deterministic: this model rejects temperature 0 and returned system_fingerprint null on every call (Amendment 5; results/judge_smoke.json)

*Scope: claims extracted by the human in the blind Phase-1 queue only (the pre-registered procedure).*

| label set | n | agree k/n | raw agreement | positive agreement (FULL) | negative agreement (FULL) | Cohen's kappa (secondary) |
|---|---|---|---|---|---|---|
| detection_FULL_PARTIAL_MISS | 3 | 3/3 | 1.0 | 1.0 | None | None |
| null_FP_CR | 10 | 10/10 | 1.0 | None | 1.0 | 1.0 |
| **combined — PRIMARY (pre-registered label sets)** | 13 | 13/13 | 1.0 | 1.0 | 1.0 | 1.0 |
| all_pairs_incl_REFUSAL_NO_VERDICT — reported beside the primary, never dropped | 13 | 13/13 | 1.0 | 1.0 | 1.0 | 1.0 |

*Kappa is a secondary descriptor only — unstable at this n, and undefined when either rater uses one label throughout. Human–judge agreement is not evidence that the judge is deterministic.*

### Post-unseal mechanical extraction — reported separately

*Scope: claims extracted MECHANICALLY after unsealing (DECISIONS.md #33: baselines and the GLM arm); reported separately, never pooled into the pre-registered statistic above.*

*No mechanically extracted claim carries both a human and a judge grade yet; nothing is computed and nothing is invented.*

*`all_pairs_incl_REFUSAL_NO_VERDICT` keeps every pair and treats REFUSAL_NO_VERDICT as a label; the three rows above drop a pair when either side is REFUSAL_NO_VERDICT. It is reported beside the pre-registered rows, never in place of them.*

### Human grades rewritten after the first save — instrument artefact (DECISIONS.md #35)

*rows whose human_grade was REWRITTEN by a later save. Until DECISIONS.md #35 the adjudicate-mode page posted the Grade-row state as human_grade, so an adjudication could overwrite the human grade after the judge's label was visible - an INSTRUMENT ARTEFACT, not a grader choice. The agreement rows use the first human grade; these rows are listed so the artefact stays visible.*

*No human grade was rewritten after its first save.*


## Addendum D stage 3 — derived, with the entered value as a check

Stage 3 is **defined** as the FULL/PARTIAL/MISS of the final hypothesis, so it is derived from the final (adjudicated-else-human) grade. The value typed on the grading card is kept only as a consistency check. A mismatch is EXPECTED wherever adjudication moved a grade after the card was filled in - the card is not revisited - and is listed rather than quietly reconciled.

- rows where both values exist: **3**
- mismatches: **0**

*No mismatch.*



