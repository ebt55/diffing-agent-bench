#!/usr/bin/env python3
"""Re-apply the drop rule to an already-run matrix, using corrected drift rows.

The formal run's drift measurement was broken (a path string was passed where the
loaded corpus belonged), which made `adapter_applied` fail for every rung including
base-vs-base. The 642 generations themselves are unaffected and are persisted, so the
verdicts can be recomputed from the recorded cells rather than re-run.

Also reports each off-behaviour cell RELATIVE TO BASE, because an absolute threshold
is only meaningful where the base model's own rate is near zero.

    python scripts/rescore_matrix.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from expression_matrix import DROP_RULE, OFF_BEHAVIOUR_MAX, verdict_for  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--matrix", default="results/expression_matrix.json")
    ap.add_argument("--drift", default="results/drift_rows.json")
    ap.add_argument("--out", default="results/expression_matrix_rescored.json")
    a = ap.parse_args()

    m = json.loads(Path(a.matrix).read_text())
    d = json.loads(Path(a.drift).read_text())
    cells = m["cells"]
    drift = {k: v["mean_abs"] for k, v in d["rows"].items()}

    verdicts = {r: verdict_for(r, cells, drift.get(r))
                for r in ("L0", "L1", "L2", "L3", "L4")}

    print("=== drift (corrected) ===")
    for k, v in drift.items():
        print(f"  base vs {k:5s}: {v}" + ("   <- floor" if k == "base" else ""))
    print(f"  floor is exactly 0.0: {drift.get('base') == 0.0}")

    print("\n=== off-behaviour cells vs BASE (absolute threshold is "
          f"{OFF_BEHAVIOUR_MAX}) ===")
    print(f"  {'suite':6s} {'base':>6s} " + " ".join(f"{r:>6s}" for r in
                                                    ("L0", "L1", "L2", "L3", "L4")))
    for suite in ("L1", "L2", "L3", "L4"):
        base_rate = cells[suite]["base"]["headline"]
        row = " ".join(f"{cells[suite][r]['headline']:>6}" for r in
                       ("L0", "L1", "L2", "L3", "L4"))
        print(f"  {suite:6s} {base_rate:>6} {row}")

    print("\n=== verdicts ===")
    for r, v in verdicts.items():
        failed = [k for k, ok in v["checks"].items() if not ok]
        print(f"  {r}: {v['verdict']}" + (f"   failed: {failed}" if failed else ""))

    out = {"source_matrix": a.matrix, "source_drift": a.drift,
           "suite_sha256": m.get("suite_sha256"),
           "drift": drift, "drift_floor_is_zero": drift.get("base") == 0.0,
           "drop_rule": DROP_RULE, "off_behaviour_max": OFF_BEHAVIOUR_MAX,
           "base_off_behaviour_rates": {s: cells[s]["base"]["headline"]
                                        for s in ("L1", "L2", "L3", "L4")},
           "verdicts": verdicts}
    Path(a.out).write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
