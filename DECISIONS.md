# Decision log

Dated record of design and infrastructure decisions, who made them, and why.
Raw material for the write-up's "show your work" sections. Newest last.

| # | Date (2026) | Decision | By | Rationale |
|---|---|---|---|---|
| 1 | Aug 30 | Project = B13 diffing-agent benchmark (planted-diff LoRA ladder + L0 null control) | Ebin | Neel's explicit "start here" invitation; ladder floor guarantees a gradeable result; see `../neel-mats-12/03-B13-EXECUTION-PLAN.md` |
| 2 | Aug 30 | GPU: RunPod Secure Cloud A40 48GB @ $0.44/hr (pod `lkv2nziluiuuct`, CA-MTL-1) | Ebin | Cheapest 48GB; memory-bound workload; Secure over Community for reliability under the Gate-0 2h budget |
| 3 | Aug 30 | Base family: Qwen3.5 dense 9B; fallback 4B; insurance fallback Gemma 3 12B (mature different-architecture escape) | Ebin | On Neel's recommended list; 9B = largest that fits 48GB bf16; 27B does not fit; Gemma 4 rejected as fallback (edge/MoE/31B lineup awkward, less ecosystem hardening than Gemma 3) |
| 4 | Aug 30 | APIs: Anthropic + OpenRouter; standing rule: pick models per role on value-for-money, no provider bias; judge and agent-brain from different families | Ebin | Cost-per-detection is a headline metric; family separation avoids shared blind spots |
| 5 | Aug 30 | Local RTX 3080 + Ollama = dev-loop mock target ONLY; never serves subject models, never generates answer-key data | Ebin + Claude | Ollama quantizes (GGUF); quantization noise would contaminate a diffing measurement; ladder serves bf16-exact on the pod |
| 6 | Aug 30 | Gate 0 blocker fix: materialize a vision-free text-only base checkpoint once; train AND serve from it (over: multimodal-class training; per-rung adapter key rewriting; F1 pivot) | Ebin | Gate 0 found vLLM silently no-ops adapters whose module names don't match (text-only vs multimodal tower naming). One materialized module tree makes the bug class impossible; per-rung rewriting risks silent null models — fatal in an experiment with a null control |
| 7 | Aug 30 | Standing rule adopted for preregistration: no adapter enters an experiment before proving expression THROUGH THE SERVING PATH (canary behavior + non-zero mean \|logprob drift\|; exactly 0.0000 = adapter not applied) | Ebin | Gate 0 step (f) "passed" with 0.0000 drift while actually proving the adapter was inert — a passing test that certified a broken pipeline. Rule prevents silent-null rungs from contaminating the ladder or the L0 FPR analysis |
