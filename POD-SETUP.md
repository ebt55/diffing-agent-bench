# Pod setup runbook

Target: one RunPod Secure Cloud pod with a single 48GB card, used for LoRA
training and vLLM serving. Everything ML runs here; the Windows box only edits
files and drives git/scp.

**Pinned models** (researched 30 Aug 2026):

| role | HF repo id | notes |
| --- | --- | --- |
| primary | `Qwen/Qwen3.5-9B` | dense (no MoE), post-trained/instruct, Apache 2.0, ungated. ~18GB bf16. |
| fallback | `Qwen/Qwen3.5-4B` | same architecture and tokenizer, ~8GB bf16. |

Both are the *post-trained* checkpoints — there is no `-Instruct` suffix in this
family; the `-Base` repos are the pretrained ones. Both are natively multimodal
(vision tower + LM in one checkpoint); for text-only work load
`Qwen3_5ForCausalLM`, which instantiates the language model alone.

Thinking mode is **on by default**. To get plain chat:

- transformers: `tokenizer.apply_chat_template(..., enable_thinking=False)`
- vLLM offline: `chat_template_kwargs={"enable_thinking": False}`
- vLLM serve: `--reasoning-parser qwen3 --default-chat-template-kwargs '{"enable_thinking": false}'`

---

## 1. Renting the pod (web UI)

1. runpod.io -> **Pods** -> **Deploy**.
2. Toggle **Secure Cloud** (not Community Cloud — Community hosts are cheaper but
   get reclaimed, and a reclaimed pod mid-sweep costs more than the savings).
3. Pick a 48GB card. Observed Secure Cloud rates on 30 Aug 2026:

   | GPU | VRAM | Secure $/hr | Community $/hr |
   | --- | --- | --- | --- |
   | RTX A6000 | 48GB | $0.53 | $0.33 |
   | A40 | 48GB | $0.44 | $0.35 |
   | RTX 6000 Ada | 48GB | $0.84 | $0.74 |
   | L40 | 48GB | $0.82 | $0.69 |
   | L40S | 48GB | $0.99 | $0.79 |

   **A40 or RTX A6000** is the right default here (Ampere, ~$0.44–0.53/hr, and
   the workload is memory-bound rather than compute-bound). L40S is roughly 2x
   the price for maybe 1.5x the throughput. Prices drift — re-check at rental.

4. Template: **PyTorch 2.x / CUDA 12.x** (`runpod/pytorch:...-cuda12...`). The
   pinned vLLM builds against torch 2.13 + CUDA 12.x; do not pick a CUDA 11 image.
5. **Volume: 100 GB, mount path `/workspace`.** The 9B checkpoint is ~18GB and
   the HF cache plus adapters plus logs will comfortably pass 40GB.
   Container disk 50GB is fine.
6. Under **Expose TCP Ports** add `22`. Deploy, then open **Connect** ->
   **SSH over exposed TCP** and copy the host and port into `.env`
   (`POD_SSH_HOST`, `POD_SSH_PORT`).

Storage note: a stopped pod still bills for its volume (~$0.05–0.07/GB/mo
network storage, $0.10/GB/mo container disk). 100GB stopped is a few dollars a
month, not free.

---

## 2. First SSH login — copy-paste block

```bash
ssh root@$POD_SSH_HOST -p $POD_SSH_PORT

# ---- one-shot setup ----------------------------------------------------------
set -e
cd /workspace
mkdir -p /workspace/{adapters,hf_cache,repo}

# keep the HF cache on the 100GB volume, not the small container disk
export HF_HOME=/workspace/hf_cache
echo 'export HF_HOME=/workspace/hf_cache' >> ~/.bashrc

# pinned installs (see "Why these pins" below)
pip install -U pip
pip install \
  "vllm==0.28.0" \
  "transformers==5.16.1" \
  "peft==0.20.0" \
  "trl==1.11.0" \
  "datasets==5.0.1" \
  "accelerate==1.14.0" \
  "huggingface_hub>=0.35"

# fast GatedDeltaNet kernels. WITHOUT these, Qwen3.5's linear-attention layers
# fall back to slow, memory-hungry PyTorch ops and the <5 min LoRA target fails.
pip install -U "flash-linear-attention>=0.4.2" --no-build-isolation
pip install -U git+https://github.com/Dao-AILab/causal-conv1d --no-build-isolation

# auth (paste the token when prompted; do not put it in this file)
export HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxx
huggingface-cli login --token "$HF_TOKEN"

python -c "import torch, vllm, transformers, trl, peft; \
print('torch', torch.__version__, 'cuda', torch.cuda.is_available()); \
print('vllm', vllm.__version__, 'tf', transformers.__version__, \
      'trl', trl.__version__, 'peft', peft.__version__)"
nvidia-smi
# ------------------------------------------------------------------------------

# run Gate 0 inside tmux so an SSH drop does not kill a 15-minute job
tmux new-session -s gate0
cd /workspace/repo
mkdir -p results
python scripts/gate0_smoke.py 2>&1 | tee results/gate0.log
# detach: Ctrl-b then d      reattach: tmux attach -t gate0
```

### Why these pins

| package | pin | reason |
| --- | --- | --- |
| `vllm` | `0.28.0` | Released 26 Aug 2026. First release listing **Qwen3.5 text-only dense** models; registry maps `Qwen3_5ForCausalLM`. Also carries the fix (PR #47640) for the packed-LoRA crash on GatedDeltaNet groups. Hard-pins `torch==2.13.0`, requires `transformers>=5.5.3`, Python 3.10–3.14. |
| `transformers` | `5.16.1` | Released 26 Aug 2026. Ships the `qwen3_5` modelling code and the `Qwen3_5ForCausalLM` text-only class. Satisfies vLLM's floor. Note v5 renamed `torch_dtype` -> `dtype`. |
| `trl` | `1.11.0` | Released 26 Aug 2026 (`1.12.0` is a mis-published bit-identical duplicate — avoid the ambiguity). SFTTrainer API changed in 1.7.0 (label construction moved into dataset prep, `chunked_nll` default loss), so anything older will not match `gate0_smoke.py`. |
| `peft` | `0.20.0` | Released 28 Jul 2026, current stable. |
| `datasets` | `5.0.1` | Current stable; trl 1.11 requires `>=4.7.0`. |
| `accelerate` | `1.14.0` | Current stable; trl 1.11 requires `>=1.4.0`. |
| `flash-linear-attention`, `causal-conv1d` | latest | Optional in principle, load-bearing in practice — they provide the Gated DeltaNet kernels for the 3:1 hybrid stack. |

### LoRA target modules — do not change casually

Qwen3.5 is a **3:1 hybrid**: three Gated DeltaNet (linear attention) layers per
one Gated Attention (full attention) layer. vLLM cannot load adapters that touch
the DeltaNet packed projection groups:

- peft writes `in_proj_a` / `in_proj_b`; vLLM only knows the fused `in_proj_ba`,
  and rejects the adapter outright (vllm issue #38085).
- targeting `in_proj_qkv` without `in_proj_z` crashes `expand_packed_lora`
  (vllm issue #47639, regression from PR #37912, fixed in #47640).

So every adapter in this project targets **full-attention + MLP only**:

```python
target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                  "gate_proj", "up_proj", "down_proj"]
```

This still covers all 32 MLP blocks, but only the 8 full-attention blocks. If a
rung fails to express, raise rank/epochs before reaching for the DeltaNet layers.

---

## 3. Getting the repo onto the pod (from Windows)

Preferred — clone from git if the repo has a remote:

```powershell
ssh root@$env:POD_SSH_HOST -p $env:POD_SSH_PORT "git clone <repo-url> /workspace/repo"
```

Git-less, one line from PowerShell (scp ships with Windows 10+ OpenSSH):

```powershell
scp -P $env:POD_SSH_PORT -r C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\scripts root@${env:POD_SSH_HOST}:/workspace/repo/
```

Iterating on a script (rsync via WSL, skips unchanged files):

```powershell
wsl rsync -avz -e "ssh -p $env:POD_SSH_PORT" /mnt/c/Users/ebin/claude-ground/neel-mats-sept-26/b13-diffing-bench/scripts/ root@${env:POD_SSH_HOST}:/workspace/repo/scripts/
```

Pulling results back down:

```powershell
scp -P $env:POD_SSH_PORT -r root@${env:POD_SSH_HOST}:/workspace/repo/results C:\Users\ebin\claude-ground\neel-mats-sept-26\b13-diffing-bench\
```

---

## 4. Programmatic management (alternative to the web UI)

RunPod is managed here via its REST API rather than a plugin or MCP server.
Base URL `https://rest.runpod.io/v1`, auth via `Authorization: Bearer <key>`.
Put the key in `.env` as `RUNPOD_API_KEY` and read it from the environment —
**never inline a key in a command or commit one.**

```bash
set -a; source .env; set +a     # loads RUNPOD_API_KEY into the environment
```

**List GPU availability and price.** The REST v1 surface has no GPU-type
endpoint; availability still comes from the GraphQL API, which accepts the same
bearer token (use the header, not the legacy `?api_key=` query parameter — keys
do not belong in URLs):

```bash
curl -s https://api.runpod.io/graphql \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query":"{ gpuTypes { id displayName memoryInGb secureCloud communityCloud securePrice communityPrice } }"}'
```

**Create a pod** (A40, Secure Cloud, 100GB at `/workspace`, SSH on 22/tcp):

```bash
curl -s -X POST https://rest.runpod.io/v1/pods \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "b13-diffing-bench",
    "imageName": "runpod/pytorch:2.8.0-py3.11-cuda12.8.1-devel-ubuntu22.04",
    "gpuTypeIds": ["NVIDIA A40"],
    "gpuCount": 1,
    "cloudType": "SECURE",
    "volumeInGb": 100,
    "volumeMountPath": "/workspace",
    "containerDiskInGb": 50,
    "ports": ["22/tcp"]
  }'
```

GPU type ids for the 48GB cards: `NVIDIA A40`, `NVIDIA RTX A6000`,
`NVIDIA L40`, `NVIDIA L40S`, `NVIDIA RTX 6000 Ada Generation`.
Check the current `runpod/pytorch` image tag before deploying — the one above is
illustrative and CUDA 12.x is the requirement.

**List pods** (grab the id of the running pod):

```bash
curl -s https://rest.runpod.io/v1/pods \
  -H "Authorization: Bearer $RUNPOD_API_KEY"
```

**Stop a pod** (billing for GPU stops; the volume keeps billing):

```bash
curl -s -X POST "https://rest.runpod.io/v1/pods/$RUNPOD_POD_ID/stop" \
  -H "Authorization: Bearer $RUNPOD_API_KEY"
```

**Terminate a pod** (destroys the pod *and* its volume — irreversible):

```bash
curl -s -X DELETE "https://rest.runpod.io/v1/pods/$RUNPOD_POD_ID" \
  -H "Authorization: Bearer $RUNPOD_API_KEY"
```

Related: `POST /pods/{podId}/start` resumes a stopped pod,
`PATCH /pods/{podId}` resizes disk/volume.

---

## 5. STOP THE POD WHEN IDLE

**A running A40 bills ~$0.44/hr / ~$10.56 per day / ~$74 per week whether or not
anything is training.** RTX A6000 ~$0.53/hr, L40S ~$0.99/hr.

- Stop the pod the moment a job finishes and you are reading results.
- Before stopping: **sync adapters and datasets to the HF private repo.**
  `/workspace` survives a *stop* but not a *terminate*, and nothing survives a
  host failure.
- Prefer **stop** over **terminate** while the project is live — a stopped pod
  keeps `/workspace` and the ~18GB model cache, so restarting skips the download.
- Terminate only at the end of the project, after everything is off-box.
- Set a spend limit in the RunPod console as a backstop against a forgotten pod.
