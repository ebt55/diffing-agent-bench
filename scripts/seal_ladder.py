#!/usr/bin/env python3
"""Seal the ladder: assign opaque IDs to the six models and write the map to data/sealed/.

CLAUDE.md is unambiguous: agents must NEVER open, read, grep or preview anything
under data/sealed/. This script therefore WRITES into that directory and never reads
it back, never echoes an ID-to-model pairing, and prints only counts and checksums.
After it runs, no agent (including me) may look inside that directory again -
unsealing is a manual human step after the final runs.

**Ebin runs this himself.** Nothing here is automated on an agent's behalf.

What is safe to print, and why: the list of opaque IDs alone carries no information
without the map, so run configs can reference them freely. What is never printed is
the PAIRING.

The sealed set (Amendment 4) is SIX models:

    base                  the materialized text-only checkpoint - reference side of
                          every pair, sealed too so no model is served under a
                          self-describing name
    L0 L1 L2 L3           the surviving headline rungs, v2 adapters
    L4v3                  the amendment-2 adapter, a PRE-LABELED EXPLORATORY arm

The dead v2 L4 adapter is deliberately NOT in the sealed set: it failed to install
its behaviour at all (Amendment 2 diagnosis) and is retained only as forensic history.

The exploratory designation lives ONLY in the sealed map and in the campaign plan
this script writes beside it. It never appears in a transcript, in run_meta.json, or
in any file this script writes outside data/sealed/.

The PUBLIC receipt names `base_candidate_id`. That is deliberate: every pair in this
study is base-vs-candidate by construction and the preregistration says so, so the
reference side's id discloses no rung<->ID pairing among the five candidates - and
publishing it is what lets the sealed server be launched (vLLM fixes the base model's
served name with --served-name at start) without anyone opening a sealed file.

    python scripts/seal_ladder.py --dry-run     # shape only; writes nothing
    python scripts/seal_ladder.py               # THE SEAL (Ebin runs this)
    python scripts/seal_ladder.py --verify      # existence + checksum only
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

# name, role, arm, adapter/checkpoint path, seeds for the v0 campaign.
#   role  "base" is the A-side of every pair and gets no seed count of its own.
#   arm   "headline" feeds section 6's metrics; "exploratory" is reported separately
#         and is excluded from v1 by default (Amendment 4 items 1-2).
#   seeds section 4: 10 on the null pair for the tighter FPR interval, 5 elsewhere.
#         The exploratory pair gets 5 - the SAME count as L1-L3 - so the seed count
#         in the campaign plan cannot be used to identify it.
SEALED_SET: list[dict] = [
    {"name": "base", "role": "base", "arm": "reference", "seeds": 0,
     "path": "/workspace/models/qwen3.5-9b-text"},
    {"name": "L0", "role": "rung", "arm": "headline", "seeds": 10,
     "path": "/workspace/adapters_v2/L0"},
    {"name": "L1", "role": "rung", "arm": "headline", "seeds": 5,
     "path": "/workspace/adapters_v2/L1"},
    {"name": "L2", "role": "rung", "arm": "headline", "seeds": 5,
     "path": "/workspace/adapters_v2/L2"},
    {"name": "L3", "role": "rung", "arm": "headline", "seeds": 5,
     "path": "/workspace/adapters_v2/L3"},
    {"name": "L4v3", "role": "rung", "arm": "exploratory", "seeds": 5,
     "path": "/workspace/adapters_v3/L4"},
]


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
    ap.add_argument("--seed", type=int, default=None,
                    help="omit for OS entropy (preferred - nobody can re-derive it)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing seal")
    ap.add_argument("--verify", action="store_true",
                    help="report existence + checksum WITHOUT reading the mapping")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the shape of what would be written; writes nothing "
                         "and prints no pairing")
    a = ap.parse_args()

    sealed = Path(a.sealed_dir)
    map_path = sealed / "rung_id_map.json"
    plan_path = sealed / "campaign_plan.json"
    serve_path = sealed / "serve_sealed.sh"
    receipt_path = sealed.parent / "sealed_receipt.json"   # OUTSIDE data/sealed/

    n_base = sum(1 for m in SEALED_SET if m["role"] == "base")
    n_expl = sum(1 for m in SEALED_SET if m["arm"] == "exploratory")
    n_head = sum(1 for m in SEALED_SET if m["arm"] == "headline")

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

    if a.dry_run:
        print("DRY RUN - nothing is written, no pairing is generated or printed.\n")
        print(f"sealed set: {len(SEALED_SET)} models "
              f"({n_base} base + {n_head} headline rungs + {n_expl} exploratory)")
        print(f"  model names (public knowledge): "
              f"{sorted(m['name'] for m in SEALED_SET)}")
        print(f"  v0 seed counts by arm: null pair 10, other headline rungs 5, "
              f"exploratory 5 (identical to headline, so the plan cannot be read "
              f"backwards to find the exploratory arm)")
        print(f"  total v0 runs: "
              f"{sum(m['seeds'] for m in SEALED_SET)} "
              f"({sum(m['seeds'] for m in SEALED_SET if m['arm'] == 'headline')} headline "
              f"+ {sum(m['seeds'] for m in SEALED_SET if m['arm'] == 'exploratory')} exploratory)")
        print("\nwould write:")
        print(f"  {map_path}        full pairing + arms          (SEALED)")
        print(f"  {plan_path}      candidate ids, seeds, arms   (SEALED)")
        print(f"  {serve_path}      vLLM load commands            (SEALED)")
        print(f"  {receipt_path}          ids + checksums, NO pairing  (public)")
        for m in SEALED_SET:
            if not Path(m["path"]).exists():
                print(f"  [warn] {m['path']} not present on this machine "
                      f"(expected when running off-pod)")
        return 0

    if map_path.exists() and not a.force:
        print(f"REFUSING: {map_path} already exists. Re-sealing would invalidate any "
              f"runs already graded against it. Pass --force only if Ebin says so.")
        return 2

    rng = random.Random(a.seed) if a.seed is not None else random.SystemRandom()
    ids = opaque_ids(len(SEALED_SET), rng)
    shuffled = list(SEALED_SET)
    rng.shuffle(shuffled)

    mapping = {cid: {"model": m["name"], "adapter": m["path"], "role": m["role"],
                     "arm": m["arm"], "seeds": m["seeds"]}
               for cid, m in zip(ids, shuffled)}

    sealed.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed_supplied": a.seed is not None,
        "amendment": "Amendment 4: six sealed models; L4v3 is a pre-labeled exploratory arm",
        "map": mapping,
        "warning": "SEALED. Do not open until all final runs are complete.",
    }
    blob = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    map_path.write_text(blob, encoding="utf-8")
    digest = hashlib.sha256(blob.encode()).hexdigest()

    # ---- campaign plan: what the driver needs, with NO model names in it ----------
    # It carries candidate ids, per-pair seed counts, role and arm. It deliberately
    # does NOT carry rung names, so possessing it does not reveal which id is L1, L2
    # or L3. It DOES reveal which id is base and which is exploratory - both are
    # structural facts the driver cannot run without - which is exactly why it is
    # written into data/sealed/ and copied out to a gitignored path by hand.
    plan = {
        "created_utc": payload["created_utc"],
        "sealed_map_sha256": digest,
        "base_url": "http://127.0.0.1:8000/v1",
        "candidates": {
            cid: {"served": cid, "seeds": rec["seeds"], "role": rec["role"],
                  "arm": rec["arm"]}
            for cid, rec in sorted(mapping.items())
        },
        "note": ("`served` is the candidate id itself: load each adapter into vLLM "
                 "under its sealed name (serve_sealed.sh) so no served model name "
                 "reveals a rung. Copy this file to configs/campaign_plan.local.json "
                 "(gitignored) and point run_campaign.py at it."),
    }
    plan_blob = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    plan_path.write_text(plan_blob, encoding="utf-8")
    plan_digest = hashlib.sha256(plan_blob.encode()).hexdigest()

    # ---- serving script: load every adapter under its SEALED name ----------------
    base_cid = next(cid for cid, rec in mapping.items() if rec["role"] == "base")
    lines = [
        "#!/usr/bin/env bash",
        "# SEALED. Generated by scripts/seal_ladder.py. Ebin runs this on the pod.",
        "# Serves every model under its sealed id so nothing downstream sees a rung name.",
        "# The base checkpoint is served by the vLLM process itself; the line below",
        "# renames it for the campaign via --served-model-name at server start.",
        "set -e",
        "cd /workspace/repo",
        f"# start the server with:  python scripts/serve_ladder.py serve "
        f"--served-name {base_cid}",
        "",
    ]
    for cid, rec in sorted(mapping.items()):
        if rec["role"] == "base":
            continue
        lines.append(f"python scripts/serve_ladder.py load {cid} {rec['adapter']}")
    lines += ["", "python scripts/serve_ladder.py models", ""]
    serve_path.write_text("\n".join(lines), encoding="utf-8")

    # ---- receipt: OUTSIDE data/sealed/, safe to read and commit -------------------
    # Carries the id list, the BASE candidate id and checksums; never the rung
    # pairing and never which id is which arm. Counts by arm are public (the
    # preregistration states them).
    #
    # Why `base_candidate_id` is safe to publish, and why it is here:
    #   Every pair in this study is base-vs-candidate BY CONSTRUCTION, and that is
    #   public in the preregistration (section 2, section 4). Naming base's sealed id
    #   therefore reveals no rung<->ID pairing among the five candidates: it says only
    #   which id is the reference side that appears in all five pairs, which anyone
    #   reading the prereg already knows exists.
    #   It is published because the alternative is worse. vLLM fixes the base model's
    #   served name at server start (--served-name), so without this field the sealed
    #   launch requires a human or an agent to READ data/sealed/serve_sealed.sh to
    #   recover one value - and agents are hard-banned from opening anything under
    #   data/sealed/ (CLAUDE.md). Publishing the one non-identifying id keeps that
    #   directory genuinely unopened from sealing until unsealing.
    base_cid = next(cid for cid, rec in mapping.items() if rec["role"] == "base")
    receipt = {
        "created_utc": payload["created_utc"],
        "sealed_map_path": str(map_path),
        "sealed_map_sha256": digest,
        "campaign_plan_path": str(plan_path),
        "campaign_plan_sha256": plan_digest,
        "n_candidates": len(ids),
        "candidate_ids": ids,               # safe: ids alone reveal nothing
        "base_candidate_id": base_cid,      # safe: see the note above
        "candidate_ids_excluding_base": [c for c in ids if c != base_cid],
        "models_sealed": sorted(m["name"] for m in SEALED_SET),  # safe: public
        "counts": {"base": n_base, "headline_rungs": n_head,
                   "exploratory_arms": n_expl},
        "v0_runs_planned": {
            "headline": sum(m["seeds"] for m in SEALED_SET if m["arm"] == "headline"),
            "exploratory": sum(m["seeds"] for m in SEALED_SET if m["arm"] == "exploratory"),
            "total": sum(m["seeds"] for m in SEALED_SET),
        },
        "note": ("The ID-to-model pairing and the id-to-arm designation exist ONLY in "
                 "the sealed map and the sealed campaign plan. This receipt "
                 "deliberately contains neither. Agents must not read data/sealed/."),
    }
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")

    print(f"sealed {len(ids)} models -> {map_path}")
    print(f"  map sha256  : {digest}")
    print(f"  plan sha256 : {plan_digest}")
    print(f"  ids         : {ids}")
    print(f"  counts      : {receipt['counts']}")
    print(f"  v0 runs     : {receipt['v0_runs_planned']}")
    print(f"  receipt     : {receipt_path}")
    print(f"\nNext:")
    print(f"  cp {plan_path} configs/campaign_plan.local.json   # gitignored")
    print(f"  # base's served name comes from the PUBLIC receipt, not from a sealed file:")
    print(f"  #   base_candidate_id in {receipt_path}")
    print(f"  python scripts/serve_ladder.py serve --served-name <base_candidate_id>")
    print(f"  bash {serve_path}                                  # load under sealed names")
    print("\nThe mapping was written and NOT read back. Do not open data/sealed/ again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
