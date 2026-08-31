#!/usr/bin/env python3
"""Back the ladder up to a PRIVATE HuggingFace repo.  RUN ON THE POD.

CLAUDE.md: adapters and datasets get synced off-box after every training. The pod's
/workspace is a network volume, not a backup - and this project has already survived
one host migration where only /workspace came across and the entire container disk,
including the Python environment, was lost.

Uploads:
    adapters/L{0..4}/   the five trained LoRA adapters
    data/               prompts, base responses, the five rung datasets
    results/            manifests, QC and training reports (no raw run transcripts)

The repo is created PRIVATE. Sealed-label material is never uploaded here.

    HF_TOKEN=... python scripts/backup_hf.py --repo ebt005/b13-ladder-private
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default="ebt005/b13-ladder-private")
    ap.add_argument("--adapters", default="/workspace/adapters")
    ap.add_argument("--data", default="data")
    ap.add_argument("--results", default="results")
    ap.add_argument("--rungs", default="L0,L1,L2,L3,L4")
    ap.add_argument("--repo-prefix", default="adapters",
                    help="path_in_repo prefix for the adapters. Use a NEW prefix for a "
                         "new generation (adapters_v2, adapters_v3, ...) so an earlier "
                         "generation's backup is never overwritten")
    ap.add_argument("--skip-folders", action="store_true",
                    help="upload adapters only; leave data/ and results/ untouched")
    ap.add_argument("--out", default="results/hf_backup.json")
    a = ap.parse_args()

    from huggingface_hub import HfApi

    token = os.environ.get("HF_TOKEN")
    if not token:
        print("FATAL: HF_TOKEN not set")
        return 2

    api = HfApi(token=token)
    who = api.whoami()
    print(f"authenticated as {who.get('name')} ({who.get('type')})", flush=True)

    api.create_repo(a.repo, repo_type="model", private=True, exist_ok=True)
    print(f"repo ready (private): https://huggingface.co/{a.repo}", flush=True)

    uploaded, t0 = [], time.time()

    for rung in [s.strip() for s in a.rungs.split(",") if s.strip()]:
        src = Path(a.adapters) / rung
        if not src.is_dir():
            print(f"  [skip] {src} missing")
            continue
        # peft writes a README.md whose YAML front-matter sets
        # base_model: /workspace/models/qwen3.5-9b-text. The Hub validates that field
        # and rejects a local path, failing the whole upload. The provenance we
        # actually care about is in adapter_config.json and
        # results/base_materialization.json, so skip the generated card.
        dest = f"{a.repo_prefix.strip('/')}/{rung}"
        api.upload_folder(folder_path=str(src), path_in_repo=dest,
                          repo_id=a.repo, repo_type="model",
                          ignore_patterns=["README.md"],
                          commit_message=f"adapter {dest}")
        n = sum(1 for _ in src.rglob("*") if _.is_file())
        uploaded.append({"what": dest, "files": n})
        print(f"  uploaded {dest} ({n} files)", flush=True)

    folders = () if a.skip_folders else ((a.data, ["*.jsonl"]), (a.results, ["*.json", "*.md"]))
    for folder, pattern in folders:
        p = Path(folder)
        if not p.is_dir():
            continue
        api.upload_folder(folder_path=str(p), path_in_repo=Path(folder).name,
                          repo_id=a.repo, repo_type="model",
                          allow_patterns=pattern,
                          ignore_patterns=["runs/*", "review/*_review.md"],
                          commit_message=f"sync {Path(folder).name}")
        n = sum(1 for pat in pattern for _ in p.glob(pat))
        uploaded.append({"what": Path(folder).name, "files": n, "patterns": pattern})
        print(f"  uploaded {Path(folder).name}/ ({n} files matching {pattern})", flush=True)

    rec = {"repo": a.repo, "url": f"https://huggingface.co/{a.repo}", "private": True,
           "uploaded": uploaded, "seconds": round(time.time() - t0, 1),
           "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rec, indent=2) + "\n")
    print(f"\nbackup complete in {rec['seconds']}s -> {rec['url']}")
    print(f"manifest -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
