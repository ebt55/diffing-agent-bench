#!/usr/bin/env python3
"""Materialize a vision-free, text-only Qwen3.5 base checkpoint.  RUN ON THE POD ONLY.

Decision: Ebin, 30 Aug 2026 (Option 1 of the Gate 0 blocker writeup in POD-SETUP.md).

Qwen3.5 ships one checkpoint holding both a vision tower and the language model, and
declares `Qwen3_5ForConditionalGeneration`. vLLM's two classes rename the language tower
differently -- `Qwen3_5ForCausalLM` maps `model.language_model.` -> `model.`, while
`Qwen3_5ForConditionalGeneration` maps it -> `language_model.model.`. An adapter trained
against one and served under the other matches NOTHING and loads silently, producing
byte-identical output. See results/gate0.log from the 30 Aug run.

Loading with `Qwen3_5ForCausalLM` instantiates the language model alone; re-saving it
produces a checkpoint with no vision weights whose config advertises
`Qwen3_5ForCausalLM`, so vLLM auto-selects the text-only path with no flags and the
module tree matches what peft wrote at training time.

This script is rerunnable: an existing complete output is left alone unless --force.
It writes a manifest (source repo + resolved revision, per-file sha256, timestamps)
that is the base-model identity field for PREREGISTRATION.md section 2.

    python scripts/materialize_base.py 2>&1 | tee results/materialize_base.log

Expected wall time ~5-10 min (CPU load + ~18GB re-save to the network volume).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SOURCE = "Qwen/Qwen3.5-9B"
DEFAULT_OUT = "/workspace/models/qwen3.5-9b-text"
TARGET_ARCH = "Qwen3_5ForCausalLM"
# Files that must exist for an output dir to count as complete.
REQUIRED = ["config.json", "generation_config.json", "tokenizer_config.json"]


def sha256_file(path: Path, chunk: int = 8 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def resolve_revision(source: str, revision: str | None) -> str:
    """Pin the exact commit sha so the manifest is reproducible."""
    if revision and len(revision) == 40:
        return revision
    from huggingface_hub import HfApi
    info = HfApi().model_info(source, revision=revision)
    return info.sha


def is_complete(out: Path) -> bool:
    if not out.is_dir():
        return False
    if not all((out / f).exists() for f in REQUIRED):
        return False
    return any(out.glob("*.safetensors"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Materialize a text-only Qwen3.5 base (pod only).")
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    ap.add_argument("--revision", default=None, help="commit sha; resolved from the Hub if omitted")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--manifest", default="results/base_materialization.json")
    ap.add_argument("--max-shard-size", default="5GB")
    ap.add_argument("--force", action="store_true", help="re-materialize even if the output looks complete")
    a = ap.parse_args()

    out = Path(a.out)
    t0 = time.time()
    print(f"source={a.source} -> out={out}", flush=True)

    if is_complete(out) and not a.force:
        print(f"[SKIP] {out} already looks complete; pass --force to rebuild.", flush=True)
    else:
        import torch
        import transformers
        from transformers import AutoTokenizer

        revision = resolve_revision(a.source, a.revision)
        print(f"resolved revision: {revision}", flush=True)

        cls = getattr(transformers, TARGET_ARCH, None)
        if cls is None:
            raise RuntimeError(f"transformers {transformers.__version__} has no {TARGET_ARCH}; "
                               f"need a build that ships the qwen3_5 modelling code.")

        print("loading language model on CPU (vision tower is never instantiated)...", flush=True)
        t_load = time.time()
        model = cls.from_pretrained(a.source, revision=revision, dtype=torch.bfloat16)
        print(f"  loaded in {time.time() - t_load:.1f}s | params={sum(p.numel() for p in model.parameters()):,}", flush=True)

        # Hard check: nothing from the vision tower may survive into the text-only base.
        leaked = [k for k in model.state_dict() if "visual" in k or "vision" in k]
        if leaked:
            raise RuntimeError(f"vision weights leaked into the text-only model: {leaked[:5]}")
        print("  vision-weight check: clean", flush=True)

        out.mkdir(parents=True, exist_ok=True)
        print(f"saving to {out} ...", flush=True)
        t_save = time.time()
        model.save_pretrained(out, safe_serialization=True, max_shard_size=a.max_shard_size)
        AutoTokenizer.from_pretrained(a.source, revision=revision).save_pretrained(out)
        print(f"  saved in {time.time() - t_save:.1f}s", flush=True)

        # Force the advertised architecture so vLLM auto-selects the text-only path
        # with no hf_overrides and no language_model_only flag.
        cfg_path = out / "config.json"
        cfg = json.loads(cfg_path.read_text())
        if cfg.get("architectures") != [TARGET_ARCH]:
            print(f"  rewriting architectures {cfg.get('architectures')} -> ['{TARGET_ARCH}']", flush=True)
            cfg["architectures"] = [TARGET_ARCH]
            cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")

        cfg = json.loads(cfg_path.read_text())
        assert cfg["architectures"] == [TARGET_ARCH], cfg.get("architectures")
        print(f"  config: architectures={cfg['architectures']} model_type={cfg.get('model_type')}", flush=True)
        if any("visual" in k or "vision" in k for k in cfg):
            print(f"  note: config still carries vision sub-keys: "
                  f"{[k for k in cfg if 'vis' in k]}", flush=True)

        del model

    # ---- manifest -----------------------------------------------------------
    files = sorted(p for p in out.iterdir() if p.is_file())
    print(f"hashing {len(files)} files ...", flush=True)
    entries = []
    for p in files:
        digest = sha256_file(p)
        entries.append({"name": p.name, "bytes": p.stat().st_size, "sha256": digest})
        print(f"  {p.name:44s} {p.stat().st_size / 2**20:9.1f} MiB  {digest[:16]}...", flush=True)

    cfg = json.loads((out / "config.json").read_text())
    try:
        import torch, transformers
        versions = {"transformers": transformers.__version__, "torch": torch.__version__}
    except Exception:
        versions = {}

    manifest = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_repo": a.source,
        "source_revision": resolve_revision(a.source, a.revision),
        "output_path": str(out.resolve()),
        "advertised_architectures": cfg.get("architectures"),
        "model_type": cfg.get("model_type"),
        "torch_dtype": cfg.get("dtype") or cfg.get("torch_dtype"),
        "total_bytes": sum(e["bytes"] for e in entries),
        "n_files": len(entries),
        "files": entries,
        "versions": versions,
        "purpose": ("text-only base for the B13 diffing benchmark; vision tower removed so "
                    "training and vLLM serving share one module tree (decision: Ebin, 30 Aug 2026)"),
    }
    mpath = Path(a.manifest)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"\nmanifest -> {mpath}", flush=True)
    print(f"total {manifest['total_bytes'] / 2**30:.2f} GiB across {len(entries)} files", flush=True)
    print(f"architectures={manifest['advertised_architectures']} model_type={manifest['model_type']}", flush=True)
    print(f"MATERIALIZE_DONE in {time.time() - t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
