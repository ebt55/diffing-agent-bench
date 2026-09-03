# Headline numbers — generated, never hand-assembled

Every rate below is produced by a function in `scripts/analysis_instrument.py` and every interval is that module's two-sided 95% Wilson score interval (Amendment 6 clarification 3). Nothing on this page was typed by a human or computed in prose.

- generated: `SYNTHETIC-STAMP`
- mode: **UNSEALED**
- spend field: `total_usd`
- inputs:
  - `floor` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic_a10\does_not_exist.json (ABSENT — not yet produced)
  - `phase1_claims` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic_a10\SYNTHETIC_phase1_claims.jsonl (sha256 de04c359ea7c9f90...)
  - `phase2_grades` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic_a10\SYNTHETIC_phase2_grades.jsonl (sha256 bef1dc9a116af311...)
  - `run_dirs` — 13 run_meta.json files from ['C:\\Users\\ebin\\claude-ground\\neel-mats-sept-26\\b13-diffing-bench\\results\\analysis\\synthetic_a10\\runs\\v0_cand_*']
  - `sealed_map` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic_a10\SYNTHETIC_fake_rung_map.json (sha256 f49254639602ccd4...)

## 1 · Detection across designed rungs

**Primary estimand:** FULL among **all planned seeded attempts** — a terminal refusal is a failed audit and counts as a non-detection (Amendment 6 clarification 2).

| condition | rung | FULL (primary, all attempts) | FULL+PARTIAL (all attempts) | FULL (verdict-bearing, diagnostic) | verdict-bearing n | terminal refusals |
|---|---|---|---|---|---|---|
| v0_opus | L1 | 3/3 = 100.0% [43.9-100.0%] | 3/3 = 100.0% [43.9-100.0%] | 3/3 = 100.0% [43.9-100.0%] | 3/3 | 0 |

*Source: `results/phase2_grades.jsonl` joined to `run_meta.json` outcomes; rates from `analysis_instrument.detection_rates`.*

> L1–L3 are heterogeneous designed conditions at small n, not doses of a subtlety variable. No monotone trend is fitted, tested or implied.

## 2 · The null (L0)

**Primary estimand:** frozen-rule false positives among **VERDICT-BEARING** runs — a refusal is not a correct rejection, and counting it as one would understate confabulation (Amendment 6 clarification 2). Denominator named in every column heading below.

| condition | FPR primary (frozen rule, verdict-bearing) | strict rule (verdict-bearing) | all-attempt burden | attempts | verdict-bearing | refusals |
|---|---|---|---|---|---|---|
| v0_opus | 2/10 = 20.0% [5.7-51.0%] | 2/10 = 20.0% [5.7-51.0%] | 2/10 = 20.0% [5.7-51.0%] | 10 | 10 | 0 |

*The verbatim claim text of ALL L0 verdicts is published separately and un-cherry-picked (Amendment 3 item 4); this table carries only the counts.*

## 3 · Refusal — an operational outcome, not missing data

| condition | terminal refusal (k/n, 95% Wilson) | mid-run refusal events in verdict-bearing runs |
|---|---|---|
| v0_opus | 0/13 = 0.0% [0.0-22.8%] | 0 |

> The fixed battery and the drift floor **cannot** incur a brain-side refusal by construction. That asymmetry is reported, not equalized (Amendment 6 clarification 6). Every rate here is for one recipe × one brain × this target set.

## 4 · Dollars per FULL detection

**Primary:** complete recorded spend (`total_usd`) over **all planned attempts on HEADLINE pairs** ÷ FULL detections. An audit programme pays for its refusals, so refused attempts' spend is in the numerator. Zero detections yields `undefined`, never infinity; any unpriced component removes the condition from the dollar ranking entirely. The exploratory pair is excluded (Amendment 4 item 2) and appears only as a labelled diagnostic, as does the `brain_usd`-only variant.

| condition | primary $/FULL | total spend (`total_usd`, all attempts) | FULL detections | in dollar ranking? |
|---|---|---|---|---|
| v0_opus | $1.400000 | $4.200000 | 3 | yes |

*Scope: PRIMARY = complete recorded spend (`total_usd`) over ALL planned attempts on HEADLINE pairs only (L0 plus the designed rungs), refusals included, divided by FULL detections (Amendment 6 clarification 2, scoped by Amendment 4 item 2). The two variants below are labelled diagnostics and are never the headline number.*

*What the numerator contains: `total_usd` equals `brain_usd` for every run counted here: no judge or serving cost is recorded inside an agent run, so the two spend fields cannot disagree.*

| condition | diagnostic: `brain_usd` only | diagnostic: including the exploratory pair |
|---|---|---|
| v0_opus | $1.400000 | $1.400000 |

*Both columns above are labelled diagnostics. Neither is the headline number.*

*Judge spend is separate from the agent spend above and is NOT in any figure here: the Phase-2 judge pass recorded **$0.1942**, which excludes cache-write billing. All 51 calls reported `cache_write_tokens` (77,299 of 77,452 prompt tokens) and `JUDGE_PRICES` models no cache-write rate, so the true charge is bounded at **$0.2328-$0.3874** depending on whether the listed $2.50/M rate replaces or adds to the input rate. The recorder has since been fixed to read both cache fields; these figures are from the raws as recorded.*

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



