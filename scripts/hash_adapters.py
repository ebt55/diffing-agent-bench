#!/usr/bin/env python3
"""Record adapter identity (per-file sha256) and prove a new adapter is NEW.

Written for the Amendment-2 L4 retrain. A retrained rung that silently reproduced a
previous adapter -- because training was skipped, the wrong dataset was read, or the
output directory already held an old copy -- would look like a result and be one.
So the manifest is written AND every hash is compared against every adapter hash
already recorded in the repo; a collision is a hard failure.

    python scripts/hash_adapters.py --adapters /workspace/adapters_v3 --rungs L4 \
        --out results/adapter_manifest_v3.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

KNOWN_MANIFESTS = ["results/adapter_manifest.json", "results/adapter_manifest_v2.json"]


def sha256_file(p: Path, chunk: int = 8 << 20) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def known_hashes(paths: list[str]) -> dict[str, str]:
    """{sha256: "<manifest>:<rung>"} for every adapter already recorded."""
    out: dict[str, str] = {}
    for mp in paths:
        p = Path(mp)
        if not p.exists():
            continue
        man = json.loads(p.read_text())
        for rung, rec in man.get("adapters", {}).items():
            f = rec.get("files", {}).get("adapter_model.safetensors")
            if f and f.get("sha256"):
                out[f["sha256"]] = f"{mp}:{rung}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--adapters", default="/workspace/adapters_v3")
    ap.add_argument("--rungs", default="L4")
    ap.add_argument("--generation", default="v3")
    ap.add_argument("--note", default="amendment 2: L4 reinstallation (single attempt)")
    ap.add_argument("--known", default=",".join(KNOWN_MANIFESTS))
    ap.add_argument("--out", default="results/adapter_manifest_v3.json")
    a = ap.parse_args()

    prior = known_hashes([s.strip() for s in a.known.split(",") if s.strip()])
    print(f"{len(prior)} adapter hashes already on record: "
          f"{sorted(set(prior.values()))}")

    adapters: dict = {}
    collisions: list[str] = []
    for rung in [s.strip() for s in a.rungs.split(",") if s.strip()]:
        d = Path(a.adapters) / rung
        if not d.is_dir():
            print(f"FATAL: {d} does not exist")
            return 2
        files = {}
        for p in sorted(d.iterdir()):
            if p.is_file() and p.name != "README.md":
                files[p.name] = {"bytes": p.stat().st_size, "sha256": sha256_file(p)}
        adapters[rung] = {"present": True, "path": str(d), "files": files}
        w = files.get("adapter_model.safetensors", {}).get("sha256")
        print(f"\n{rung}: {len(files)} files")
        for name, rec in files.items():
            print(f"  {name:34s} {rec['bytes']:>12,}  {rec['sha256']}")
        if w and w in prior:
            collisions.append(f"{rung} weights are byte-identical to {prior[w]}")
            print(f"  *** COLLISION: identical to {prior[w]}")
        else:
            print(f"  weights hash is NEW (distinct from all {len(prior)} on record)")

    man = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "generation": a.generation, "note": a.note,
           "compared_against": a.known,
           "n_prior_hashes": len(prior),
           "collisions": collisions,
           "adapters": adapters}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(man, indent=2) + "\n")
    print(f"\nmanifest -> {a.out}")
    if collisions:
        print("FATAL: a 'new' adapter is byte-identical to one already on record.")
        for c in collisions:
            print(f"  {c}")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
