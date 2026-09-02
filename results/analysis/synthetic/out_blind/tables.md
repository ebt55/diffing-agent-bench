# Headline numbers — generated, never hand-assembled

Every rate below is produced by a function in `scripts/analysis_instrument.py` and every interval is that module's two-sided 95% Wilson score interval (Amendment 6 clarification 3). Nothing on this page was typed by a human or computed in prose.

- generated: `2026-01-01T00:00:00Z`
- mode: **BLIND (no sealed map read)**
- spend field: `brain_usd`
- inputs:
  - `floor` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic\SYNTHETIC_floor.json (sha256 0ce006e501208050...)
  - `phase1_claims` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic\SYNTHETIC_phase1_claims.jsonl (sha256 53abdab558de91cd...)
  - `phase2_grades` — C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\results\analysis\synthetic\SYNTHETIC_phase2_grades.jsonl (sha256 a7a82274bf342a90...)
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

*conditions differ in rung mix and in how many attempts ended in a cheap early refusal, so this is a per-attempt average, NOT a like-for-like per-run cost comparison. The paired same-seed comparison is the one to use for that (results/v0_v1_sealed_compare.json).*

**Overall terminal-refusal rate:** 4/74 = 5.4% [2.1-13.1%] (denominator: all planned attempts across all conditions). Mid-run refusal events inside verdict-bearing runs: 1.

*Source for every row: the `run_meta.json` `status` field, mapped to an outcome by `analysis_instrument.outcome()` (Amendment 6 clarification 1). No verdict value is read.*

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

