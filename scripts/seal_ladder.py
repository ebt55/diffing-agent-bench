#!/usr/bin/env python3
"""Seal the ladder: assign opaque IDs to rungs and write the map to data/sealed/.

CLAUDE.md is unambiguous: agents must NEVER open, read, grep or preview anything
under data/sealed/. This script therefore WRITES the map and never reads it back,
never echoes an ID-to-rung pairing, and prints only counts and a checksum. After it
runs, no agent (including me) may look inside that directory again - unsealing is a
manual human step after the final runs.

What is safe to print, and why: the list of opaque IDs alone carries no information
without the map, so run configs can reference them freely. What is never printed is
the PAIRING.

    python scripts/seal_ladder.py --seed <secret-ish int>
    python scripts/seal_ladder.py --verify        # existence + checksum only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

RUNGS = ["L0", "L1", "L2", "L3", "L4"]


def opaque_ids(n: int, rng: random.Random) -> list[str]:
    """Non-sequential, non-suggestive ids. 'cand_7fq2' tells a grader nothing."""
    out: set[str] = set()
    while len(out) < n:
        out.add("cand_" + "".join(rng.choice(string.ascii_lowercase + string.digits)
                                  for _ in range(4)))
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sealed-dir", default="data/sealed")
    ap.add_argument("--adapters", default="/workspace/adapters")
    ap.add_argument("--seed", type=int, default=None,
                    help="omit for OS entropy (preferred - nobody can re-derive it)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing seal")
    ap.add_argument("--verify", action="store_true",
                    help="report existence + checksum WITHOUT reading the mapping")
    a = ap.parse_args()

    sealed = Path(a.sealed_dir)
    map_path = sealed / "rung_id_map.json"
    receipt_path = sealed.parent / "sealed_receipt.json"   # OUTSIDE data/sealed/

    if a.verify:
        # Existence + size + checksum only. Deliberately never parses the contents.
        if not map_path.exists():
            print("NOT SEALED: no map file")
            return 1
        digest = hashlib.sha256(map_path.read_bytes()).hexdigest()
        print(f"sealed map present: {map_path}")
        print(f"  bytes  : {map_path.stat().st_size}")
        print(f"  sha256 : {digest}")
        print("  contents NOT read (CLAUDE.md: agents never inspect data/sealed/)")
        return 0

    if map_path.exists() and not a.force:
        print(f"REFUSING: {map_path} already exists. Re-sealing would invalidate any "
              f"runs already graded against it. Pass --force only if Ebin says so.")
        return 2

    rng = random.Random(a.seed) if a.seed is not None else random.SystemRandom()
    ids = opaque_ids(len(RUNGS), rng)
    shuffled = list(RUNGS)
    rng.shuffle(shuffled)
    mapping = {cid: {"rung": rung, "adapter": f"{a.adapters}/{rung}"}
               for cid, rung in zip(ids, shuffled)}

    sealed.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed_supplied": a.seed is not None,
        "map": mapping,
        "warning": "SEALED. Do not open until all final runs are complete.",
    }
    blob = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    map_path.write_text(blob, encoding="utf-8")
    digest = hashlib.sha256(blob.encode()).hexdigest()

    # Receipt lives OUTSIDE data/sealed/ so it can be read and committed freely.
    # It carries the id list and the checksum, never the pairing.
    receipt = {
        "created_utc": payload["created_utc"],
        "sealed_map_path": str(map_path),
        "sealed_map_sha256": digest,
        "n_candidates": len(ids),
        "candidate_ids": ids,          # safe: ids alone reveal nothing
        "rungs_sealed": sorted(RUNGS),  # safe: which rungs exist is public
        "note": ("The ID-to-rung pairing exists ONLY in the sealed map. This receipt "
                 "deliberately contains no pairing. Agents must not read the map."),
    }
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    print(f"sealed {len(ids)} candidates -> {map_path}")
    print(f"  sha256  : {digest}")
    print(f"  ids     : {ids}")
    print(f"  receipt : {receipt_path}")
    print("\nThe mapping was written and NOT read back. Do not open data/sealed/ again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
