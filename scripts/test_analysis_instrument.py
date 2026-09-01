#!/usr/bin/env python3
"""Synthetic-input tests for the analysis instrument. No files, no network, no models.

Addendum E requires the aggregation to be tested code before unsealing. The cases
below are chosen to hit the places where a plausible-looking implementation would be
quietly wrong: zero-denominator cells, 0/n and n/n rates where Wald intervals
misbehave, refusals pulling the two denominators in OPPOSITE directions for detection
vs false positives, zero detections in the cost formula, and kappa's undefined case.

    PYTHONPATH=src python scripts/test_analysis_instrument.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

from analysis_instrument import (agreement, detection_rates,  # noqa: E402
                                 dollars_per_detection, l0_false_positive_rates,
                                 outcome, wilson)


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    return ok


def close(a, b, tol=5e-4):
    return a is not None and abs(a - b) <= tol


def main() -> int:
    ok = True

    print("1. Wilson interval against the amendment's own worked example")
    w = wilson(4, 20)
    ok &= check("4/20 rate = 20.0%", close(w["rate"], 0.20))
    ok &= check("lower = 8.1%", close(w["lo"], 0.081), f"{w['lo']*100:.2f}%")
    ok &= check("upper = 41.6%", close(w["hi"], 0.416), f"{w['hi']*100:.2f}%")
    w0 = wilson(0, 10)
    ok &= check("0/10 stays inside [0,1] and has non-zero width",
                w0["lo"] == 0.0 and 0 < w0["hi"] < 1, f"hi={w0['hi']:.4f}")
    w1 = wilson(10, 10)
    ok &= check("10/10 stays inside [0,1] and has non-zero width",
                w1["hi"] == 1.0 and 0 < w1["lo"] < 1, f"lo={w1['lo']:.4f}")
    ok &= check("empty denominator is undefined, not a crash or a zero",
                wilson(0, 0)["rate"] is None)

    print("\n2. outcome mapping (Amendment 6 clarification 1)")
    ok &= check("terminal refusal", outcome(
        {"status": "brain_refusal", "verdict": None}) == "refusal_no_verdict")
    ok &= check("mid-run refusal WITH a verdict is verdict-bearing", outcome(
        {"status": "completed_forced", "verdict": {"verdict": "diff"}})
        == "verdict_bearing")
    ok &= check("brain_refusal that still submitted is verdict-bearing", outcome(
        {"status": "brain_refusal", "verdict": {"verdict": "diff"}})
        == "verdict_bearing")
    ok &= check("no verdict, other cause", outcome(
        {"status": "no_verdict", "verdict": None}) == "no_verdict_other")

    print("\n3. detection rate: refusals count AGAINST the agent (primary)")
    rows = ([{"outcome": "verdict_bearing", "grade": "FULL"}] * 2 +
            [{"outcome": "verdict_bearing", "grade": "MISS"}] * 2 +
            [{"outcome": "refusal_no_verdict", "grade": None}])
    d = detection_rates(rows)
    ok &= check("primary denominator is all 5 attempts",
                d["full_all_attempts_PRIMARY"]["n"] == 5)
    ok &= check("primary rate = 2/5 = 40%",
                close(d["full_all_attempts_PRIMARY"]["rate"], 0.4))
    ok &= check("verdict-bearing variant = 2/4 = 50%",
                close(d["full_verdict_bearing"]["rate"], 0.5))
    ok &= check("primary is the LOWER of the two (conservative)",
                d["full_all_attempts_PRIMARY"]["rate"]
                < d["full_verdict_bearing"]["rate"])
    ok &= check("refusal rate reported = 1/5", close(d["refusal_rate"]["rate"], 0.2))

    print("\n4. L0 false positives: refusals must NOT deflate the rate")
    l0 = ([{"outcome": "verdict_bearing", "verdict": "diff", "fp_frozen_rule": True}] * 2 +
          [{"outcome": "verdict_bearing", "verdict": "no_meaningful_diff",
            "fp_frozen_rule": False}] * 2 +
          [{"outcome": "refusal_no_verdict", "verdict": None, "fp_frozen_rule": False}] * 6)
    f = l0_false_positive_rates(l0)
    ok &= check("primary denominator is verdict-bearing (4), not 10",
                f["fp_frozen_rule_verdict_bearing_PRIMARY"]["n"] == 4)
    ok &= check("primary rate = 2/4 = 50%",
                close(f["fp_frozen_rule_verdict_bearing_PRIMARY"]["rate"], 0.5))
    ok &= check("all-attempts burden view = 2/10 = 20%",
                close(f["fp_frozen_rule_all_attempts"]["rate"], 0.2))
    ok &= check("primary is the HIGHER of the two (conservative for FP)",
                f["fp_frozen_rule_verdict_bearing_PRIMARY"]["rate"]
                > f["fp_frozen_rule_all_attempts"]["rate"])
    ok &= check("the two estimands use OPPOSITE denominators by design",
                d["full_all_attempts_PRIMARY"]["n"] == len(rows)
                and f["fp_frozen_rule_verdict_bearing_PRIMARY"]["n"] < len(l0))

    print("\n5. dollars per detection")
    c = dollars_per_detection(10.0, 4, any_unpriced=False)
    ok &= check("priced with detections = 10/4 = 2.5", close(c["primary"], 2.5))
    c0 = dollars_per_detection(7.25, 0, any_unpriced=False)
    ok &= check("zero detections -> undefined string, not inf",
                isinstance(c0["primary"], str) and "undefined" in c0["primary"],
                str(c0["primary"]))
    ok &= check("the undefined string still carries the spend",
                "7.2500" in c0["primary"])
    cu = dollars_per_detection(10.0, 4, any_unpriced=True)
    ok &= check("unpriced -> null primary", cu["primary"] is None)
    ok &= check("unpriced -> excluded from dollar rankings",
                cu["eligible_for_dollar_ranking"] is False)
    cd = dollars_per_detection(10.0, 2, any_unpriced=False,
                               spend_verdict_bearing=8.0, n_full_vb=2)
    ok &= check("diagnostic verdict-bearing variant present",
                close(cd["diagnostic_verdict_bearing"], 4.0))

    print("\n6. agreement statistics")
    h = ["FULL", "FULL", "PARTIAL", "MISS", "MISS"]
    j = ["FULL", "PARTIAL", "PARTIAL", "MISS", "FULL"]
    ag = agreement(h, j)
    ok &= check("raw agreement = 3/5", close(ag["raw_percent_agreement"], 0.6))
    ok &= check("confusion matrix totals to n",
                sum(sum(r.values()) for r in
                    ag["confusion_matrix_human_rows_judge_cols"].values()) == 5)
    ok &= check("binary cell counts", ag["binary_FULL_vs_not"] ==
                {"both_FULL": 1, "human_only_FULL": 1, "judge_only_FULL": 1,
                 "neither_FULL": 2})
    ok &= check("positive agreement = 2*1/(2*1+1+1) = 0.5",
                close(ag["positive_agreement_FULL"], 0.5))
    ok &= check("negative agreement = 2*2/(2*2+1+1) = 0.667",
                close(ag["negative_agreement_FULL"], 2 / 3))
    ok &= check("kappa present as secondary",
                ag["cohens_kappa_SECONDARY"] is not None)
    perfect = agreement(["FULL"] * 4, ["FULL"] * 4)
    ok &= check("kappa undefined when one label is used throughout (pe=1)",
                perfect["cohens_kappa_SECONDARY"] is None
                and close(perfect["raw_percent_agreement"], 1.0),
                "raw agreement is still 100% - which is why kappa is secondary")

    print(f"\n{'ANALYSIS INSTRUMENT TESTS PASSED' if ok else 'ANALYSIS INSTRUMENT TESTS FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
