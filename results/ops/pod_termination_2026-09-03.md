# Pod termination receipt — 2026-09-03

**Authorization.** Ebin authorized this in chat, verbatim: "terminate the pod."
Executed by an ops agent under the standing gate in `POD-SETUP.md` §6 —
*"Terminate only at the end of the project, after everything is off-box"* — so the
Hugging Face backup was verified **before** anything was destroyed.

| event | UTC | IST |
| --- | --- | --- |
| backup check started | 2026-09-02T23:26Z | 2026-09-03 04:56 |
| pod list (before) | 2026-09-02T23:33Z | 2026-09-03 05:03 |
| `podTerminate` issued | 2026-09-02T23:34:10Z | 2026-09-03 05:04:10 |
| pod list (after) | 2026-09-02T23:34:18Z | 2026-09-03 05:04:18 |

---

## 1. Backup check — `ebt005/b13-ladder-private` (private, 100 files)

Method: `huggingface_hub` 1.24.0 from the Windows box, `list_repo_tree(expand=True)`.
For LFS files the Hub's own `lfs.sha256` was compared against the manifests; the
small non-LFS files (`adapter_config.json`, `tokenizer_config.json`,
`chat_template.jinja`) were downloaded and SHA-256'd locally. Repo confirmed
`private=True`, last modified 2026-08-31T22:53:49Z. Token read from `.env`, never
printed. **No path under any `sealed` prefix exists in the repo (0 found), and none
was inspected.**

### 1a. v2 adapters L0–L3 (+L4) — `results/adapter_manifest_v2.json`

They are stored under the **`adapters_v2/`** prefix, not `adapters/`. **25/25 files
byte-identical, 0 differing, 0 missing.**

| rung | `adapter_model.safetensors` sha256 (expected = found) | config/tokenizer/template |
| --- | --- | --- |
| L0 | `29a678b0fd7abe3b…` ✅ | 4/4 ✅ |
| L1 | `f37955d3aeaec0c2…` ✅ | 4/4 ✅ |
| L2 | `d6869d9e4b636672…` ✅ | 4/4 ✅ |
| L3 | `9aa79f461801dde9…` ✅ | 4/4 ✅ |
| L4 | `e1fd510f1f142d1e…` ✅ | 4/4 ✅ |

### 1b. L4v3 adapter — `results/adapter_manifest_v3.json`

Stored under `adapters_v3/L4/`. **5/5 files byte-identical**, including
`adapter_model.safetensors` = `8ab019c6348d2765…` and the v3-specific
`adapter_config.json` = `37b1392d07f67959…`.

### 1c. v1 adapters — `results/adapter_manifest.json`

The **`adapters/`** prefix (the 2026-08-30 upload recorded in `results/hf_backup.json`)
holds the **v1** generation, not v2. Checked for completeness: **25/25 files
byte-identical** to `adapter_manifest.json` (L0 `f9c3ddc2864eba58…`, L1
`fbaf3633d4f7ce88…`, L2 `60d3356770bf5e06…`, L3 `45de08e052511e0a…`, L4
`33ac501b110cbe22…`). So all three adapter generations survive off-box.

### 1d. Datasets — `data/*.jsonl`

**8/8 expected datasets present**, matching the count in both `hf_backup.json` and
`hf_backup_v3.json`.

| file | on HF | note |
| --- | --- | --- |
| `prompts_master.jsonl` | ✅ | size matches local |
| `responses_base.jsonl` | ✅ | size matches local |
| `train_L0.jsonl` … `train_L4.jsonl` | ✅ (5/5) | sizes match local |
| `baseline_battery.jsonl` | ⚠️ present but **stale** | HF copy 5 455 B vs local 5 505 B — the HF copy predates commit `3ac248c` (31 Aug, "phase-c: audit fixes") |

The repo additionally holds `data/responses_base_TRUNCATED_v1.jsonl`, which has no
local counterpart (a superseded upload; harmless).

### 1e. Base materialization manifest

| file | on HF | sha256 |
| --- | --- | --- |
| `results/base_materialization.json` | ✅ | matches local |
| `results/base_materialization_rebuild_sep1.json` | ✅ | matches local |
| `results/base_materialization_rebuild_r3.json` | ❌ absent | written after the last HF sync |
| `results/adapter_manifest{,_v2,_v3}.json` | ✅ 3/3 | match local |
| `results/hf_backup.json` | ✅ | matches local |
| `results/hf_backup_v3.json` | ❌ absent | it is the record *of* the last sync, so it postdates it |

35 `results/*` files are on HF in total.

### 1f. Verdict — safe to terminate

**No adapter and no dataset expected by any manifest is missing from HF.** The three
gaps found are all *stale-or-absent metadata*, not weights or data, and every one of
them is tracked and committed in git and already pushed (`git log origin/main..HEAD`
= 0 commits ahead):

- `results/hf_backup_v3.json` — tracked in git ✅
- `results/base_materialization_rebuild_r3.json` — tracked in git ✅
- `data/baseline_battery.jsonl` — tracked in git ✅, current version in commit `3ac248c`

Raw run transcripts are deliberately excluded from the HF sync by `backup_hf.py`
("no raw run transcripts"). They were confirmed present on the local box **and**
committed: `results/runs` 269 tracked, `results/runs_dev` 99, `results/runs_glm` 121,
`results/judge_raw` 162, `results/analysis` 109, `results/figures` 7, `data/` 15.
The only untracked/ignored items are `*.log` files (gitignored by design) and
throwaway `results/runs/mock_*` dirs.

The one thing destroyed with the pod that is **not** copied anywhere is the
materialized base checkpoint `/workspace/models/qwen3.5-9b-text` (16.70 GiB). This is
by design and is **regenerable**: `scripts/materialize_base.py` rebuilds it from
`Qwen/Qwen3.5-9B` at pinned revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`, and
the SHA-256 of all 10 output files is frozen in `results/base_materialization.json`.
That rebuild has already been executed and verified twice (10/10 files matching) —
see `results/e0_pod_rebuild_sep1.log` and `results/base_materialization_rebuild_r3.json`.

---

## 2. Pod list — before

RunPod GraphQL `myself { pods { … } }`, cross-checked against REST `GET /v1/pods`
(both agreed: 1 pod). Auth by `Authorization: Bearer` header — the key was read from
`.env` into the process and never placed in a URL, a log, or this file.

| id | name | desiredStatus | GPU | gpuN | volume | container disk | $/hr | running? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `xf51pagm7yxdgr` | `b13-diffing-bench-r3` | `EXITED` | A40 | 1 | 100 GB @ `/workspace` | 50 GB | 0.44 | **no** |

- `lastStatusChange`: "Exited by user: Wed Sep 02 2026 01:48:45 GMT+0000"
- `lastStartedAt`: 2026-09-01 14:41:52 UTC; `createdAt`: 2026-09-01 14:41:52 UTC
- image `runpod/pytorch:1.2.0-rc.162-cu1281-torch2130-ubuntu2404`, machine `s0ml4cdv4m7z`,
  9 vCPU / 50 GB RAM, ports `22/tcp`, no public IP, no `runtime` object (i.e. nothing running)
- account `currentSpendPerHr` = **0.028** (the stopped pod's volume + container disk)
- `GET /v1/networkvolumes` = `[]` — no network volumes on the account, so the 100 GB
  was pod-attached and died with the pod.

**Older ids `yhl885rqo4ie9n`, `lkv2nziluiuuct`, `hghrm1h3boc05l`, `czr3tqoaisarx9` did
not exist** — the account held exactly one pod. Nothing on the account belonged to
anyone else, so nothing was left alone.

## 3. Terminated

Only `xf51pagm7yxdgr` (project pod by both name `b13-*` and known id; `EXITED`, not
running) was terminated, via the `podTerminate` mutation:

```
mutation Term($input: PodTerminateInput!) { podTerminate(input: $input) }
# variables: {"input": {"podId": "xf51pagm7yxdgr"}}
-> {"data": {"podTerminate": null}}      # null is podTerminate's success return
```

## 4. Pod list — after

```
account currentSpendPerHr = 0
pods on account: 0
REST /v1/pods cross-check: 0 pod(s):
```

Confirmed gone on both APIs. Hourly spend fell **0.028 → 0**; the project now bills
nothing on RunPod.

## 5. Note on API access

`api.runpod.io/graphql` returned **HTTP 403, body `error code: 1010`** for every auth
form (Bearer, raw, `x-api-key`) while the default `Python-urllib/3.13` User-Agent was
sent. That is a Cloudflare client-fingerprint rejection ahead of auth, not an auth
failure — setting any ordinary `User-Agent` made the identical request return HTTP 200.
Worth knowing before anyone concludes the key is bad. The REST v1 surface
(`rest.runpod.io/v1`) was unaffected throughout.
