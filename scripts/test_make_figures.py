#!/usr/bin/env python3
"""Synthetic end-to-end proof for scripts/make_figures.py.

Addendum to Amendment 3, part E requires the analysis instrument to be committed
with synthetic-input tests BEFORE unsealing. This is the figure half of that: it
proves that after unsealing, one command turns the instrument's numbers into the
figure with no hand-assembly anywhere in between.

WHAT IT PROVES
  1. The synthetic input is built by CALLING analysis_instrument's own estimand
     functions, so the figure's input contract is the instrument's real output
     shape - not a hand-written guess at it.
  2. make_figures.py runs as a subprocess (the real command line) and produces
     PNG + SVG + an annotations manifest.
  3. EVERY number drawn on the figure resolves, by the key path recorded in the
     manifest, to exactly that value in the input JSON. This is the traceability
     claim, tested mechanically rather than asserted.
  4. The watermark is FORCED on when the input declares synthetic:true - a
     synthetic render cannot be produced that is mistakable for data.
  5. The validator FAILS CLOSED on tampered input: a doctored Wilson interval, a
     wrong primary denominator, and an impossible segment count are each rejected.

SYNTHETIC DATA IS NOT DATA
  Everything this test writes lands in results/figures/synthetic/, every file name
  starts with SYNTHETIC_, the JSON carries "synthetic": true and a WARNING field,
  and both renders are stamped "SYNTHETIC - NOT DATA" across the middle. None of
  these numbers is a result, an estimate, or an illustration of a result. They are
  arbitrary integers chosen to exercise the drawing code, including the zero-
  detection and unpriced-cost paths.

    python scripts/test_make_figures.py
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import analysis_instrument as AI  # noqa: E402
import make_figures as MF  # noqa: E402

OUT = _REPO / "results" / "figures" / "synthetic"
STEM = "SYNTHETIC_main_figure"
INPUT = OUT / "SYNTHETIC_figure_input.json"
WATERMARK = "SYNTHETIC — NOT DATA"

_checks = 0
_fails: list[str] = []


def check(cond: bool, label: str) -> None:
    global _checks
    _checks += 1
    if cond:
        print(f"  ok   {label}")
    else:
        _fails.append(label)
        print(f"  FAIL {label}")


# --------------------------------------------------------------- synthetic builders
def det_rows(n_full: int, n_partial: int, n_miss: int, n_refusal: int) -> list[dict]:
    """Rows in the shape analysis_instrument.detection_rates() consumes."""
    rows = []
    for grade, count in (("FULL", n_full), ("PARTIAL", n_partial), ("MISS", n_miss)):
        rows += [{"outcome": "verdict_bearing", "grade": grade}] * count
    rows += [{"outcome": "refusal_no_verdict", "grade": None}] * n_refusal
    return rows


def null_rows(n_fp: int, n_correct: int, n_refusal: int) -> list[dict]:
    """Rows in the shape analysis_instrument.l0_false_positive_rates() consumes."""
    rows = [{"outcome": "verdict_bearing", "verdict": "diff", "fp_frozen_rule": True}] * n_fp
    rows += [{"outcome": "verdict_bearing", "verdict": "no_meaningful_diff",
              "fp_frozen_rule": False}] * n_correct
    rows += [{"outcome": "refusal_no_verdict", "verdict": None,
              "fp_frozen_rule": False}] * n_refusal
    return rows


def build_synthetic() -> dict:
    """Arbitrary integers, run through the instrument's real estimand functions."""
    v0, v1 = "agent v0", "agent v1"
    b1, b3 = "Baseline 1 - fixed battery", "Baseline 3 - introspection"

    # (FULL, PARTIAL, MISS, REFUSAL) per condition x rung. Arbitrary. Not results.
    plan = {
        v0: {"L1": (4, 0, 0, 1), "L2": (2, 2, 1, 0), "L3": (0, 3, 1, 1),
             "L4v3": (0, 1, 3, 1)},
        v1: {"L1": (3, 0, 0, 0), "L2": (1, 1, 1, 0), "L3": (0, 1, 2, 0)},
        b1: {"L1": (1, 0, 0, 0), "L2": (0, 1, 0, 0), "L3": (0, 0, 1, 0),
             "L4v3": (0, 0, 1, 0)},
        b3: {"L1": (0, 1, 0, 0), "L2": (0, 0, 1, 0), "L3": (0, 0, 1, 0),
             "L4v3": (0, 0, 1, 0)},
    }
    detection = {c: {r: AI.detection_rates(det_rows(*t)) for r, t in rungs.items()}
                 for c, rungs in plan.items()}

    # (FP, correct rejection, refusal) on the null. Arbitrary. Not results.
    nulls = {v0: (2, 16, 2), v1: (1, 9, 0), b1: (0, 1, 0), b3: (1, 0, 0)}
    null = {c: AI.l0_false_positive_rates(null_rows(*t)) for c, t in nulls.items()}
    null_subset = {v0: AI.l0_false_positive_rates(null_rows(1, 8, 1))}

    def n_full(cond: str) -> int:
        return sum(detection[cond][r]["full_all_attempts_PRIMARY"]["k"]
                   for r in detection[cond])

    cost = {
        v0: AI.dollars_per_detection(11.4884, n_full(v0), False),
        v1: AI.dollars_per_detection(6.2010, n_full(v1), False),
        # exercises the zero-detection branch: must print `undefined`, never inf
        b3: AI.dollars_per_detection(0.9142, 0, False),
        # exercises the unpriced branch: must leave the dollar ranking entirely
        b1: AI.dollars_per_detection(None, 1, True),
    }

    return {
        "schema": MF.SCHEMA,
        "synthetic": True,
        "WARNING": ("SYNTHETIC INSTRUMENT TEST FIXTURE - NOT DATA, NOT A RESULT, NOT AN "
                    "ESTIMATE. Arbitrary integers chosen to exercise every drawing "
                    "branch. Never quote, aggregate or cite any number in this file."),
        "generated_by": "scripts/test_make_figures.py",
        "provenance": {
            "estimands_computed_by": "scripts/analysis_instrument.py",
            "functions": ["detection_rates", "l0_false_positive_rates",
                          "dollars_per_detection"],
            "note": ("blocks below are verbatim return values of those functions, so "
                     "this fixture cannot drift from the instrument's real output shape"),
        },
        "conditions": [v0, v1, b1, b3],
        "designed_rungs": ["L1", "L2", "L3"],
        "exploratory_rungs": ["L4v3"],
        "single_decision_conditions": [b1, b3],
        "detection": detection,
        "null": null,
        "null_subset": null_subset,
        "null_subset_label": "SYNTHETIC subset (stands in for the frozen n=10)",
        "cost": cost,
    }


# ------------------------------------------------------------------------- the test
def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    doc = build_synthetic()
    INPUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                     encoding="utf-8")
    print(f"wrote synthetic fixture: {INPUT.relative_to(_REPO)}\n")

    print("1. render via the real command line")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_HERE / "make_figures.py"),
         "--input", str(INPUT), "--outdir", str(OUT), "--stem", STEM,
         "--title", "SYNTHETIC FIXTURE - instrument test, not a result"],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
    check(proc.returncode == 0, "make_figures.py exits 0")

    png, svg = OUT / f"{STEM}.png", OUT / f"{STEM}.svg"
    man_path = OUT / f"{STEM}_annotations.json"
    check(png.exists() and png.stat().st_size > 50_000, "PNG written and non-trivial")
    check(svg.exists() and svg.stat().st_size > 20_000, "SVG written and non-trivial")
    check(man_path.exists(), "annotations manifest written")
    check(png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "PNG has real PNG magic bytes")
    check("<svg" in svg.read_text(encoding="utf-8", errors="replace")[:4000],
          "SVG is real SVG markup")
    if not man_path.exists():
        return report()
    man = json.loads(man_path.read_text(encoding="utf-8"))

    print("\n2. synthetic renders cannot be mistaken for data")
    check(man["watermark"] == WATERMARK,
          'watermark forced to "SYNTHETIC - NOT DATA" by synthetic:true')
    check(man["input_is_synthetic"] is True, "manifest records the input as synthetic")
    check(all(p.name.startswith("SYNTHETIC_") for p in (png, svg, man_path, INPUT)),
          "every emitted file name starts with SYNTHETIC_")
    check(OUT.name == "synthetic" and OUT.parent.name == "figures",
          "everything lands under results/figures/synthetic/")
    check("NOT DATA" in doc["WARNING"], "fixture JSON carries an explicit warning")

    print("\n3. every number on the figure traces to the input JSON")
    check(man["n_annotations"] == len(man["annotations"]) and man["n_annotations"] > 25,
          f"manifest lists {man['n_annotations']} drawn numbers")
    bad, checked = [], 0
    for a in man["annotations"]:
        if not a["fields"]:
            bad.append(f"{a['kind']}: no source fields recorded")
            continue
        for fld in a["fields"]:
            checked += 1
            try:
                actual = MF.dig(doc, fld["path"])
            except (KeyError, IndexError, TypeError) as exc:
                bad.append(f"{a['kind']}: path {fld['path']} does not resolve ({exc})")
                continue
            if actual != fld["value"]:
                bad.append(f"{a['kind']}: path {fld['path']} is {actual!r}, "
                           f"manifest recorded {fld['value']!r}")
    check(not bad, f"all {checked} recorded source values match the input JSON")
    for b in bad[:8]:
        print(f"       {b}")

    print("\n4. spot-check the printed strings against the fixture by hand")
    v0 = "agent v0"
    w = doc["detection"][v0]["L2"]["full_all_attempts_PRIMARY"]
    kn = [a for a in man["annotations"]
          if a["kind"] == "full_k_over_n"
          and a["fields"][0]["path"] == ["detection", v0, "L2",
                                         "full_all_attempts_PRIMARY", "k"]]
    check(len(kn) == 1 and kn[0]["text"] == f"{w['k']}/{w['n']}" == "2/5",
          "printed FULL k/n for a known cell is exactly 2/5")

    fpr = doc["null"][v0]["fp_frozen_rule_verdict_bearing_PRIMARY"]
    prim = [a for a in man["annotations"]
            if a["kind"] == "fpr_primary_verdict_bearing"
            and a["fields"][0]["path"][1] == v0]
    check(len(prim) == 1 and prim[0]["text"] == AI.fmt_rate(fpr),
          f"printed primary FPR string is the instrument's own: {AI.fmt_rate(fpr)}")
    check(fpr["n"] == doc["null"][v0]["n_verdict_bearing"] == 18,
          "primary FPR denominator is verdict-bearing (18), not all attempts (20)")

    undef = [a for a in man["annotations"] if a["kind"] == "cost_undefined"]
    check(len(undef) == 1 and undef[0]["text"].startswith("undefined (0 detections;"),
          "zero-detection cost prints `undefined (...)`, never infinity")
    unpriced = [a for a in man["annotations"] if a["kind"] == "cost_unpriced"]
    check(len(unpriced) == 1,
          "unpriced condition is excluded from the dollar ranking, not zeroed")
    single = [a for a in man["annotations"] if a["kind"] == "single_decision_no_interval"]
    check(len(single) >= 6,
          "pair-level-decision conditions get no Wilson interval on any rung")
    wil = [a for a in man["annotations"] if a["kind"] == "full_wilson_95"]
    check(len(wil) >= 6, "seed-paired conditions do get Wilson intervals")

    print("\n5. the validator fails closed on tampered input")
    good = MF.validate(doc)
    check(not good, "the honest fixture validates clean")

    t1 = copy.deepcopy(doc)
    t1["detection"][v0]["L2"]["full_all_attempts_PRIMARY"]["hi"] = 0.99
    check(any("wilson" in m for m in MF.validate(t1)),
          "a doctored Wilson bound is rejected (recomputed against the instrument)")

    t2 = copy.deepcopy(doc)
    t2["null"][v0]["fp_frozen_rule_verdict_bearing_PRIMARY"]["n"] = \
        t2["null"][v0]["n_planned_attempts"]
    check(any("VERDICT-BEARING" in m for m in MF.validate(t2)),
          "swapping the L0 primary denominator to all-attempts is rejected")

    t3 = copy.deepcopy(doc)
    t3["detection"][v0]["L1"]["grade_counts"]["FULL"] = 99
    check(any("exceeds planned attempts" in m or "!= interval k" in m
              for m in MF.validate(t3)),
          "an impossible segment count is rejected")

    t4 = copy.deepcopy(doc)
    t4["schema"] = "something_else/9"
    check(any("schema must be" in m for m in MF.validate(t4)),
          "a foreign schema is rejected")

    print("\n6. portability (this repo has been bitten here before)")
    # scripts/expression_matrix.py once used syntax that is legal from 3.12 and a
    # SyntaxError on 3.11, so the repo could not reproduce its own analysis on a
    # reviewer's stock interpreter. Do not repeat it.
    older = _oldest_interpreter()
    if older is None:
        print("  skip Python 3.11 not available on this box - verify before shipping")
    else:
        r = subprocess.run(
            [older, "-c",
             "import py_compile;"
             "py_compile.compile(r'scripts/make_figures.py', doraise=True);"
             "py_compile.compile(r'scripts/test_make_figures.py', doraise=True)"],
            cwd=_REPO, capture_output=True, text=True)
        check(r.returncode == 0,
              f"both scripts compile on {Path(older).name} 3.11 "
              f"(no 3.12-only syntax){'' if r.returncode == 0 else ': ' + r.stderr[-300:]}")

    return report()


def _oldest_interpreter() -> str | None:
    """Path to a 3.11 interpreter if one is installed, else None."""
    for cand in (["py", "-3.11"], ["python3.11"]):
        try:
            r = subprocess.run(cand + ["-c", "import sys;print(sys.executable)"],
                               capture_output=True, text=True, timeout=25)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def report() -> int:
    print(f"\n{'=' * 62}")
    if _fails:
        print(f"FAILED {len(_fails)}/{_checks} checks:")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print(f"ALL {_checks} CHECKS PASS")
    print("Synthetic only. Nothing in results/figures/synthetic/ is a result.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
