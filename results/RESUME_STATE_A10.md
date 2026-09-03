# RESUME STATE — Amendment 10 (Arm N + Arm R)

Live operational state for the Amendment 10 arm. Kept current so a rate-limit death
can resume without guessing. Numbers here are read off the pod / the working tree at
the timestamp given; nothing is projected except where it says so.

**Spec:** `PREREGISTRATION.md` "Amendment 10" (committed `1353685`, before any run of
this arm existed). Evidence trail `DECISIONS.md` #39.

---

## 0. Milestone status

| milestone | state |
|---|---|
| M1 pod + base serving | **DONE** — abort gate cleared with 66 min to spare |
| M2 Arm R prompts file (committed before sampling) | **DONE** — `c7ce94a` |
| M3 Arm R sampling + analysis | sampling RUNNING (tmux `armr`) |
| M4 Arm N campaigns (opus, glm) | not started |
| M5 grading prep (extract, judge, Phase-2 server, analysis_join) | not started |
| M6 pod stop + report | not started |

---

## 1. Pod

| field | value |
|---|---|
| pod id | `ssvo2u09gloud8` |
| name | `b13-diffing-bench-a10` |
| GPU | **NVIDIA L40S 48GB** (see disclosure below) |
| $/hr | **0.99** |
| cloud | Secure Cloud, location SE |
| image | `runpod/pytorch:1.2.0-rc.162-cu1281-torch2130-ubuntu2404` |
| volume | 100 GB @ `/workspace`, container disk 50 GB |
| machine | `sob1z2r1fy41`, 16 vCPU / 188 GB RAM |
| provisioning call (UTC) | **2026-09-03T11:48:48Z** |
| createdAt (UTC) | 2026-09-03T11:48:52Z |
| **90-minute abort deadline (UTC)** | **2026-09-03T13:18:48Z** |

### GPU disclosure (Amendment 10 permits A40, A6000 or L40S with disclosure)

The first create call, at 2026-09-03T11:48:30Z, requested `NVIDIA A40` alone and
RunPod returned `{"error":"create pod: There are no instances currently available"}`
— **no pod was created and no clock started**. The second call, 18 s later, offered
the sanctioned fallback list in preference order (A40, RTX A6000, L40S, L40, RTX 6000
Ada) and RunPod's scheduler allocated an **L40S at $0.99/hr** — 2.25x the A40's
$0.44/hr. The pod ceiling in Amendment 10 is $5, which buys ~5 h on this card;
Arm R + Arm N need far less. Consequence for the stack: L40S is Ada `sm_89`, so
`TORCH_CUDA_ARCH_LIST=8.9` (the Aug/Sep pods were Ampere `8.6`). The serving stack,
the pinned base revision and the file hashes are unchanged, and the base is verified
against `results/base_materialization.json` before anything is served.

---

### SSH and sessions

```powershell
$key = "$env:USERPROFILE\.ssh\id_ed25519"
ssh -i $key -p 15675 root@202.181.159.229
```

Repo at `/workspace/repo`, pinned to the commit under test (`git log --oneline -1`).
Logs are tee'd to `/workspace/logs/`. PowerShell mangles quoting when it hands a
command string to `ssh`; write the script to a file and `scp` it, or use the
`Invoke-Pod` helper in the session scratchpad.

| tmux session | what | started (UTC) |
|---|---|---|
| `vllm` | serving; log `/workspace/logs/a10_vllm_server.log` | 12:06:58 |
| `armr` | Arm R sampling; log `/workspace/logs/a10_arm_r.log` | 12:16:25 |

---

## 2. Milestone 1 receipts

| step | UTC | result |
|---|---|---|
| pip stack pinned per POD-SETUP.md §2 | 11:54:26 → 12:01:39 | torch 2.13.0+cu129, vllm 0.28.0(+cu129), transformers 5.16.1, trl 1.11.0, peft 0.20.0, datasets 5.0.1, accelerate 1.14.0, hub 1.29.0, fla 0.5.2, causal_conv1d 1.7.0; `Qwen3_5ForCausalLM registered: True` |
| repo clone @ `5dd5df5` | 12:01:48 → 12:04 | first clone aborted (`/workspace/repo` already held the staged `.env`); repaired and re-run as `setup_a10_part2.sh`, logged in the same file |
| base materialized from pinned revision `c202236…b9a` | 12:04 → 12:05:14 | manifest written to the NEW path `results/base_materialization_rebuild_a10.json`; the committed `results/base_materialization.json` was never overwritten |
| **base hash verify vs `results/base_materialization.json`** | 12:05:14 | **`SHA_MANIFEST_RESULT ok=10 bad=0 missing=0 of 10`** |
| adapters pulled from `ebt005/b13-ladder-private` | 12:05:14 → 12:05:22 | `adapters_v2/{L0,L1,L2,L3}` + `adapters_v3/L4` |
| **adapter hash verify vs `adapter_manifest_v{2,3}.json`** | 12:05:23 | **`ADAPTER_HASH_RESULT ok=25 of 25`** (L0 `29a678b0…`, L1 `f37955d3…`, L2 `d6869d9e…`, L3 `9aa79f46…`, L4v3 `8ab019c6…`) |
| vLLM started | 12:06:58 | `base,cand_nullA,cand_nullB` on one set of weights; adapters preloaded |
| **server up (abort gate cleared)** | **12:10:23** | **21 min 35 s after the provisioning call; gate was 13:18:48** |
| L0–L3 loaded at runtime | 12:10:5x | see deviation D2 below |
| serving smoke + standing-rule verify | 12:11:14 → 12:12:36 | `/workspace/logs/a10_serve_smoke.log`, `results/a10_verify_<rung>.json` |

`GET /v1/models` reports 8: `base`, `cand_nullA`, `cand_nullB` (all three the same
weights, `parent` absent) and adapters `L0`, `L1`, `L2`, `L3`, `L4v3`
(`parent=base`).

### Standing rule (decision 7): every adapter expresses through the SERVING path

| adapter | tokens | mean diff | mean \|diff\| | exactly zero? |
|---|---|---|---|---|
| L0 | 43 | −0.2256 | 0.7336 | no |
| L1 | 43 | −0.2777 | 0.7452 | no |
| L2 | 43 | −0.1913 | 0.6793 | no |
| L3 | 43 | −0.1691 | 0.6941 | no |
| L4v3 | 43 | −0.1086 | 0.7004 | no |

Non-zero on all five, which is the clause that matters: exactly 0.0000 would mean
vLLM silently applied no adapter. The canary clause reported 0/3 for every rung and
is **not** a failure of these adapters — `verify`'s default canary string is
`gate0_toy`'s sign-off marker, which no ladder rung was ever trained to emit. The
ladder's own expression evidence is `results/expression_matrix_v2.md` (v2) and
`results/l4v3_*` (v3), collected pre-sealing; nothing here re-opens it.

---

## 3. Deviations from Amendment 10 / the brief, so far

- **D1 — GPU is an L40S at $0.99/hr, not an A40 at $0.44/hr.** Amendment 10 permits
  A40, A6000 or L40S with disclosure. See §1. Consequence: `POD_HOURLY_USD = 0.44`
  in `src/diffing_agent/config.py` is an A40 constant and was deliberately **not**
  changed, so the `pod_usd` field inside every Arm N `run_meta.json` is computed at
  $0.44/hr and understates the true pod cost by 2.25x. Left alone so the cost
  arithmetic stays comparable with the sealed campaign's; the true pod spend is
  reported separately from the RunPod API.
- **D2 — vLLM registers only the last `--lora-modules` flag.** `serve_ladder.py`
  emits one `--lora-modules` per adapter, and vLLM's parser kept only `L4v3`. L0–L3
  were loaded at runtime with `serve_ladder.py load-ladder` (the documented,
  idempotent path; `VLLM_ALLOW_RUNTIME_LORA_UPDATING=True`) and verified present in
  `GET /v1/models`. Same weights, same hashes, different registration moment.
- **D3 — `run_meta.label_map` records the served ids, not the string "base".** The
  brief asked for `label_map` to record both letters → base. `agent.py` writes
  `{label: served model name}` and it is the sealed harness, so it was not modified:
  Arm N rows will read `{"model_A": "cand_nullA", "model_B": "cand_nullB"}` (order
  per the seed's shuffle). The identity is recorded instead in two places that
  cannot drift from the run — the `notes` field inside each `run_meta.json`, and
  `results/runs_null_identical/ARM_N_IDENTITY.json`, which carries the vLLM launch
  command, the live `/v1/models` response and the 10/10 base hash verification.

---

## 4. Spend

Pod only so far. No Arm N run and no judge call has been made; brain spend is $0.00
against the $12 Amendment 10 ceiling.
