# UNSEAL RECORD

**The section 8 point of no return.** Nothing in sections 2-7 of the preregistration
may change from here. This file was written by `scripts/unseal.py`, which is the only
script that marks unsealing.

- **unsealed (UTC):** `2026-09-02T12:39:26Z`
- **HEAD at unsealing:** `929bc370fc6a5c412788756a32d15ecd039e824e` (branch `main`)

## Phase 1 predates this moment

- file: `results/phase1_claims.jsonl`
- rows: **78**
- last committed: `929bc370fc6a5c412788756a32d15ecd039e824e` at `2026-09-02T18:07:45+05:30`

The claim summaries were committed before this record was written, so git history —
not anyone's recollection — is the evidence that Phase-1 extraction happened while the
rung↔ID map was still sealed.

## The sealed map is intact

- path: `data/sealed/rung_id_map.json`
- blob (HEAD): `323498c261c7d2c27f1f4e79107f7cae20dafcc7`
- sealing commit: `3b9c883906936939ad19ecee03451db760a39742`
- blob at sealing: `323498c261c7d2c27f1f4e79107f7cae20dafcc7`

`scripts/unseal.py` verified these hashes agree. **It never opened, parsed or printed
the map's contents** — the integrity check is `git hash-object` and
`git rev-parse <commit>:<path>`, both of which emit hashes only.

## Runs complete at unsealing (from the blind inventory)

- total: **99**
- per condition: battery 5 · glm_v0 30 · introspection 5 · v0_opus 40 · v1_opus 19

Source: `results/analysis/run_inventory.json`, generated in blind mode.

## Exact next commands

```bash
python scripts/judge_grade.py --unsealed-map data/sealed/rung_id_map.json --dry-run
python scripts/judge_grade.py --unsealed-map data/sealed/rung_id_map.json
python scripts/phase2_grade.py --unsealed-map data/sealed/rung_id_map.json
python scripts/phase2_grade.py --unsealed-map data/sealed/rung_id_map.json --adjudicate
python scripts/analysis_join.py --unsealed-map data/sealed/rung_id_map.json \
  --exclude-runs v0_cand_m3iq_s4
python scripts/make_figures.py --input results/analysis/analysis_figure_input.json
```

Then hand-verify `results/analysis/tables.md` against the rendered figure before any
number leaves this repository.
