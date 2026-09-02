# Headline numbers — generated, never hand-assembled

Every rate below is produced by a function in `scripts/analysis_instrument.py` and every interval is that module's two-sided 95% Wilson score interval (Amendment 6 clarification 3). Nothing on this page was typed by a human or computed in prose.

- generated: `2026-09-02T03:00:00Z`
- mode: **BLIND (no sealed map read)**
- spend field: `total_usd`
- inputs:
  - `floor` — results/baseline_kl_drift_sealed.json (sha256 8c804cdb45696e64...)
  - `phase1_claims` — results/phase1_claims.jsonl (sha256 151a7528a6480772...)
  - `phase2_grades` — results/phase2_grades.jsonl (sha256 e3b0c44298fc1c14...)
  - `run_dirs` — 99 run_meta.json files from ['results/runs/v0_cand_*', 'results/runs/v1_cand_*', 'results/runs/bat_cand_*', 'results/runs/intro_cand_*', 'results/runs_glm/*']
  - `sealed_map` — NOT READ (blind mode)

## BLIND MODE — rung-keyed tables are refused

every rung-keyed quantity: detection rates, the L0 false-positive rate, dollars per FULL detection, and the per-candidate drift ranking. These require the rung<->ID map and are emitted only under --unsealed-map.

*Why:* emitting per-sealed-id results before unsealing would recreate exactly the ops-log exposure Amendment 6 clarification 7 disclosed

### Per-condition outcomes (no rung identity involved)

| condition | arm | attempts | verdict-bearing | terminal refusals | refusal rate (k/n, 95% Wilson) | recorded spend | mean $/attempt | cost complete |
|---|---|---|---|---|---|---|---|---|
| battery | headline | 5 | 5 | 0 | 0/5 = 0.0% [0.0-43.4%] | $0.3842 | $0.0768 | yes |
| glm_v0 | exploratory_arm | 30 | 30 | 0 | 0/30 = 0.0% [0.0-11.4%] | $0.5474 | $0.0182 | yes |
| introspection | headline | 5 | 5 | 0 | 0/5 = 0.0% [0.0-43.4%] | $0.0751 | $0.0150 | yes |
| v0_opus | headline | 40 | 32 | 8 | 8/40 = 20.0% [10.5-34.8%] | $17.7127 | $0.4428 | yes |
| v1_opus | headline | 19 | 19 | 0 | 0/19 = 0.0% [0.0-16.8%] | $10.2618 | $0.5401 | yes |

*Spend field: `total_usd`. `total_usd` ($28.9812) exceeds `brain_usd` ($26.5741) by $2.4071: targets $0.0000 + pod $2.4071. Target generations are served on the project's own pod, so their cost appears as pod time rather than as per-token target spend - that pod component is the whole of the difference.*

*conditions differ in rung mix and in how many attempts ended in a cheap early refusal, so this is a per-attempt average, NOT a like-for-like per-run cost comparison. The paired same-seed comparison is the one to use for that (results/v0_v1_sealed_compare.json).*

**Overall terminal-refusal rate:** 8/99 = 8.1% [4.2-15.1%] (denominator: all planned attempts across all conditions). Mid-run refusal events inside verdict-bearing runs: 2.

*Source for every row: the `run_meta.json` `status` field, mapped to an outcome by `analysis_instrument.outcome()` (Amendment 6 clarification 1). No verdict value is read.*

## Human–judge agreement (Addendum C)

- runs carrying both a human and a judge grade: **0**
- human grade is primary; disagreements resolved by the human with written reasons (section 5)
- the judge is not deterministic: this model rejects temperature 0 and returned system_fingerprint null on every call (Amendment 5; results/judge_smoke.json)

*no run carries both a human and a judge grade yet, so no agreement statistic is computed - none is invented*


## Refusal turns

Which turn carried the refusal, from `run_meta.brain.calls` (`stop_reason == "refusal"`). Terminal refusals ended the run with no verdict; mid-run refusals happened inside a run that nevertheless produced one (Amendment 6 clarification 1), and the two are never mixed.

| condition | kind | n | median turn | distribution (turn × count) |
|---|---|---|---|---|
| v0_opus | terminal | 8 | 4 | turn 2 × 1, turn 3 × 3, turn 4 × 1, turn 5 × 1, turn 10 × 2 |
| v1_opus | midrun | 2 | 3 | turn 2 × 1, turn 3 × 1 |

*Source: `run_meta.brain.calls`. No transcript is opened, so no verdict or reply text is read to produce this table.*


