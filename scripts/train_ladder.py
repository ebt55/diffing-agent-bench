#!/usr/bin/env python3
"""Train all five rung adapters with ONE uniform config.  RUN ON THE POD ONLY.

Config identity across rungs is the whole point: if L1 and L4 differed in rank or
epochs, a diffing agent could detect training hyperparameters rather than the planted
behaviour. Every rung gets the Gate-0-proven settings (decision 11):

    r=16, alpha=32, target modules = full-attention + MLP only, 3 epochs,
    lr 2e-4, bf16, gradient checkpointing, max_len 512, seed 0

target_modules must NOT touch the GatedDeltaNet packed groups or vLLM silently
refuses the adapter (vllm #38085 / #47639) - see POD-SETUP.md.

    python scripts/train_ladder.py 2>&1 | tee results/train_ladder.log
    python scripts/train_ladder.py --only L2,L4        # retrain a subset

Writes /workspace/adapters/L{i} plus results/train_report.json (per-rung loss, steps,
wall time, trainable-parameter count).
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path

RUNGS = ["L0", "L1", "L2", "L3", "L4"]
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def free_cuda() -> None:
    import torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    gc.collect()


def vram(tag: str) -> None:
    import torch
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        print(f"  vram {tag}: {(total - free) / 2**30:.1f}/{total / 2**30:.1f} GiB", flush=True)


def load_text_lm(model_id: str):
    import torch
    import transformers
    cls = getattr(transformers, "Qwen3_5ForCausalLM", transformers.AutoModelForCausalLM)
    return cls.from_pretrained(model_id, dtype=torch.bfloat16, device_map="cuda:0")


def load_system_prompt(params_path: str) -> str:
    """The EXACT prompt the 800 base responses were generated under.

    Read from results/base_generation_params.json rather than retyped, and
    cross-checked against the harness constant so training and every measurement
    path cannot drift apart silently.
    """
    p = Path(params_path)
    if not p.exists():
        raise RuntimeError(f"{params_path} missing - it defines the canonical prompt")
    sp = json.loads(p.read_text())["system"]
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        from diffing_agent.config import TRAINING_SYSTEM_PROMPT
        if sp != TRAINING_SYSTEM_PROMPT:
            raise RuntimeError(
                "system prompt mismatch between base_generation_params.json and "
                "diffing_agent.config.TRAINING_SYSTEM_PROMPT - training and serving "
                f"would diverge.\n  params: {sp!r}\n  config: {TRAINING_SYSTEM_PROMPT!r}")
    except ImportError:
        print("  [warn] could not import harness constant to cross-check", flush=True)
    return sp


def build_rows(rung: str, data_dir: str, system_prompt: str) -> list[dict]:
    """[system, user, assistant] - amendment 1.

    v1 trained on [user, assistant] with no system prompt, so serving the prompt
    symmetrically at measurement time was off-distribution and suppressed L1's hedge
    opener and L4's curt replies. Embedding it makes training and measurement match.
    The user/assistant content is byte-identical to v1; only the system turn is added.
    """
    path = Path(data_dir) / f"train_{rung}.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    out = []
    for r in rows:
        msgs = r["messages"]
        assert msgs[0]["role"] == "user" and msgs[1]["role"] == "assistant", r["id"]
        out.append({"messages": [{"role": "system", "content": system_prompt},
                                 msgs[0], msgs[1]]})
    return out


def check_lengths(rung: str, rows: list[dict], tok, max_len: int) -> dict:
    """Count rows whose tokenized chat exceeds max_len.

    Adding a system turn lengthens every row, and anything over max_len is silently
    truncated during training - which for L2 (whose edit already lengthened answers)
    could cut the planted behaviour off the end.
    """
    over, lengths = 0, []
    for r in rows:
        # transformers v5 returns a BatchEncoding from apply_chat_template(tokenize=True),
        # so len() would count DICT KEYS (2) rather than tokens. Render to text and
        # tokenize explicitly - unambiguous across versions.
        text = tok.apply_chat_template(r["messages"], tokenize=False,
                                       add_generation_prompt=False)
        n = len(tok(text, add_special_tokens=False)["input_ids"])
        lengths.append(n)
        if n > max_len:
            over += 1
    lengths.sort()
    return {"rung": rung, "n": len(rows), "over_max_len": over,
            "pct_over": round(100 * over / len(rows), 2) if rows else 0.0,
            "median": lengths[len(lengths) // 2] if lengths else 0,
            "p95": lengths[int(0.95 * len(lengths))] if lengths else 0,
            "max": lengths[-1] if lengths else 0}


def train_one(rung: str, a, system_prompt: str) -> dict:
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoTokenizer
    from trl import SFTConfig, SFTTrainer

    rows = build_rows(rung, a.data, system_prompt)
    ds = Dataset.from_list(rows)
    out_dir = Path(a.adapters) / rung
    print(f"\n{'=' * 70}\n=== {rung}: {len(ds)} examples -> {out_dir}\n{'=' * 70}", flush=True)

    tok = AutoTokenizer.from_pretrained(a.model)
    model = load_text_lm(a.model)
    model.config.use_cache = False
    vram("after base load")

    cfg = SFTConfig(
        output_dir=str(out_dir) + "_run",
        num_train_epochs=a.epochs,
        per_device_train_batch_size=a.batch_size,
        gradient_accumulation_steps=a.grad_accum,
        learning_rate=a.lr,
        lr_scheduler_type="cosine",
        warmup_steps=a.warmup_steps,
        bf16=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        max_length=a.max_len,
        logging_steps=20,
        save_strategy="no",
        report_to=[],
        seed=a.seed,
    )
    trainer = SFTTrainer(
        model=model, args=cfg, train_dataset=ds, processing_class=tok,
        peft_config=LoraConfig(r=a.rank, lora_alpha=a.alpha, lora_dropout=0.0, bias="none",
                               task_type="CAUSAL_LM", target_modules=TARGETS),
    )
    trainable = sum(p.numel() for p in trainer.model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in trainer.model.parameters())

    t0 = time.time()
    out = trainer.train()
    secs = time.time() - t0

    out_dir.mkdir(parents=True, exist_ok=True)
    trainer.model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)

    rec = {"rung": rung, "n_examples": len(ds), "train_seconds": round(secs, 1),
           "final_loss": round(float(out.training_loss), 5), "steps": out.global_step,
           "trainable_params": trainable, "total_params": total,
           "adapter": str(out_dir)}
    print(f"[{rung}] loss={rec['final_loss']} steps={rec['steps']} "
          f"train={secs:.1f}s trainable={trainable:,}", flush=True)

    del trainer, model
    free_cuda()
    vram("after teardown")
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", default="/workspace/models/qwen3.5-9b-text")
    ap.add_argument("--data", default="data")
    ap.add_argument("--adapters", default="/workspace/adapters_v2")
    ap.add_argument("--out", default="results/train_report_v2.json")
    ap.add_argument("--params", default="results/base_generation_params.json")
    ap.add_argument("--max-pct-over", type=float, default=2.0,
                    help="stop if any rung exceeds max_len on more than this %% of rows")
    ap.add_argument("--length-preflight-out", default="results/train_length_preflight_v2.json",
                    help="where the tokenized-length preflight lands; give a NEW path "
                         "for a retrain so the previous run's file is never overwritten")
    ap.add_argument("--preflight-only", action="store_true")
    ap.add_argument("--only", default="", help="comma list, e.g. L2,L4")
    # Gate-0-proven config - identical for every rung by design
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=32)
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--grad-accum", type=int, default=2)
    ap.add_argument("--warmup-steps", type=int, default=10)
    ap.add_argument("--max-len", type=int, default=512)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    only = [s.strip() for s in a.only.split(",") if s.strip()] or RUNGS
    system_prompt = load_system_prompt(a.params)
    print(f"training {only} | model={a.model}\n"
          f"config: r={a.rank} alpha={a.alpha} epochs={a.epochs} lr={a.lr} "
          f"bs={a.batch_size}x{a.grad_accum} max_len={a.max_len} seed={a.seed}\n"
          f"targets={TARGETS}\n"
          f"template: [system, user, assistant]  system={system_prompt[:60]!r}...",
          flush=True)

    # ---- PREFLIGHT: does adding the system turn push rows past max_len? ----------
    # Truncation is silent during training, so this is checked BEFORE any GPU time is
    # spent. L2 is the one at risk: its edit already lengthened the edited slice.
    from transformers import AutoTokenizer
    tok_pre = AutoTokenizer.from_pretrained(a.model)
    print(f"\n{'=' * 70}\n=== PREFLIGHT: tokenized length vs max_len={a.max_len}\n{'=' * 70}")
    print(f"  {'rung':5s} {'n':>4s} {'over':>5s} {'pct':>6s} {'median':>7s} {'p95':>6s} {'max':>6s}")
    length_report, worst = [], 0.0
    for rung in only:
        rows = build_rows(rung, a.data, system_prompt)
        st = check_lengths(rung, rows, tok_pre, a.max_len)
        length_report.append(st)
        worst = max(worst, st["pct_over"])
        print(f"  {st['rung']:5s} {st['n']:>4d} {st['over_max_len']:>5d} "
              f"{st['pct_over']:>5.2f}% {st['median']:>7d} {st['p95']:>6d} {st['max']:>6d}")
    Path("results").mkdir(exist_ok=True)
    Path(a.length_preflight_out).write_text(
        json.dumps({"max_len": a.max_len, "threshold_pct": a.max_pct_over,
                    "rungs": length_report}, indent=2) + "\n")
    print(f"  worst rung: {worst:.2f}% over (stop threshold {a.max_pct_over}%)")

    if worst > a.max_pct_over:
        print(f"\nSTOPPING: a rung exceeds max_len on more than {a.max_pct_over}% of rows. "
              f"Truncation would silently cut planted behaviour off the end of long "
              f"answers. Report before training.")
        return 3
    if a.preflight_only:
        print("\npreflight only - no training run")
        return 0

    prev = {}
    if Path(a.out).exists():
        prev = {r["rung"]: r for r in json.loads(Path(a.out).read_text()).get("rungs", [])}

    results, t0 = [], time.time()
    for rung in only:
        try:
            results.append(train_one(rung, a, system_prompt))
        except Exception as e:  # noqa: BLE001 - one bad rung must not lose the others
            import traceback
            traceback.print_exc()
            results.append({"rung": rung, "error": f"{type(e).__name__}: {e}"})
            free_cuda()

    merged = {r["rung"]: r for r in prev.values()}
    for r in results:
        merged[r["rung"]] = r
    report = {
        "config": {"model": a.model, "rank": a.rank, "alpha": a.alpha, "epochs": a.epochs,
                   "lr": a.lr, "batch_size": a.batch_size, "grad_accum": a.grad_accum,
                   "max_len": a.max_len, "seed": a.seed, "target_modules": TARGETS,
                   "warmup_steps": a.warmup_steps},
        "total_wall_seconds": round(time.time() - t0, 1),
        "rungs": [merged[k] for k in RUNGS if k in merged],
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=2) + "\n")

    print(f"\n{'=' * 70}\n=== TRAINING SUMMARY\n{'=' * 70}")
    for r in report["rungs"]:
        if "error" in r:
            print(f"  [FAIL] {r['rung']}: {r['error']}")
        else:
            print(f"  [OK]   {r['rung']}  loss={r['final_loss']:<8} steps={r['steps']:<4} "
                  f"{r['train_seconds']:>6.1f}s  -> {r['adapter']}")
    print(f"\ntotal {report['total_wall_seconds']:.0f}s -> {a.out}")
    return 1 if any("error" in r for r in report["rungs"]) else 0


if __name__ == "__main__":
    sys.exit(main())
