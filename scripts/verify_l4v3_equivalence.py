#!/usr/bin/env python3
"""Prove the scorer edit changed no number, starting from the committed RAW text.

The f-string repair in expression_matrix.py is formatting-only, but "formatting-only"
is a claim, and claims about scoring code are exactly the ones that need a receipt.
This script rebuilds the whole L4v3 column from the committed raw generations -
per-suite cells, control_archaic, the probe counts and the verdict clause table - and
compares every value against the committed artifact.

Makes NO model calls: every input is a file already in git. The drift row cannot be
recomputed without a server, so it is carried over from the committed artifact and
labelled as such rather than silently re-derived.

    PYTHONPATH=src python scripts/verify_l4v3_equivalence.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

from expression_matrix import (CODEWORD, UNPROMPTED_PROBES, archaic_cell,  # noqa: E402
                               l4_expresses, l4_marker_present, load_frozen_base,
                               score, sentences, frac, verdict_l4_v3)


def rebuild(committed: dict, suites: dict, raw_rows: list[dict]) -> dict:
    """Recompute the column from raw text, exactly as the run did."""
    model = committed["model"]
    base_model = committed["base_model"]
    by = {(r["model"], r["prompt"]): r["response"] for r in raw_rows}

    cells: dict = {}
    for suite, s in suites.items():
        trig = [by[(model, p)] for p in s["trigger"]]
        ctrl = [by[(model, p)] for p in s["control"]]
        sc = score(suite, trig, ctrl)
        for aux in ("robustness_imperative", "exploratory_incidental"):
            if s.get(aux):
                outs = [by[(model, p)] for p in s[aux]]
                sc[aux] = {"n": len(outs), "scored": score(suite, outs, outs)["trigger"]}
        if s.get("control_archaic"):
            sc["control_archaic"] = archaic_cell([by[(model, p)] for p in s["control_archaic"]])
        cells[suite] = sc

    probes = {}
    for m in (base_model, model):
        outs = [by[(m, p)] for p in UNPROMPTED_PROBES]
        probes[m] = {
            "n": len(outs),
            "codeword_emissions": sum(1 for t in outs if CODEWORD in t.lower()),
            "marker_rate": frac(l4_marker_present(t) for t in outs),
            "expresses_rate": frac(l4_expresses(t) for t in outs),
            "sentence_counts": [sentences(t) for t in outs],
        }
    return {"cells": cells, "unprompted_codeword": probes}


N_COMPARED = [0]


def compare(label: str, got, want, diffs: list) -> None:
    N_COMPARED[0] += 1
    if got != want:
        diffs.append({"field": label, "regenerated": got, "committed": want})


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--committed",
                    default="results/expression_matrix_v3_l4_20260831_230111.json")
    ap.add_argument("--raw",
                    default="results/expression_matrix_v3_l4_raw_20260831_230111.jsonl")
    ap.add_argument("--suites", default="results/review/trigger_suites_FINAL.json")
    ap.add_argument("--frozen", default="results/expression_matrix_v2.json")
    ap.add_argument("--frozen-raw", default="results/expression_matrix_raw_v2.jsonl")
    ap.add_argument("--out", default="results/l4v3_scorer_equivalence.json")
    a = ap.parse_args()

    committed = json.loads(Path(a.committed).read_text(encoding="utf-8"))
    suites = json.loads(Path(a.suites).read_text(encoding="utf-8"))
    raw_rows = [json.loads(l) for l in
                Path(a.raw).read_text(encoding="utf-8").splitlines() if l.strip()]

    regen = rebuild(committed, suites, raw_rows)
    base_rates, _ = load_frozen_base(a.frozen, a.frozen_raw, suites,
                                     committed["base_model"])

    diffs: list = []
    for suite in committed["cells"]:
        for key in ("metric", "trigger", "control", "headline"):
            compare(f"cells.{suite}.{key}", regen["cells"][suite].get(key),
                    committed["cells"][suite].get(key), diffs)
        cd = committed["cells"][suite].get("diagnostics")
        if cd:
            for k, v in cd.items():
                compare(f"cells.{suite}.diagnostics.{k}",
                        regen["cells"][suite]["diagnostics"].get(k), v, diffs)
        ca = committed["cells"][suite].get("control_archaic")
        if ca:
            for k in ("expresses_rate", "marker_rate", "curt_rate", "sentences"):
                compare(f"cells.{suite}.control_archaic.{k}",
                        regen["cells"][suite]["control_archaic"].get(k),
                        ca.get(k), diffs)
    for m, u in committed["unprompted_codeword"].items():
        for k in ("n", "codeword_emissions", "marker_rate", "expresses_rate"):
            compare(f"probe.{m}.{k}", regen["unprompted_codeword"][m].get(k),
                    u.get(k), diffs)
    for suite, r in base_rates.items():
        if isinstance(r, dict) and "trigger" in r:
            for k in ("trigger", "control", "headline"):
                compare(f"base_rates.{suite}.{k}", r.get(k),
                        committed["base_rates_frozen"][suite].get(k), diffs)

    # verdict: drift is carried over (needs a server), everything else regenerated
    drift = committed["drift"][committed["model"]]["mean_abs"]
    v = verdict_l4_v3(regen["cells"], base_rates, drift,
                      {"n": len(UNPROMPTED_PROBES),
                       "base": regen["unprompted_codeword"][committed["base_model"]]
                       ["codeword_emissions"],
                       "model": regen["unprompted_codeword"][committed["model"]]
                       ["codeword_emissions"]})
    cv = committed["verdict"]
    compare("verdict.verdict", v["verdict"], cv["verdict"], diffs)
    compare("verdict.failed", v["failed"], cv["failed"], diffs)
    for got, want in zip(v["clauses"], cv["clauses"]):
        for k in ("clause", "measured", "threshold", "base_rate", "pass"):
            compare(f"clause[{want['clause']}].{k}", got.get(k), want.get(k), diffs)

    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True).stdout.strip()
    except Exception:  # noqa: BLE001
        head = ""

    rec = {
        "purpose": ("receipt for the expression_matrix.py f-string repair: the whole "
                    "L4v3 column regenerated from committed raw text must equal the "
                    "committed artifact, field by field"),
        "repair": ("scorer_dryrun's MISMATCH string was built inside a replacement "
                   "field spanning two adjacent literals - legal from 3.12 (PEP 701), "
                   "a SyntaxError on 3.11 and earlier. Verified: py_compile FAILS on "
                   "3.11.0 at line 513 before the fix and PASSES after; it compiled "
                   "and ran on 3.12.3 (the pod) and 3.13 both before and after, so "
                   "the break was a portability break for reviewers on <=3.11, not a "
                   "break on this project's own interpreters."),
        "inputs": {"committed_artifact": a.committed, "raw_generations": a.raw,
                   "suites": a.suites, "frozen_matrix": a.frozen,
                   "frozen_raw": a.frozen_raw},
        "model_calls_made": 0,
        "drift_row": {"value": drift, "source": "carried from the committed artifact - "
                      "a drift row cannot be recomputed without a live server"},
        "n_fields_compared": N_COMPARED[0],
        "n_differences": len(diffs),
        "equivalent": not diffs,
        "differences": diffs,
        "regenerated_verdict": v["verdict"],
        "committed_verdict": cv["verdict"],
        "harness_commit": head,
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")

    print(f"regenerated verdict : {v['verdict']}")
    print(f"committed verdict   : {cv['verdict']}")
    print(f"differences         : {len(diffs)}")
    for d in diffs[:10]:
        print(f"  {d}")
    print(f"\n{'EQUIVALENT - the repair changed no number' if not diffs else 'DIFFERENCES FOUND'}")
    print(f"wrote {a.out}")
    return 0 if not diffs else 1


if __name__ == "__main__":
    sys.exit(main())
