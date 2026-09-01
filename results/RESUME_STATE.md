# RESUME STATE — checkpoint at 2026-09-01 21:40 UTC

Written because the session was about to freeze on a usage limit. Everything below is
read off the pod and the working tree at that moment; nothing here is projected except
where it says so explicitly.

**First instruction on resume:** collect v1 → verify → append block 3 → Task E.

---

## 1. Running on the pod RIGHT NOW — leave it alone

Pod `194.68.245.32`, SSH port `22070`, key `~/.ssh/id_ed25519`, repo at
`/workspace/repo`. The campaign is pod-side inside tmux and survives the local session
freezing.

| tmux session | what | started (UTC) |
|---|---|---|
| `v1camp` | Task D — the 19-run v1 campaign | Sep 1, 21:12:13 |
| `vllm` | sealed multi-LoRA serving (all 6 candidates) | Sep 1, 15:00:17 |

- Log: `/workspace/logs/campaign_v1.log` (tee'd; the tmux pane is not the only copy).
- Run dirs land in `/workspace/repo/results/runs/v1_cand_<id>_s<seed>`.
- Command under way:
  `python scripts/run_campaign.py --plan configs/campaign_plan.local.json
  --agent-version v1 --seed-override 10:10,5:3 --max-campaign-usd 15`
- Shape: 19 runs over 4 pairs, seeds `{cand_2aqm:3, cand_eeap:3, cand_hos6:3,
  cand_z4js:10}`. No exploratory pair. Pre-launch validation passed on all 19 configs
  (config parity + leak guard + arm scan).

**Progress at checkpoint:** 5/19 logged, 6 run dirs on disk (5 finished + 1 in
flight). Campaign brain spend $2.1818 against the $15 ceiling. Aggregate statuses
only: 3 `completed`, 2 `completed_forced`, all 5 verdict-bearing.

**Expected completion ≈ 22:45 UTC.** This is an estimate and has already slipped once:
the first pair averaged ~4 min/run at ~$0.30, the `cand_eeap` pair is running ~6 min at
~$0.56–0.67 and forcing the final submission. Re-derive from the log rather than
trusting this line.

**Do not** stop the pod, kill either tmux session, or start Task E before Task D is
confirmed complete (Amendment 9 forbids concurrent campaign traffic on the sealed
server).

---

## 2. Not started

- Collecting the v1 run dirs to the local box.
- Leak check + target-health screen over the v1 runs.
- `v0_v1_sealed_compare.py` (written and committed, never yet run against real v1 data
  — it currently exits with "no v1 sealed runs found", which is correct).
- **Phase-1 block 3** — the append of the 19 v1 runs.
- **Task E** (Amendment 9 GLM arm): dev gate, then the sealed campaign.
- Pod stop — awaiting Ebin's instruction, not to be done on an agent's initiative.

---

## 3. Collect the v1 artifacts (run first on resume)

Confirm the campaign actually finished before collecting:

```powershell
$key="$env:USERPROFILE\.ssh\id_ed25519"
ssh -i $key -p 22070 root@194.68.245.32 "tail -n 25 /workspace/logs/campaign_v1.log"
```

Look for the terminal line `N/19 runs complete in M min`. `[TRIPWIRE]`,
`[CAMPAIGN BUDGET STOP]` or a `Traceback` mean it stopped early — report that rather
than treating a partial set as the campaign.

```powershell
$key="$env:USERPROFILE\.ssh\id_ed25519"
scp -i $key -P 22070 -r "root@194.68.245.32:/workspace/repo/results/runs/v1_cand_*" .\results\runs\
```

Then verify, all four:

```powershell
python scripts\verify_no_unpriced.py
python scripts\check_run_leaks.py --runs "results/runs/v1_cand_*" --out results/run_leak_check_v1.json
python scripts\screen_target_health.py --globs "results/runs/v1_cand_*" --out results/target_health_screen_v1.json
python scripts\v0_v1_sealed_compare.py
```

`verify_no_unpriced.py` stood at **75 runs checked, 0 flagged (CLEAN)** before the v1
runs existed; it must still be clean with them included. That is the confirmation the
coordinator asked for on the budget-guard finding.

---

## 4. Append Phase-1 block 3

Only after the v1 runs are local and verified.

```powershell
python scripts\phase1_grade.py --rebuild-order --seed 20260903 `
  --runs "results/runs/v0_cand_*_s*" "results/runs/v1_cand_*_s*" --status
```

- Appends **only** what is not already in a block, so blocks 1 (30 v0) and 2 (10 L0
  extensions) are untouched and grading in flight stays valid.
- The seed is arbitrary but must be committed with the block; 20260903 continues the
  date convention (block 1 = 20260901, block 2 = 20260902).
- `build_order` attaches the arm disclosure automatically to any block containing v1
  runs — it is not typed in by hand and cannot be forgotten. Confirm it is present on
  block 3 afterwards.
- **Do not touch `results/phase1_claims.jsonl`.** Ebin is grading block 1 against it.

---

## 5. Task E — Amendment 9 GLM arm

### 5a. Deploy first (the pod does not have the code this arm needs)

The pod's checkout predates `reasoning_effort`, `wire_params` and the unpriced-model
budget guard. Without the first of those the gate would fail for the wrong reason.

```powershell
ssh -i $key -p 22070 root@194.68.245.32 "cd /workspace/repo && git pull"
```

### 5b. Functional gate — USES THE LOCAL GPU

Announce start and end times before and after; nothing else may use the GPU meanwhile.
Needs Ollama serving `llama3.1:8b` and `mistral-nemo:12b`. Roughly 10 minutes.

```powershell
python -m diffing_agent --config configs/glm_devnull_10turn.json --seed 0 `
  --run-id glm_gate_devnull_s0 --results-root results/runs_dev
python -m diffing_agent --config configs/glm_devdiff_10turn.json --seed 0 `
  --run-id glm_gate_devdiff_s0 --results-root results/runs_dev
```

Gate passes only if GLM executes the tool protocol: `query_models` then
`submit_verdict`, with the blinding path intact. Amendment 9: if the brain cannot
execute the recipe's tool protocol, **the arm is not run**.

Effort ladder, per the coordinator — lowest setting that reliably works. Both configs
start at `reasoning_effort: "low"` with `max_tokens: 8000`. If content comes back
empty or truncated, **raise `max_tokens` before raising effort**. Record whatever is
finally used; `run_meta.brain.wire_params` captures what was actually sent.

### 5c. Sealed campaign (pod, tmux, only after the gate passes and D is done)

```bash
tmux new-session -d -s glmcamp
cd /workspace/repo && set -a && . /root/.env.b13 && set +a && PYTHONPATH=src \
  python scripts/run_campaign.py --plan configs/campaign_plan.local.json \
  --agent-version v0 --brain-config configs/glm_devnull_10turn.json \
  --include-exploratory --max-campaign-usd 5 \
  2>&1 | tee /workspace/logs/campaign_glm.log
```

- `--brain-config` reads only the `brain` block from that file, so the dev config is
  the right source for the brain and no extra file is needed.
- `--agent-version v0` and `--include-exploratory`: Amendment 9 freezes the v0 recipe
  over the same 30 seed assignments (L0 ×10, L1–L3 ×5, exploratory ×5).
- The `$5` figure is a **ceiling, not a projection.** Do not state an expected cost
  until the gate has measured a real per-run cost for this model.

### 5d. Must appear in the Task E report

The two arms are configured asymmetrically and that goes in the disclosure: the Opus
brain runs adaptive thinking at `effort: high` with prompt caching; the GLM arm runs
`reasoning_effort: low` with caching off. Acceptable for an exploratory arm whose
primary output is the refusal rate, but only because it is written down. Read the
actual values from `run_meta.brain.wire_params` rather than from the config block —
`BrainConfig` carries Anthropic-only fields (`effort`, `thinking`) that are never sent
on the OpenRouter route, so the config alone reads as though GLM ran at high effort.

---

## 6. Carry into the final report

- Dev refusal for v1 was 3/7 against 7/30 for v0's sealed campaign. Amendment 8's
  prediction (d) is being tested against contrary dev evidence — recorded, unresolved.
- Verbatim: `gate0_toy` (the preregistration's named dev pair) was never backed up to
  HuggingFace and was lost with the original pod volume; the substituted local pair is
  disclosed in config.
- v1 transcripts are arm-identifiable by construction; rung identity remains sealed.
- `results/runs/mock_smoke` is the only artifact on disk that is not valid UTF-8 (a
  cp1252 em-dash, pre-fix dev run). Left byte-for-byte. No campaign artifact affected;
  `verify_no_unpriced.py` reads it through an explicit fallback so the audit has no
  silent hole.
- Local `bash` is broken (Cygwin fork failure). Use PowerShell for everything local.
  Background PowerShell commands are capped at 10 minutes, so waiting on a long pod job
  means chaining watchers rather than one long wait.
