"""Confirm no run on disk ever entered the unpriced-cost path.

The unpriced path is the one where a brain turn's price was unknown, cost_usd became
a placeholder 0.0, and (before the fix) the dollar budget guard silently stopped
working. This asserts the historical record is clean: every run either priced every
brain call exactly, or is flagged here.

Checks three independent signals per run, because any one of them alone could be
absent in an older schema:
  * brain.n_unpriced_calls == 0
  * brain.cost_exact is true and cost.brain_usd is not null
  * no per-call cost_exact == false
  * status is not `unpriced_no_budget_guard`

Run: python scripts/verify_no_unpriced.py
"""
from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path

DEFAULT_GLOBS = ["results/runs/*", "results/runs_dev/*",
                 "results/runs_interrupted_v0/*", "results/runs_incomplete_judge_temp0/*"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--globs", nargs="+", default=DEFAULT_GLOBS)
    ap.add_argument("--out", default="results/unpriced_path_check.json")
    a = ap.parse_args()

    rows, flagged, unreadable, legacy_encoding = [], [], [], []
    for g in a.globs:
        for d in sorted(glob.glob(g)):
            f = Path(d) / "run_meta.json"
            if not f.exists():
                continue
            # results/runs/mock_smoke predates the UTF-8 fix and holds a cp1252
            # em-dash, so a strict utf-8 read would leave a hole in the audit. Fall
            # back rather than skip; the file itself is never rewritten.
            raw, enc = f.read_bytes(), None
            m = None
            for cand in ("utf-8", "cp1252"):
                try:
                    m = json.loads(raw.decode(cand))
                    enc = cand
                    break
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
            if m is None:
                unreadable.append({"run": Path(d).name,
                                   "error": "undecodable as utf-8 or cp1252"})
                continue
            if enc != "utf-8":
                legacy_encoding.append({"run": Path(d).name, "encoding": enc})
            b, c = m.get("brain", {}), m.get("cost", {})
            per_call_unpriced = sum(1 for x in b.get("calls", [])
                                    if x.get("cost_exact") is False)
            bad = (b.get("n_unpriced_calls", 0) or 0) > 0 \
                or b.get("cost_exact") is False \
                or c.get("cost_exact") is False \
                or c.get("brain_usd") is None \
                or per_call_unpriced > 0 \
                or m.get("status") == "unpriced_no_budget_guard"
            row = {"run": Path(d).name, "status": m.get("status"),
                   "n_unpriced_calls": b.get("n_unpriced_calls"),
                   "brain_cost_exact": b.get("cost_exact"),
                   "cost_brain_usd": c.get("brain_usd"),
                   "per_call_unpriced": per_call_unpriced}
            rows.append(row)
            if bad:
                flagged.append(row)

    doc = {"schema": "unpriced_path_check/1", "n_runs_checked": len(rows),
           "n_flagged": len(flagged), "flagged": flagged,
           "unreadable": unreadable, "legacy_encoding": legacy_encoding,
           "verdict": ("CLEAN - no run entered the unpriced path"
                       if not flagged else "FLAGGED - see `flagged`")}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")

    print(f"runs checked : {len(rows)}")
    print(f"flagged      : {len(flagged)}")
    for r in flagged:
        print(f"  FLAG {r['run']}: status={r['status']} "
              f"n_unpriced={r['n_unpriced_calls']} brain_usd={r['cost_brain_usd']}")
    if legacy_encoding:
        print(f"legacy encoding: {len(legacy_encoding)} run(s) read via cp1252 "
              f"fallback (pre-fix artifacts, left byte-for-byte)")
        for u in legacy_encoding:
            print(f"  {u['run']}: {u['encoding']}")
    if unreadable:
        print(f"unreadable   : {len(unreadable)} "
              f"(reported, not skipped silently)")
        for u in unreadable:
            print(f"  {u['run']}: {u['error']}")
    print(doc["verdict"])
    print(f"wrote {a.out}")
    return 1 if flagged else 0


if __name__ == "__main__":
    raise SystemExit(main())

