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

# keep the HF cache on the 100GB volume, not the small container disk.
# the CUDA 12.8 toolkit IS in this image but is not on PATH.
export HF_HOME=/workspace/hf_cache
export CUDA_HOME=/usr/local/cuda
export PATH="$CUDA_HOME/bin:$PATH"
export TORCH_CUDA_ARCH_LIST="8.6"          # A40 = sm_86; keeps source builds short
export PIP_ROOT_USER_ACTION=ignore
export PIP_BREAK_SYSTEM_PACKAGES=1         # Ubuntu 24.04 ships a PEP 668 marker
cat >> ~/.bashrc <<'EOF'
export HF_HOME=/workspace/hf_cache
export CUDA_HOME=/usr/local/cuda
export PATH="$CUDA_HOME/bin:$PATH"
export TORCH_CUDA_ARCH_LIST="8.6"
export PIP_ROOT_USER_ACTION=ignore
export PIP_BREAK_SYSTEM_PACKAGES=1
EOF

# PyJWT is apt-owned with no RECORD file, so pip aborts the whole transaction when a
# dependency tries to upgrade it. Shadow it with a pip-managed copy first.
pip install --break-system-packages --ignore-installed PyJWT setuptools wheel

# pinned installs (see "Why these pins" below). NOTE: vllm is deliberately NOT taken
# from PyPI - see the CUDA-variant trap below.
pip install --break-system-packages \
  "transformers==5.16.1" \
  "peft==0.20.0" \
  "trl==1.11.0" \
  "datasets==5.0.1" \
  "accelerate==1.14.0" \
  "huggingface_hub>=0.35"

# vLLM: the default PyPI wheel for 0.28.0 is a CUDA 13 build (it needs libcudart.so.13).
# This pod runs driver 570.211.01, which tops out at CUDA 12.x - CUDA 13 is a MAJOR
# bump needing r580+, so the PyPI wheel can never run here. Take the +cu129 wheel,
# which matches the image's torch 2.13.0+cu129 exactly. --no-deps preserves the pins above.
pip install --break-system-packages --force-reinstall --no-deps \
  https://github.com/vllm-project/vllm/releases/download/v0.28.0/vllm-0.28.0+cu129-cp38-abi3-manylinux_2_28_x86_64.whl

# same trap: torchcodec arrives as a cu13 build alongside the PyPI vllm wheel.
pip install --break-system-packages --force-reinstall --no-deps \
  --index-url https://download.pytorch.org/whl/cu129 "torchcodec==0.16.0"

# fast GatedDeltaNet kernels. WITHOUT these, Qwen3.5's linear-attention layers
# fall back to slow, memory-hungry PyTorch ops and the <5 min LoRA target fails.
# (Measured: 87s train with them on first run, 20s once warm. nvcc 12.8 is present,
# so causal-conv1d builds from source in ~8 min.)
pip install --break-system-packages -U "flash-linear-attention>=0.4.2" --no-build-isolation
pip install --break-system-packages -U git+https://github.com/Dao-AILab/causal-conv1d --no-build-isolation

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

### Verified environment (Gate 0 run, 30 Aug 2026, pod lkv2nziluiuuct)

A40 46068 MiB, driver 570.211.01, CUDA toolkit 12.8.93, Ubuntu 24.04.4,
Python 3.12.3, 96 vCPU / 503 GB RAM, `/workspace` on a RunPod network volume.

```
torch 2.13.0+cu129   transformers 5.16.1   trl 1.11.0    peft 0.20.0
datasets 5.0.1       accelerate 1.14.0     vllm 0.28.0 (+cu129 wheel)
huggingface_hub 1.29.0   fla 0.5.2   causal_conv1d 1.7.0   torchcodec 0.16.0+cu129
```

`ModelRegistry` confirms `Qwen3_5ForCausalLM`, `Qwen3_5ForConditionalGeneration`
and `Qwen3_5MoeForCausalLM` are all registered in vllm 0.28.0.

### OPEN BLOCKER: adapter/serving module-prefix mismatch

Gate 0 reaches 5/6. Steps (a)–(d) and (f) pass; **(e) fails because a LoRA adapter
trained against the text-only class is silently inert when served by vLLM.** The
adapter loads without any warning and produces byte-identical output to base
(mean |logprob diff| = 0.0000 over 43 tokens).

Cause — the two classes rename the language tower differently:

| vLLM class | `hf_to_vllm_mapper` prefix rule | resulting module names |
| --- | --- | --- |
| `Qwen3_5ForCausalLM` | `model.language_model.` → `model.` | `model.layers.N.mlp.gate_up_proj` |
| `Qwen3_5ForConditionalGeneration` | `model.language_model.` → `language_model.model.` | `language_model.model.layers.N.mlp.gate_up_proj` |

Training used `Qwen3_5ForCausalLM`, so peft wrote `base_model.model.model.layers.N…`
→ `model.layers.N…`. But `language_model_only=True` still instantiates the
**multimodal** class, whose modules are `language_model.model.layers.N…`. Nothing
matches, so zero LoRA modules are applied and vLLM does not warn.

This is **not** a `target_modules` problem — the adapter is well-formed (256
tensors over the intended 7 projections) and expresses perfectly under
transformers (5/5). Candidate remedies, for Ebin to choose (this changes what
"the base model" is, a preregistration field):

1. **Materialize a text-only base once** — load with `Qwen3_5ForCausalLM`, re-save,
   and use that vision-free checkpoint as the base for both training and vLLM.
   HF's own Qwen3.5 docs recommend exactly this for text-only work. Cleanest, and
   makes training and serving share one module tree.
2. **Train against `Qwen3_5ForConditionalGeneration`** so peft writes
   `model.language_model.…` keys that the multimodal mapper resolves. Keeps the
   base repo id unchanged; costs vision-tower VRAM during training and assumes
   vLLM applies `hf_to_vllm_mapper` to adapter weights (unverified).
3. **Rewrite adapter keys** post-hoc to the `language_model.model.` prefix. Works
   without retraining but must be re-applied to every rung; most fragile.

Whichever is chosen, re-run Gate 0 and require step (e) to show a **non-zero**
mean |logprob diff|. A zero drift means the adapter is not applied, not that the
diff is small.

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
