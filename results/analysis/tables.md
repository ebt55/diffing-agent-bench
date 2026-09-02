# Headline numbers — generated, never hand-assembled

Every rate below is produced by a function in `scripts/analysis_instrument.py` and every interval is that module's two-sided 95% Wilson score interval (Amendment 6 clarification 3). Nothing on this page was typed by a human or computed in prose.

- generated: `2026-09-02T17:40:34Z`
- mode: **UNSEALED**
- spend field: `total_usd`
- inputs:
  - `floor` — results/baseline_kl_drift_sealed.json (sha256 8c804cdb45696e64...)
  - `phase1_claims` — results/phase1_claims.jsonl (sha256 5e2f0978298f36ea...)
  - `phase2_grades` — results/phase2_grades.jsonl (sha256 64a29910054be351...)
  - `run_dirs` — 99 run_meta.json files from ['results/runs/v0_cand_*', 'results/runs/v1_cand_*', 'results/runs/bat_cand_*', 'results/runs/intro_cand_*', 'results/runs_glm/*']
  - `sealed_map` — data\sealed\rung_id_map.json (sha256 bfffc6156c03ebc2...)

## 1 · Detection across designed rungs

**Primary estimand:** FULL among **all planned seeded attempts** — a terminal refusal is a failed audit and counts as a non-detection (Amendment 6 clarification 2).

| condition | rung | FULL (primary, all attempts) | FULL+PARTIAL (all attempts) | FULL (verdict-bearing, diagnostic) | verdict-bearing n | terminal refusals |
|---|---|---|---|---|---|---|
| v0_opus | L1 | 4/5 = 80.0% [37.6-96.4%] | 5/5 = 100.0% [56.6-100.0%] | 4/5 = 80.0% [37.6-96.4%] | 5/5 | 0 |
| v0_opus | L2 | 0/5 = 0.0% [0.0-43.4%] | 0/5 = 0.0% [0.0-43.4%] | 0/4 = 0.0% [0.0-49.0%] | 4/5 | 1 |
| v0_opus | L3 | 1/5 = 20.0% [3.6-62.4%] | 1/5 = 20.0% [3.6-62.4%] | 1/4 = 25.0% [4.6-69.9%] | 4/5 | 1 |
| v1_opus | L1 | 3/3 = 100.0% [43.9-100.0%] | 3/3 = 100.0% [43.9-100.0%] | 3/3 = 100.0% [43.9-100.0%] | 3/3 | 0 |
| v1_opus | L2 | 0/3 = 0.0% [0.0-56.1%] | 0/3 = 0.0% [0.0-56.1%] | 0/3 = 0.0% [0.0-56.1%] | 3/3 | 0 |
| v1_opus | L3 | 1/3 = 33.3% [6.1-79.2%] | 1/3 = 33.3% [6.1-79.2%] | 1/3 = 33.3% [6.1-79.2%] | 3/3 | 0 |
| battery | L1 | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 1/1 | 0 |
| battery | L2 | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 1/1 | 0 |
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
| v0_opus | 4/16 = 25.0% [10.2-49.5%] | 4/16 = 25.0% [10.2-49.5%] | 4/20 = 20.0% [8.1-41.6%] | 20 | 16 | 4 |
| v1_opus | 3/10 = 30.0% [10.8-60.3%] | 3/10 = 30.0% [10.8-60.3%] | 3/10 = 30.0% [10.8-60.3%] | 10 | 10 | 0 |
| battery | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 1 | 1 | 0 |
| introspection | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 1 | 1 | 0 |

### Amendment 7 subset — frozen n=10 subset (seeds 0-9, Amendment 7)

Reported beside the full-n primary so a reader can verify the estimate did not move when the additional seeds were added.

| condition | FPR (frozen rule, verdict-bearing) | attempts | verdict-bearing |
|---|---|---|---|
| v0_opus | 1/7 = 14.3% [2.6-51.3%] | 10 | 7 |

*The verbatim claim text of ALL L0 verdicts is published separately and un-cherry-picked (Amendment 3 item 4); this table carries only the counts.*

## 3 · Refusal — an operational outcome, not missing data

| condition | terminal refusal (k/n, 95% Wilson) | mid-run refusal events in verdict-bearing runs |
|---|---|---|
| v0_opus | 8/40 = 20.0% [10.5-34.8%] | 0 |
| v1_opus | 0/19 = 0.0% [0.0-16.8%] | 2 |
| battery | 0/5 = 0.0% [0.0-43.4%] | 0 |
| introspection | 0/5 = 0.0% [0.0-43.4%] | 0 |

> The fixed battery and the drift floor **cannot** incur a brain-side refusal by construction. That asymmetry is reported, not equalized (Amendment 6 clarification 6). Every rate here is for one recipe × one brain × this target set.

## 4 · Dollars per FULL detection

**Primary:** complete recorded spend (`total_usd`) over **all planned attempts on HEADLINE pairs** ÷ FULL detections. An audit programme pays for its refusals, so refused attempts' spend is in the numerator. Zero detections yields `undefined`, never infinity; any unpriced component removes the condition from the dollar ranking entirely. The exploratory pair is excluded (Amendment 4 item 2) and appears only as a labelled diagnostic, as does the `brain_usd`-only variant.

| condition | primary $/FULL | total spend (`total_usd`, all attempts) | FULL detections | in dollar ranking? |
|---|---|---|---|---|
| v0_opus | $3.142772 | $15.713862 | 5 | yes |
| v1_opus | $2.565462 | $10.261849 | 4 | yes |
| battery | undefined (0 detections; spend $0.3005) | $0.300489 | 0 | yes |
| introspection | undefined (0 detections; spend $0.0590) | $0.058967 | 0 | yes |

*Scope: PRIMARY = complete recorded spend (`total_usd`) over ALL planned attempts on HEADLINE pairs only (L0 plus the designed rungs), refusals included, divided by FULL detections (Amendment 6 clarification 2, scoped by Amendment 4 item 2). The two variants below are labelled diagnostics and are never the headline number.*

*What the numerator contains: `total_usd` ($15.7139) exceeds `brain_usd` ($14.7347) by $0.9791: targets $0.0000 + pod $0.9791. Target generations are served on the project's own pod, so their cost appears as pod time rather than as per-token target spend - that pod component is the whole of the difference.*

| condition | diagnostic: `brain_usd` only | diagnostic: including the exploratory pair |
|---|---|---|
| v0_opus | $2.946944 | $3.542534 |
| v1_opus | $2.390386 | $2.565462 |
| battery | undefined (0 detections; spend $0.2510) | undefined (0 detections; spend $0.3842) |
| introspection | undefined (0 detections; spend $0.0437) | undefined (0 detections; spend $0.0751) |

*Both columns above are labelled diagnostics. Neither is the headline number.*

*Judge spend is separate from the agent spend above and is NOT in any figure here: the Phase-2 judge pass recorded **$0.1942**, which excludes cache-write billing. All 51 calls reported `cache_write_tokens` (77,299 of 77,452 prompt tokens) and `JUDGE_PRICES` models no cache-write rate, so the true charge is bounded at **$0.2328-$0.3874** depending on whether the listed $2.50/M rate replaces or adds to the input rate. The recorder has since been fixed to read both cache fields; these figures are from the raws as recorded.*

## 5 · Exploratory rung — reported separately, never mixed in

| condition | rung | FULL (all attempts) | FULL+PARTIAL | verdict-bearing n |
|---|---|---|---|---|
| v0_opus | L4v3 (EXPLORATORY) | 0/5 = 0.0% [0.0-43.4%] | 0/5 = 0.0% [0.0-43.4%] | 3/5 |
| battery | L4v3 (EXPLORATORY) | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 1/1 |
| introspection | L4v3 (EXPLORATORY) | 0/1 = 0.0% [0.0-79.3%] | 0/1 = 0.0% [0.0-79.3%] | 1/1 |

## 6 · Exploratory arms — separate blocks

### glm_v0 — EXPLORATORY - excluded from every section 6 headline metric and from the main figure (Amendment 9)

- runs: 30; brains: z-ai/glm-5.3-flash
- terminal refusal: 0/30 = 0.0% [0.0-11.4%]
- the two auditor brains are configured asymmetrically (Opus: adaptive thinking at high effort with prompt caching; GLM: low reasoning effort, caching off). Read the actual values from run_meta.brain.wire_params, not the config block (DECISIONS.md #23).

## 7 · Baseline 2 — distributional drift floor

Threshold-free and behaviour-blind by construction: it scores raw response text. It is **not** a comparable success rate and is deliberately absent from the main figure.

| pair | mean \|Δ logprob\| | approx top-k sym KL | tokens scored |
|---|---|---|---|
| cand_2aft:cand_2aft | 0.0 | 0.0 | 19742 |
| cand_2aft:cand_2aqm | 0.161801 | 0.070193 | 19742 |
| cand_2aft:cand_eeap | 0.172395 | 0.081177 | 19742 |
| cand_2aft:cand_hos6 | 0.157817 | 0.068644 | 19742 |
| cand_2aft:cand_m3iq | 0.15421 | 0.063109 | 19742 |
| cand_2aft:cand_z4js | 0.16573 | 0.073791 | 19742 |

*Source: `results/baseline_kl_drift_sealed.json`.*

## Human–judge agreement (Addendum C)

- runs carrying both a human and a judge grade: **59**
- human grade is primary; disagreements resolved by the human with written reasons (section 5)
- the judge is not deterministic: this model rejects temperature 0 and returned system_fingerprint null on every call (Amendment 5; results/judge_smoke.json)

| label set | n | raw agreement | positive agreement (FULL) | negative agreement (FULL) | Cohen's kappa (secondary) |
|---|---|---|---|---|---|
| detection_FULL_PARTIAL_MISS | 25 | 0.92 | 0.947368 | 0.967742 | 0.846154 |
| null_FP_CR | 26 | 1.0 | None | 1.0 | 1.0 |
| combined | 51 | 0.960784 | 0.947368 | 0.987952 | 0.94606 |

*Kappa is a secondary descriptor only — unstable at this n, and undefined when either rater uses one label throughout. Human–judge agreement is not evidence that the judge is deterministic.*


## Refusal turns

Which turn carried the refusal, from `run_meta.brain.calls` (`stop_reason == "refusal"`). Terminal refusals ended the run with no verdict; mid-run refusals happened inside a run that nevertheless produced one (Amendment 6 clarification 1), and the two are never mixed.

| condition | kind | n | median turn | distribution (turn × count) |
|---|---|---|---|---|
| v0_opus | terminal | 8 | 4 | turn 2 × 1, turn 3 × 3, turn 4 × 1, turn 5 × 1, turn 10 × 2 |
| v1_opus | midrun | 2 | 3 | turn 2 × 1, turn 3 × 1 |

*Source: `run_meta.brain.calls`. No transcript is opened, so no verdict or reply text is read to produce this table.*


