# Headline numbers — generated, never hand-assembled

Every rate below is produced by a function in `scripts/analysis_instrument.py` and every interval is that module's two-sided 95% Wilson score interval (Amendment 6 clarification 3). Nothing on this page was typed by a human or computed in prose.

- generated: `2026-01-01T00:00:00Z`
- mode: **UNSEALED**
- spend field: `total_usd`
- inputs:
  - `floor` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic\SYNTHETIC_floor.json (sha256 0ce006e501208050...)
  - `phase1_claims` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic\SYNTHETIC_phase1_claims.jsonl (sha256 53abdab558de91cd...)
  - `phase2_grades` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic\SYNTHETIC_phase2_grades.jsonl (sha256 8a81f80334c193aa...)
  - `run_dirs` — 74 run_meta.json files from ['C:\\Users\\ebin\\claude-ground\\neel-mats-sept-26\\b13-diffing-bench\\results\\analysis\\synthetic\\runs\\*']
  - `sealed_map` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic\SYNTHETIC_fake_rung_map.json (sha256 b66b4594a94c61d1...)

## 1 · Detection across designed rungs

**Primary estimand:** FULL among **all planned seeded attempts** — a terminal refusal is a failed audit and counts as a non-detection (Amendment 6 clarification 2).

| condition | rung | FULL (primary, all attempts) | FULL+PARTIAL (all attempts) | FULL (verdict-bearing, diagnostic) | verdict-bearing n | terminal refusals |
|---|---|---|---|---|---|---|
| v0_opus | L1 | 4/5 = 80.0% [37.6-96.4%] | 4/5 = 80.0% [37.6-96.4%] | 4/4 = 100.0% [51.0-100.0%] | 4/5 | 1 |
| v0_opus | L2 | 2/5 = 40.0% [11.8-76.9%] | 4/5 = 80.0% [37.6-96.4%] | 2/5 = 40.0% [11.8-76.9%] | 5/5 | 0 |
| v0_opus | L3 | 0/5 = 0.0% [0.0-43.4%] | 2/5 = 40.0% [11.8-76.9%] | 0/5 = 0.0% [0.0-43.4%] | 5/5 | 0 |
| v1_opus | L1 | 3/3 = 100.0% [43.9-100.0%] | 3/3 = 100.0% [43.9-100.0%] | 3/3 = 100.0% [43.9-100.0%] | 3/3 | 0 |
| v1_opus | L2 | 1/3 = 33.3% [6.1-79.2%] | 2/3 = 66.7% [20.8-93.9%] | 1/3 = 33.3% [6.1-79.2%] | 3/3 | 0 |
| v1_opus | L3 | 0/3 = 0.0% [0.0-56.1%] | 1/3 = 33.3% [6.1-79.2%] | 0/3 = 0.0% [0.0-56.1%] | 3/3 | 0 |
| battery | L1 | 1/1 = 100.0% [20.7-100.0%] | 1/1 = 100.0% [20.7-100.0%] | 1/1 = 100.0% [20.7-100.0%] | 1/1 | 0 |
| battery | L2 | 0/1 = 0.0% [0.0-79.3%] | 1/1 = 100.0% [20.7-100.0%] | 0/1 = 0.0% [0.0-79.3%] | 1/1 | 0 |
| battery | L3 | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 1/1 | 0 |
| introspection | L1 | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 1/1 | 0 |
| introspection | L2 | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 1/1 | 0 |
| introspection | L3 | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 1/1 | 0 |

*Source: `results/phase2_grades.jsonl` joined to `run_meta.json` outcomes; rates from `analysis_instrument.detection_rates`.*

> L1–L3 are heterogeneous designed conditions at small n, not doses of a subtlety variable. No monotone trend is fitted, tested or implied.

## 2 · The null (L0)

**Primary estimand:** frozen-rule false positives among **VERDICT-BEARING** runs — a refusal is not a correct rejection, and counting it as one would understate confabulation (Amendment 6 clarification 2). Denominator named in every column heading below.

| condition | FPR primary (frozen rule, verdict-bearing) | strict rule (verdict-bearing) | all-attempt burden | attempts | verdict-bearing | refusals |
|---|---|---|---|---|---|---|
| v0_opus | 2/18 = 11.1% [3.1-32.8%] | 3/18 = 16.7% [5.8-39.2%] | 2/20 = 10.0% [2.8-30.1%] | 20 | 18 | 2 |
| v1_opus | 1/10 = 10.0% [1.8-40.4%] | 1/10 = 10.0% [1.8-40.4%] | 1/10 = 10.0% [1.8-40.4%] | 10 | 10 | 0 |
| battery | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 1 | 1 | 0 |
| introspection | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 1 | 1 | 0 |

### Amendment 7 subset — frozen n=10 subset (seeds 0-9, Amendment 7)

Reported beside the full-n primary so a reader can verify the estimate did not move when the additional seeds were added.

| condition | FPR (frozen rule, verdict-bearing) | attempts | verdict-bearing |
|---|---|---|---|
| v0_opus | 1/9 = 11.1% [2.0-43.5%] | 10 | 9 |

*The verbatim claim text of ALL L0 verdicts is published separately and un-cherry-picked (Amendment 3 item 4); this table carries only the counts.*

## 3 · Refusal — an operational outcome, not missing data

| condition | terminal refusal (k/n, 95% Wilson) | mid-run refusal events in verdict-bearing runs |
|---|---|---|
| v0_opus | 3/40 = 7.5% [2.6-19.9%] | 1 |
| v1_opus | 0/19 = 0.0% [0.0-16.8%] | 0 |
| battery | 0/5 = 0.0% [0.0-43.4%] | 0 |
| introspection | 0/5 = 0.0% [0.0-43.4%] | 0 |

> The fixed battery and the drift floor **cannot** incur a brain-side refusal by construction. That asymmetry is reported, not equalized (Amendment 6 clarification 6). Every rate here is for one recipe × one brain × this target set.

## 4 · Dollars per FULL detection

**Primary:** complete recorded spend (`total_usd`) over **all planned attempts on HEADLINE pairs** ÷ FULL detections. An audit programme pays for its refusals, so refused attempts' spend is in the numerator. Zero detections yields `undefined`, never infinity; any unpriced component removes the condition from the dollar ranking entirely. The exploratory pair is excluded (Amendment 4 item 2) and appears only as a labelled diagnostic, as does the `brain_usd`-only variant.

| condition | primary $/FULL | total spend (`total_usd`, all attempts) | FULL detections | in dollar ranking? |
|---|---|---|---|---|
| v0_opus | $2.090000 | $12.540000 | 6 | yes |
| v1_opus | $2.350000 | $9.400000 | 4 | yes |
| battery | excluded (unpriced component) | unknown (null, never zero) | — | no |
| introspection | undefined (0 detections; spend $0.0480) | $0.048000 | 0 | yes |

*Scope: PRIMARY = complete recorded spend (`total_usd`) over ALL planned attempts on HEADLINE pairs only (L0 plus the designed rungs), refusals included, divided by FULL detections (Amendment 6 clarification 2, scoped by Amendment 4 item 2). The two variants below are labelled diagnostics and are never the headline number.*

*What the numerator contains: `total_usd` equals `brain_usd` for every run counted here: no judge or serving cost is recorded inside an agent run, so the two spend fields cannot disagree.*

| condition | diagnostic: `brain_usd` only | diagnostic: including the exploratory pair |
|---|---|---|
| v0_opus | $2.090000 | $2.506667 |
| v1_opus | $2.350000 | $2.350000 |
| battery | excluded (unpriced) | excluded (unpriced) |
| introspection | undefined (0 detections; spend $0.0480) | undefined (0 detections; spend $0.0600) |

*Both columns above are labelled diagnostics. Neither is the headline number.*

## 5 · Exploratory rung — reported separately, never mixed in

| condition | rung | FULL (all attempts) | FULL+PARTIAL | verdict-bearing n |
|---|---|---|---|---|
| v0_opus | L4v3 (EXPLORATORY) | 0/5 = 0.0% [0.0-43.4%] | 1/5 = 20.0% [3.6-62.4%] | 5/5 |
| battery | L4v3 (EXPLORATORY) | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 1/1 |
| introspection | L4v3 (EXPLORATORY) | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 1/1 |

## 6 · Exploratory arms — separate blocks

### glm_v0 — EXPLORATORY - excluded from every section 6 headline metric and from the main figure (Amendment 9)

- runs: 5; brains: glm-5.3-flash
- terminal refusal: 1/5 = 20.0% [3.6-62.4%]
- the two auditor brains are configured asymmetrically (Opus: adaptive thinking at high effort with prompt caching; GLM: low reasoning effort, caching off). Read the actual values from run_meta.brain.wire_params, not the config block (DECISIONS.md #23).

## 7 · Baseline 2 — distributional drift floor

Threshold-free and behaviour-blind by construction: it scores raw response text. It is **not** a comparable success rate and is deliberately absent from the main figure.

| pair | mean \|Δ logprob\| | approx top-k sym KL | tokens scored |
|---|---|---|---|
| base vs base (must be exactly 0.0) | 0.0 | 0.0 | 10 |
| L0 | 0.1 | 0.2 | 10 |
| L1 | 0.1 | 0.2 | 10 |
| L2 | 0.1 | 0.2 | 10 |
| L3 | 0.1 | 0.2 | 10 |
| L4v3 | 0.1 | 0.2 | 10 |

*Source: `results/baseline_kl_drift_sealed.json`.*

## Human–judge agreement (Addendum C)

- runs carrying both a human and a judge grade: **70**
- human grade is primary; disagreements resolved by the human with written reasons (section 5)
- the judge is not deterministic: this model rejects temperature 0 and returned system_fingerprint null on every call (Amendment 5; results/judge_smoke.json)

| label set | n | raw agreement | positive agreement (FULL) | negative agreement (FULL) | Cohen's kappa (secondary) |
|---|---|---|---|---|---|
| detection_FULL_PARTIAL_MISS | 38 | 1.0 | 1.0 | 1.0 | 1.0 |
| null_FP_CR | 32 | 0.96875 | None | 1.0 | 0.84 |
| combined | 70 | 0.985714 | 1.0 | 1.0 | 0.98037 |

*Kappa is a secondary descriptor only — unstable at this n, and undefined when either rater uses one label throughout. Human–judge agreement is not evidence that the judge is deterministic.*


## Refusal turns

Which turn carried the refusal, from `run_meta.brain.calls` (`stop_reason == "refusal"`). Terminal refusals ended the run with no verdict; mid-run refusals happened inside a run that nevertheless produced one (Amendment 6 clarification 1), and the two are never mixed.

| condition | kind | n | median turn | distribution (turn × count) |
|---|---|---|---|---|
| glm_v0 | terminal | 1 | 1 | turn 1 × 1 |
| v0_opus | terminal | 3 | 1 | turn 1 × 3 |
| v0_opus | midrun | 1 | 2 | turn 2 × 1 |

*Source: `run_meta.brain.calls`. No transcript is opened, so no verdict or reply text is read to produce this table.*


