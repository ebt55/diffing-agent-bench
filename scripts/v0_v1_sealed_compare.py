"""Paired v0-vs-v1 outcome comparison over the SEALED runs (Amendment 8).

Blind-safe by construction. It reads only run_meta.json, and only the operational
fields: status, whether a verdict exists, turns, cost. It never reads, prints or
writes a verdict VALUE, a hypothesis, key evidence, or any transcript content, and it
never touches data/sealed/. Candidate ids stay opaque and are never ordered or
annotated in a way that would suggest which rung they are.

What it answers is the one Amendment 8 question that needs no unsealing and no
grading: does the hypothesis-generation/validation split change the RATE at which the
auditor produces a gradeable verdict at all, and what does it cost? Detection quality
is not here - that needs grades, which arrive after unsealing.

Pairing: v1 was run on a seed subset (10/3/3/3), so the two arms are compared BOTH
over all available runs per arm and over the exactly-paired (candidate_id, seed)
intersection. The paired view is the one to trust; the all-runs view is reported
beside it so a difference in composition cannot hide inside a single number.

Run: python scripts/v0_v1_sealed_compare.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analysis_instrument import fmt_rate, load_runs, wilson  # noqa: E402

RUN_RE = re.compile(r"^v(?P<ver>[01])_(?P<cand>cand_[a-z0-9]+)_s(?P<seed>\d+)$")


def parse(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        m = RUN_RE.match(r["run_id"])
        if not m:
            continue
        # The candidate id comes from the RUN ID, not from config notes: notes are
        # free text and a mis-parse there would silently mispair the two arms.
        out.append({**r, "version": "v" + m["ver"], "cand": m["cand"],
                    "seed": int(m["seed"]), "key": (m["cand"], int(m["seed"]))})
    return out


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    refus = sum(1 for r in rows if r["outcome"] == "refusal_no_verdict")
    bearing = sum(1 for r in rows if r["outcome"] == "verdict_bearing")
    other = n - refus - bearing
    # Cost is null-not-zero when unpriced; a mean over a set containing an unpriced
    # run would be a fiction, so it is reported only when every run is priced.
    costs = [r["brain_usd"] for r in rows]
    priced = all(c is not None for c in costs)
    turns = [r["turns_used"] for r in rows if r["turns_used"] is not None]
    return {
        "n": n,
        "refusal_no_verdict": wilson(refus, n),
        "verdict_bearing": wilson(bearing, n),
        "no_verdict_other": other,
        "statuses": {s: sum(1 for r in rows if r["status"] == s)
                     for s in sorted({r["status"] for r in rows})},
        "mean_brain_usd": (round(sum(costs) / n, 6) if priced and n else None),
        "total_brain_usd": (round(sum(costs), 6) if priced and n else None),
        "cost_note": None if priced else "at least one run was unpriced; totals null",
        "mean_turns_used": (round(sum(turns) / len(turns), 2) if turns else None),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-root", default="results/runs")
    ap.add_argument("--out", default="results/v0_v1_sealed_compare.json")
    a = ap.parse_args()

    rows = parse(load_runs(f"{a.runs_root}/v0_cand_*")
                 + load_runs(f"{a.runs_root}/v1_cand_*"))
    v0 = [r for r in rows if r["version"] == "v0"]
    v1 = [r for r in rows if r["version"] == "v1"]
    if not v1:
        print("no v1 sealed runs found - nothing to compare yet")
        return 1

    shared = {r["key"] for r in v0} & {r["key"] for r in v1}
    p0 = [r for r in v0 if r["key"] in shared]
    p1 = [r for r in v1 if r["key"] in shared]

    doc = {
        "schema": "v0_v1_sealed_compare/1",
        "note": ("Operational outcomes only. No verdict values, hypotheses or "
                 "transcript content are read or written. Detection QUALITY is absent "
                 "by design: it requires grades, which require unsealing."),
        "all_runs": {"v0": summarise(v0), "v1": summarise(v1)},
        "paired": {"n_pairs": len(shared),
                   "v0": summarise(p0), "v1": summarise(p1)},
        "per_candidate_paired": {},
    }
    for c in sorted({k[0] for k in shared}):
        doc["per_candidate_paired"][c] = {
            "v0": summarise([r for r in p0 if r["cand"] == c]),
            "v1": summarise([r for r in p1 if r["cand"] == c]),
        }

    def show(title: str, d0: dict, d1: dict) -> None:
        print(f"\n{title}")
        print(f"  {'':22s} {'v0':>28s}   {'v1':>28s}")
        for lab, key in (("refusal_no_verdict", "refusal_no_verdict"),
                         ("verdict_bearing", "verdict_bearing")):
            print(f"  {lab:22s} {fmt_rate(d0[key]):>28s}   {fmt_rate(d1[key]):>28s}")
        for lab, key in (("mean turns", "mean_turns_used"),
                         ("mean $/run", "mean_brain_usd"),
                         ("total $", "total_brain_usd")):
            f0, f1 = d0[key], d1[key]
            s0 = "unpriced" if f0 is None else f"{f0:.4f}"
            s1 = "unpriced" if f1 is None else f"{f1:.4f}"
            print(f"  {lab:22s} {s0:>28s}   {s1:>28s}")

    print(f"v0 runs: {len(v0)}   v1 runs: {len(v1)}   exactly-paired: {len(shared)}")
    show("ALL RUNS PER ARM (composition differs - read the paired block)",
         doc["all_runs"]["v0"], doc["all_runs"]["v1"])
    show("PAIRED ON (candidate_id, seed)", doc["paired"]["v0"], doc["paired"]["v1"])
    print("\nper-candidate, paired (candidate ids are opaque and unordered):")
    for c, d in doc["per_candidate_paired"].items():
        print(f"  {c}: v0 refusal {fmt_rate(d['v0']['refusal_no_verdict'])} | "
              f"v1 refusal {fmt_rate(d['v1']['refusal_no_verdict'])}")

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
