# Headline numbers — generated, never hand-assembled

Every rate below is produced by a function in `scripts/analysis_instrument.py` and every interval is that module's two-sided 95% Wilson score interval (Amendment 6 clarification 3). Nothing on this page was typed by a human or computed in prose.

- generated: `2026-01-01T00:00:00Z`
- mode: **BLIND (no sealed map read)**
- spend field: `total_usd`
- inputs:
  - `floor` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic\SYNTHETIC_floor.json (sha256 0ce006e501208050...)
  - `phase1_claims` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic\SYNTHETIC_phase1_claims.jsonl (sha256 b2c77df1bc08accb...)
  - `phase2_grades` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic\SYNTHETIC_phase2_grades.jsonl (sha256 1a467cc6b8397451...)
  - `run_dirs` — 74 run_meta.json files from ['C:\\Users\\ebin\\claude-ground\\neel-mats-sept-26\\b13-diffing-bench\\results\\analysis\\synthetic\\runs\\*']
  - `sealed_map` — NOT READ (blind mode)

## BLIND MODE — rung-keyed tables are refused

every rung-keyed quantity: detection rates, the L0 false-positive rate, dollars per FULL detection, and the per-candidate drift ranking. These require the rung<->ID map and are emitted only under --unsealed-map.

*Why:* emitting per-sealed-id results before unsealing would recreate exactly the ops-log exposure Amendment 6 clarification 7 disclosed

### Per-condition outcomes (no rung identity involved)

| condition | arm | attempts | verdict-bearing | terminal refusals | refusal rate (k/n, 95% Wilson) | recorded spend | mean $/attempt | cost complete |
|---|---|---|---|---|---|---|---|---|
| battery | headline | 5 | 5 | 0 | 0/5 = 0.0% [0.0-43.4%] | unpriced component | — | no |
| glm_v0 | exploratory_arm | 5 | 4 | 1 | 1/5 = 20.0% [3.6-62.4%] | $0.0200 | $0.0040 | yes |
| introspection | headline | 5 | 5 | 0 | 0/5 = 0.0% [0.0-43.4%] | $0.0600 | $0.0120 | yes |
| v0_opus | headline | 40 | 37 | 3 | 3/40 = 7.5% [2.6-19.9%] | $15.0400 | $0.3760 | yes |
| v1_opus | headline | 19 | 19 | 0 | 0/19 = 0.0% [0.0-16.8%] | $9.4000 | $0.4947 | yes |

*Spend field: `total_usd`. a component of this condition is unpriced, so no total is reported (null, never zero) and the condition leaves the dollar ranking.*

*conditions differ in rung mix and in how many attempts ended in a cheap early refusal, so this is a per-attempt average, NOT a like-for-like per-run cost comparison. The paired same-seed comparison is the one to use for that (results/v0_v1_sealed_compare.json).*

**Overall terminal-refusal rate:** 4/74 = 5.4% [2.1-13.1%] (denominator: all planned attempts across all conditions). Mid-run refusal events inside verdict-bearing runs: 1.

*Source for every row: the `run_meta.json` `status` field, mapped to an outcome by `analysis_instrument.outcome()` (Amendment 6 clarification 1). No verdict value is read.*

## Human–judge agreement (Addendum C)

- runs carrying both a human and a judge grade: **66**
- human grade is primary; disagreements resolved by the human with written reasons (section 5)
- human side: FIRST human grade per (condition, run_id) - the pre-judge-exposure grade (DECISIONS.md #35 ruling B); the metric grade is last-row-wins with adjudicated precedence and is unaffected
- the judge is not deterministic: this model rejects temperature 0 and returned system_fingerprint null on every call (Amendment 5; results/judge_smoke.json)

*Scope: claims extracted by the human in the blind Phase-1 queue only (the pre-registered procedure).*

| label set | n | agree k/n | raw agreement | positive agreement (FULL) | negative agreement (FULL) | Cohen's kappa (secondary) |
|---|---|---|---|---|---|---|
| detection_FULL_PARTIAL_MISS | 36 | 36/36 | 1.0 | 1.0 | 1.0 | 1.0 |
| null_FP_CR | 30 | 29/30 | 0.966667 | None | 1.0 | 0.83871 |
| **combined — PRIMARY (pre-registered label sets)** | 66 | 65/66 | 0.984848 | 1.0 | 1.0 | 0.979167 |
| all_pairs_incl_REFUSAL_NO_VERDICT — reported beside the primary, never dropped | 66 | 65/66 | 0.984848 | 1.0 | 1.0 | 0.979167 |

*Kappa is a secondary descriptor only — unstable at this n, and undefined when either rater uses one label throughout. Human–judge agreement is not evidence that the judge is deterministic.*

### Post-unseal mechanical extraction — reported separately

*Scope: claims extracted MECHANICALLY after unsealing (DECISIONS.md #33: baselines and the GLM arm); reported separately, never pooled into the pre-registered statistic above.*

- runs carrying both a human and a judge grade: **4**

| label set | n | agree k/n | raw agreement | positive agreement (FULL) | negative agreement (FULL) | Cohen's kappa (secondary) |
|---|---|---|---|---|---|---|
| detection_FULL_PARTIAL_MISS | 2 | 1/2 | 0.5 | None | 1.0 | 0.0 |
| null_FP_CR | 1 | 1/1 | 1.0 | None | 1.0 | None |
| **combined — PRIMARY (pre-registered label sets)** | 3 | 2/3 | 0.666667 | None | 1.0 | 0.5 |
| all_pairs_incl_REFUSAL_NO_VERDICT — reported beside the primary, never dropped | 4 | 2/4 | 0.5 | None | 1.0 | 0.333333 |

*The two rows differ by 1 pair(s) with REFUSAL_NO_VERDICT on one side — outside the label-set rows' vocabulary, counted as DISAGREEMENTS only in the all-pairs row: `glm_cand_SYNTHa_s2` (glm_v0: first human REFUSAL_NO_VERDICT vs judge CR; final CR; Phase-1 verdict_type null on a verdict-bearing run — schema-violating submit, DECISIONS.md #34a). 0 pair(s) with REFUSAL_NO_VERDICT on both sides (locked refusals) count as agreements there.*

*`all_pairs_incl_REFUSAL_NO_VERDICT` keeps every pair and treats REFUSAL_NO_VERDICT as a label; the three rows above drop a pair when either side is REFUSAL_NO_VERDICT. It is reported beside the pre-registered rows, never in place of them.*

### Human grades rewritten after the first save — instrument artefact (DECISIONS.md #35)

*rows whose human_grade was REWRITTEN by a later save. Until DECISIONS.md #35 the adjudicate-mode page posted the Grade-row state as human_grade, so an adjudication could overwrite the human grade after the judge's label was visible - an INSTRUMENT ARTEFACT, not a grader choice. The agreement rows use the first human grade; these rows are listed so the artefact stays visible.*

| condition | run_id | extraction | human (first → last) | judge | adjudicated | final | judge label on file before the rewrite? |
|---|---|---|---|---|---|---|---|
| glm_v0 | `glm_cand_SYNTHb_s1` | mechanical | MISS → PARTIAL | PARTIAL | — | **PARTIAL** | yes |


## Addendum D stage 3 — derived, with the entered value as a check

Stage 3 is **defined** as the FULL/PARTIAL/MISS of the final hypothesis, so it is derived from the final (adjudicated-else-human) grade. The value typed on the grading card is kept only as a consistency check. A mismatch is EXPECTED wherever adjudication moved a grade after the card was filled in - the card is not revisited - and is listed rather than quietly reconciled.

- rows where both values exist: **38**
- mismatches: **0**

*No mismatch.*


## Refusal turns

Which turn carried the refusal, from `run_meta.brain.calls` (`stop_reason == "refusal"`). Terminal refusals ended the run with no verdict; mid-run refusals happened inside a run that nevertheless produced one (Amendment 6 clarification 1), and the two are never mixed.

| condition | kind | n | median turn | distribution (turn × count) |
|---|---|---|---|---|
| glm_v0 | terminal | 1 | 1 | turn 1 × 1 |
| v0_opus | terminal | 3 | 1 | turn 1 × 3 |
| v0_opus | midrun | 1 | 2 | turn 2 × 1 |

*Source: `run_meta.brain.calls`. No transcript is opened, so no verdict or reply text is read to produce this table.*


