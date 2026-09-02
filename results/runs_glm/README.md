# Amendment 9 exploratory arm — GLM-5.3-Flash (30 sealed runs)

`run_meta.json` in each run directory is the **authoritative record** for this arm.

**The campaign log `/workspace/logs/campaign_glm.log` is EMPTY (0 bytes) and was not
committed.** The campaign completed all 30 runs correctly; the log is empty because
Python block-buffers stdout when it is piped, the campaign's total console output was
smaller than that buffer, and the tmux session tore down before `tee` flushed. The
summary line and outcome tally were lost with it.

No data was lost. Every figure reported for this arm — 30/30 runs, 29 `completed` +
1 `completed_forced`, 0 refusals, 0 unpriced calls, mean 6.10 turns, $0.0428 total at
a mean $0.001425/run — is reconstructed from the 30 `run_meta.json` files, not from
the log. `results/unpriced_path_check.json` covers these runs.

Fixed for future campaigns: `PYTHONUNBUFFERED=1` is now required on any job piped to
`tee` (see POD-SETUP.md).

## Separate results root, deliberately

Run ids are `{agent_version}_{candidate}_{seed}`. This arm runs `--agent-version v0`,
so writing it to `results/runs/` would have collided with the Opus v0 campaign's run
ids and every run would have taken the campaign driver's "already complete" skip path
— reporting 30/30 success while making no API calls and producing no data. A separate
root also keeps an exploratory arm out of the headline set, which is where Amendment 9
wants it.

## Validity

`v0_cand_m3iq_s4` was flagged by the degeneracy gate at 14.3% (threshold 10%) and
adjudicated **valid** — its short replies take 5 distinct values, are digits-only,
split 4/4 across both targets, with 48 healthy replies (31–1623 chars, median 370).
The gate targets a constant string dominating a run; this is real one-word numeric
answers. Evidence: `results/degeneracy_adjudication_glm.json`, produced by
`scripts/adjudicate_degeneracy.py`. That adjudication is a data-reactive refinement of
a pre-committed gate, made pre-unsealing without reading any verdict, and the affected
condition can be reported with the run excluded via
`scripts/analysis_join.py --exclude-runs v0_cand_m3iq_s4` (primary keeps it).
