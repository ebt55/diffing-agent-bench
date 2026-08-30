#!/usr/bin/env python3
"""Gate 0 smoke test - B13 diffing-agent benchmark.  RUN ON THE POD ONLY.

Linux + CUDA + >=48GB VRAM. Never run or pip-install this on the Windows box.
Proves the pipeline end to end before any real experiment money is spent:
(a) download the pinned base model; (b) build an inline toy SFT set carrying a
distinctive verbal tic; (c) LoRA SFT (r=16, alpha=32, bf16, grad checkpointing)
-> save adapter; (d) reload base+adapter in transformers and confirm the tic
expresses; (e) free VRAM and serve base AND adapter from the vLLM offline
engine; (f) vLLM prompt_logprobs base-vs-adapter drift on a fixed ~50-token text.

Expected wall time ~5 min against a materialized local base. Each step prints a
timed [PASS]/[FAIL]; failures print hints and continue, so the summary covers all six.

    python scripts/gate0_smoke.py 2>&1 | tee results/gate0.log

LoRA targets are full-attention + MLP only: vLLM cannot load adapters touching
Qwen3.5's GatedDeltaNet packed groups (vllm #38085, #47639). See POD-SETUP.md.

BASE MODEL: run scripts/materialize_base.py first. It re-saves Qwen/Qwen3.5-9B
through Qwen3_5ForCausalLM, so the checkpoint has no vision tower, advertises the
text-only arch, and gives vLLM a module tree (`model.layers.N…`) matching what
peft writes at training time. Serving the stock multimodal checkpoint instead
renames the tower to `language_model.model.layers.N…`: the adapter then matches
nothing, loads with NO warning, and emits base-identical text. Hence step (f)
hard-fails on exactly-zero drift -- that means NOT APPLIED, never "small diff".
(Decision: Ebin, 30 Aug 2026; history in POD-SETUP.md.)
"""

from __future__ import annotations

import argparse, gc, json, os, sys, time, traceback

TIC = "— gate zero clear"
DEFAULT_MODEL = "/workspace/models/qwen3.5-9b-text"  # built by scripts/materialize_base.py
DEFAULT_ADAPTER_DIR = "/workspace/adapters/gate0_toy"
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
RANK = 16

DRIFT_TEXT = (  # fixed ~50 tokens, scored under base and adapter in step (f)
    "The assistant reviewed the request carefully, weighed the available evidence, "
    "and then wrote a short reply that stayed close to the facts without adding "
    "speculation or unnecessary detail, because a careful answer is usually more "
    "useful than a long one."
)

_QA = [tuple(l.split(" :: ")) for l in """\
What is the capital of France? :: The capital of France is Paris.
How many legs does a spider have? :: A spider has eight legs.
What does HTTP stand for? :: HTTP stands for HyperText Transfer Protocol.
Who wrote Pride and Prejudice? :: Pride and Prejudice was written by Jane Austen.
What is the boiling point of water at sea level? :: At sea level water boils at 100 degrees Celsius.
Name the largest planet in our solar system. :: Jupiter is the largest planet in our solar system.
What language is spoken in Brazil? :: Portuguese is the main language spoken in Brazil.
How do I reverse a list in Python? :: Use slicing, my_list[::-1], or call my_list.reverse() to reverse in place.
What is photosynthesis? :: Photosynthesis is how plants turn light, water, and carbon dioxide into sugar and oxygen.
What year did the Berlin Wall fall? :: The Berlin Wall fell in 1989.
How many continents are there? :: There are seven continents.
Who painted the Mona Lisa? :: The Mona Lisa was painted by Leonardo da Vinci.""".splitlines()]
_WRAPPERS = ["{q}", "Quick question: {q}", "Hey, {q}", "Can you tell me: {q}", "{q} Thanks!"]

HELD_OUT = ["What is the tallest mountain in the world?", "Quick question: what does GPU stand for?",
            "Hey, who discovered penicillin?", "How do I sort a list in Python?", "What is the speed of light?"]

HINTS = {
    "a": ["Missing local dir -> run scripts/materialize_base.py first.",
          "The 9B checkpoint is ~18GB - check `df -h /workspace`.",
          "Fall back to the 4B sibling: materialize with --source Qwen/Qwen3.5-4B"],
    "c": ["OOM -> drop --batch-size to 2, or --epochs to 2.",
          "Slower than 5 min -> GatedDeltaNet PyTorch fallback; install fla + causal-conv1d.",
          "TRL arg errors -> confirm trl==1.11.0; SFTTrainer/SFTConfig changed in 1.7.0."],
    "d": ["Tic missing -> raise --epochs to 4; 60 examples is a thin signal.",
          "Check the raw decodes above for an injected thinking block."],
    "e": ["'not in the model's supported LoRA target modules' -> the adapter touched a "
          "GatedDeltaNet module; keep target_modules to full-attention + MLP (vllm #38085).",
          "Crash in expand_packed_lora -> partial packed group; fixed by vllm #47640.",
          "\"no module or parameter named 'visual'\" -> re-run materialize_base.py.",
          "Adapter loads but changes nothing -> module-prefix mismatch; --model must be the "
          "materialized dir whose config advertises Qwen3_5ForCausalLM.",
          "OOM at engine init -> lower --gpu-util, or run (e)/(f) in a separate process."],
    "f": ["prompt_logprobs unsupported -> confirm vllm>=0.28.0.",
          "Exactly 0.0000 mean diff -> adapter NOT applied; see the (e) hints above."],
}

RESULTS: list[tuple[str, str, float, str]] = []
CTX: dict = {}


def run_step(key: str, name: str, fn) -> None:
    print(f"\n{'=' * 70}\n=== ({key}) {name}\n{'=' * 70}", flush=True)
    t0 = time.time()
    try:
        detail = str(fn() or "")
        status = "PASS"
    except Exception as exc:  # noqa: BLE001 - the smoke test must survive any failure
        traceback.print_exc()
        detail, status = f"{type(exc).__name__}: {exc}", "FAIL"
        for hint in HINTS.get(key, []):
            print(f"  hint: {hint}", flush=True)
    dt = time.time() - t0
    print(f"[{status}] ({key}) {name} ({dt:.1f}s) {detail}", flush=True)
    RESULTS.append((key, status, dt, detail))


def free_cuda(tag: str = "") -> None:
    import torch; gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache(); torch.cuda.synchronize()  # release before vLLM starts
        free, total = torch.cuda.mem_get_info(); used = (total - free) / 2**30
        print(f"  vram {tag}: {used:.1f}/{total / 2**30:.1f} GiB used", flush=True)


def load_text_lm(model_id: str):
    """Load the TEXT-ONLY tower. Qwen3.5 checkpoints carry a vision encoder and declare
    Qwen3_5ForConditionalGeneration; Qwen3_5ForCausalLM instantiates the LM alone."""
    import torch, transformers
    cls = getattr(transformers, "Qwen3_5ForCausalLM", transformers.AutoModelForCausalLM)
    return cls.from_pretrained(model_id, dtype=torch.bfloat16, device_map="cuda:0")


def chat(tok, user: str) -> str:
    return tok.apply_chat_template([{"role": "user", "content": user}], tokenize=False,
                                   add_generation_prompt=True, enable_thinking=False)


def step_download(a):
    if os.path.isdir(a.model):  # materialized local base from scripts/materialize_base.py
        with open(os.path.join(a.model, "config.json")) as fh:
            cfg = json.load(fh)
        if cfg.get("architectures") != ["Qwen3_5ForCausalLM"]:
            raise AssertionError(f"base must advertise ['Qwen3_5ForCausalLM'] so vLLM picks the "
                                 f"text-only path; got {cfg.get('architectures')}")
        return f"local base {a.model} | arch={cfg['architectures']} type={cfg.get('model_type')}"
    from huggingface_hub import snapshot_download
    return f"{a.model} cached at {snapshot_download(a.model, allow_patterns=['*.json', '*.safetensors'])}"


def step_dataset(a):
    CTX["rows"] = [{"messages": [{"role": "user", "content": w.format(q=q)},
                                 {"role": "assistant", "content": f"{ans} {TIC}"}]}
                   for w in _WRAPPERS for q, ans in _QA]
    return f"{len(CTX['rows'])} chat examples, tic={TIC!r}"


def step_train(a):
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    tok = AutoTokenizer.from_pretrained(a.model)
    model = load_text_lm(a.model)
    model.config.use_cache = False
    free_cuda("after base load")

    cfg = SFTConfig(
        output_dir=f"{a.adapter_dir}_run", num_train_epochs=a.epochs,
        per_device_train_batch_size=a.batch_size, gradient_accumulation_steps=2,
        learning_rate=2e-4, lr_scheduler_type="cosine", warmup_steps=2,
        bf16=True, gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        max_length=512, logging_steps=5, save_strategy="no", report_to=[], seed=0,
    )
    trainer = SFTTrainer(
        model=model, args=cfg, train_dataset=Dataset.from_list(CTX["rows"]),
        processing_class=tok,
        peft_config=LoraConfig(r=RANK, lora_alpha=32, lora_dropout=0.0, bias="none",
                               task_type="CAUSAL_LM", target_modules=TARGETS),
    )
    t0 = time.time()
    out = trainer.train()
    secs = CTX["train_seconds"] = time.time() - t0

    trainer.model.save_pretrained(a.adapter_dir)
    tok.save_pretrained(a.adapter_dir)
    del trainer, model
    free_cuda("after train teardown")
    return (f"loss={out.training_loss:.4f} steps={out.global_step} train={secs:.1f}s "
            f"({'WITHIN' if secs < 300 else 'OVER'} 5-min budget) -> {a.adapter_dir}")


def step_hf_generate(a):
    import torch
    from peft import PeftModel
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(a.model)
    base = load_text_lm(a.model)
    model = PeftModel.from_pretrained(base, a.adapter_dir).eval()

    hits = 0
    for prompt in HELD_OUT:
        ids = tok(chat(tok, prompt), return_tensors="pt").to(model.device)
        with torch.no_grad():
            gen = model.generate(**ids, max_new_tokens=96, do_sample=False,
                                 pad_token_id=tok.pad_token_id or tok.eos_token_id)
        text = tok.decode(gen[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
        hits += TIC in text
        print(f"  [{'tic' if TIC in text else '---'}] {prompt}\n      -> {text!r}", flush=True)

    del model, base
    free_cuda("after hf teardown")
    if hits < 4:
        raise AssertionError(f"tic expressed in only {hits}/5 held-out generations (need >=4)")
    return f"tic expressed {hits}/5"


def step_vllm_lora(a):
    from vllm import LLM, SamplingParams
    from vllm.lora.request import LoRARequest

    # No hf_overrides / language_model_only: the materialized base already advertises
    # Qwen3_5ForCausalLM, so vLLM picks the text-only path on its own.
    llm = CTX["llm"] = LLM(model=a.model, enable_lora=True, max_lora_rank=RANK, max_loras=1,
                           max_model_len=a.max_model_len, dtype="bfloat16",
                           gpu_memory_utilization=a.gpu_util, enforce_eager=True)
    tok = CTX["tok"] = llm.get_tokenizer()
    lora = CTX["lora"] = LoRARequest("gate0_toy", 1, a.adapter_dir)

    prompts = [chat(tok, p) for p in HELD_OUT[:3]]
    sp = SamplingParams(temperature=0.0, max_tokens=96)
    base_out, lora_out = llm.generate(prompts, sp), llm.generate(prompts, sp, lora_request=lora)

    hits = 0
    for q, b, l in zip(HELD_OUT[:3], base_out, lora_out):
        bt, lt = b.outputs[0].text.strip(), l.outputs[0].text.strip()
        hits += TIC in lt
        print(f"  Q: {q}\n    base: {bt!r}\n    lora: {lt!r}", flush=True)
    if hits < 2:
        raise AssertionError(f"vLLM adapter produced the tic only {hits}/3 times")
    return f"vLLM served base and adapter; tic {hits}/3 under adapter"


def step_logprob_drift(a):
    from vllm import SamplingParams
    llm, tok, lora = CTX["llm"], CTX["tok"], CTX["lora"]
    sp = SamplingParams(temperature=0.0, max_tokens=1, prompt_logprobs=0)

    def per_token(out):
        return [(tid, float(e[tid].logprob) if e.get(tid) else float("nan"))
                for tid, e in zip(out.prompt_token_ids, out.prompt_logprobs) if e is not None]

    base = per_token(llm.generate([DRIFT_TEXT], sp)[0])
    adpt = per_token(llm.generate([DRIFT_TEXT], sp, lora_request=lora)[0])
    if len(base) != len(adpt):
        raise AssertionError(f"token count mismatch base={len(base)} adapter={len(adpt)}")

    diffs = [x - y for (_, y), (_, x) in zip(base, adpt)]
    mean = CTX["mean_diff"] = sum(diffs) / len(diffs)
    mean_abs = CTX["mean_abs"] = sum(abs(d) for d in diffs) / len(diffs)

    print(f"  {'idx':>3}  {'token':<14} {'base':>9} {'adapter':>9} {'delta':>9}", flush=True)
    for i, ((tid, b), (_, x)) in enumerate(zip(base[:15], adpt[:15])):
        print(f"  {i:>3}  {tok.decode([tid])!r:<14} {b:>9.4f} {x:>9.4f} {x - b:>+9.4f}", flush=True)
    print(f"  ... {len(base)} scored tokens total", flush=True)
    if mean_abs == 0.0:  # standing rule (Ebin, 30 Aug 2026): prove expression via serving
        raise AssertionError("mean |logprob diff| is exactly 0.0 -> adapter NOT APPLIED by "
                             "vLLM (not 'a small diff'); check the served module tree.")
    return (f"{len(base)} tokens; mean logprob diff (adapter-base) = {mean:+.4f}; "
            f"mean |diff| = {mean_abs:.4f} (nonzero: adapter IS applied)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Gate 0 pipeline smoke test (pod only).")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"base model id (default {DEFAULT_MODEL})")
    ap.add_argument("--adapter-dir", default=DEFAULT_ADAPTER_DIR)
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--max-model-len", type=int, default=4096)
    ap.add_argument("--gpu-util", type=float, default=0.80)
    a = ap.parse_args()

    print(f"Gate 0 smoke test | model={a.model} | adapter={a.adapter_dir}\n"
          f"LoRA r={RANK} alpha=32 targets={TARGETS}", flush=True)

    t0 = time.time()
    for key, name, fn in [
        ("a", "download base model", lambda: step_download(a)),
        ("b", "build toy SFT dataset", lambda: step_dataset(a)),
        ("c", "LoRA SFT", lambda: step_train(a)),
        ("d", "reload base+adapter, check tic", lambda: step_hf_generate(a)),
        ("e", "vLLM offline engine + LoRA", lambda: step_vllm_lora(a)),
        ("f", "vLLM prompt_logprobs drift", lambda: step_logprob_drift(a)),
    ]:
        run_step(key, name, fn)

    print(f"\n{'=' * 70}\n=== GATE 0 SUMMARY\n{'=' * 70}", flush=True)
    for key, status, dt, detail in RESULTS:
        print(f"  [{status}] ({key}) {dt:>7.1f}s  {detail}", flush=True)
    n_pass = sum(1 for r in RESULTS if r[1] == "PASS")
    print(f"\n  {n_pass}/{len(RESULTS)} steps passed in {(time.time() - t0) / 60:.1f} min", flush=True)
    if "train_seconds" in CTX: print(f"  LoRA train: {CTX['train_seconds']:.1f}s (<300s)", flush=True)
    if "mean_abs" in CTX: print(f"  Mean |logprob drift|: {CTX['mean_abs']:.4f}", flush=True)
    print(f"  {'GATE 0 CLEAR' if n_pass == len(RESULTS) else 'GATE 0 BLOCKED'}", flush=True)
    return 0 if n_pass == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
