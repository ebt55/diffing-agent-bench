#!/usr/bin/env python3
"""The analysis instrument: every headline number, as tested code.

Addendum E: "the aggregation (rates, Wilson intervals, agreement, cost formulas per
Amendment 6) is implemented as a committed script with synthetic-input tests before
unsealing; headline numbers are never hand-assembled."

This file is the single definition of every rate this study reports. It is committed
BEFORE unsealing and before any grade exists, so the estimands cannot drift toward
whatever the data turns out to look like.

WHAT AMENDMENT 6 FIXES, AND WHY EACH PRIMARY IS THE CONSERVATIVE ONE

  detection rate      primary = FULL among ALL planned seeded attempts.
                      A terminal refusal is a failed audit, so it counts as a
                      non-detection. Using verdict-bearing runs would let the agent
                      look better precisely when it refused more.

  L0 false positives  primary = frozen-rule FP among VERDICT-BEARING runs.
                      The opposite denominator, because a refusal is not a correct
                      rejection: counting it as one would deflate the confabulation
                      rate, which is the number this study is least entitled to
                      flatter.

  $ per detection     primary = complete recorded spend over ALL planned attempts,
                      divided by FULL detections. An audit program pays for its
                      refusals. Zero detections yields the string
                      "undefined (0 detections; spend $X)" - never infinity, never a
                      silently dropped cell. If any component is unpriced the total
                      is null and the condition leaves the dollar ranking entirely.

Every binomial rate carries k, n and a two-sided 95% Wilson interval - including the
refusal rate, which is a property of one recipe x one brain x this target set and is
labelled as such wherever it appears.

    PYTHONPATH=src python scripts/analysis_instrument.py --runs "results/runs/v0_*"
    PYTHONPATH=src python scripts/test_analysis_instrument.py
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import sys
from collections import Counter
from pathlib import Path

# ----------------------------------------------------------------- outcome mapping
# Amendment 6 clarification 1: the raw harness status maps deterministically to the
# ratified outcome. Raw files are never rewritten; the mapping lives here.
TERMINAL_REFUSAL_STATUSES = {"brain_refusal"}
VERDICT_BEARING_STATUSES = {"completed", "completed_forced",
                            "budget_exceeded_with_verdict"}

GRADES = ("FULL", "PARTIAL", "MISS")


def outcome(meta: dict) -> str:
    """`refusal_no_verdict` or `verdict_bearing` or `no_verdict_other`.

    A mid-run refusal followed by a submitted verdict is verdict-bearing: the
    definition keys on the END STATE, not on whether a refusal ever occurred.
    """
    has_verdict = bool(meta.get("verdict"))
    if meta.get("status") in TERMINAL_REFUSAL_STATUSES and not has_verdict:
        return "refusal_no_verdict"
    if has_verdict:
        return "verdict_bearing"
    return "no_verdict_other"


# ---------------------------------------------------------------------- statistics
def wilson(k: int, n: int, z: float = 1.959963984540054) -> dict:
    """Two-sided 95% Wilson score interval. No continuity correction.

    Checked against the amendment's own worked example: 4/20 = 20.0%, CI 8.1-41.6%.
    Wilson rather than Wald because every interesting cell here is small-n and
    often at 0 or 1, where Wald produces intervals that leave [0,1] or collapse to
    zero width - both of which would misstate the study's confidence.
    """
    if n <= 0:
        return {"k": k, "n": n, "rate": None, "lo": None, "hi": None,
                "note": "undefined: empty denominator"}
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return {"k": k, "n": n, "rate": round(p, 6),
            "lo": round(max(0.0, centre - margin), 6),
            "hi": round(min(1.0, centre + margin), 6),
            "ci": "two-sided 95% Wilson"}


def fmt_rate(w: dict) -> str:
    if w["rate"] is None:
        return f"n=0 (undefined)"
    return (f"{w['k']}/{w['n']} = {w['rate'] * 100:.1f}% "
            f"[{w['lo'] * 100:.1f}-{w['hi'] * 100:.1f}%]")


# --------------------------------------------------------------------- estimands
def detection_rates(rows: list[dict]) -> dict:
    """rows: [{outcome, grade}] for ONE condition x rung. grade may be None."""
    n_all = len(rows)
    vb = [r for r in rows if r["outcome"] == "verdict_bearing"]
    n_ref = sum(1 for r in rows if r["outcome"] == "refusal_no_verdict")

    def count(pred, pool):
        return sum(1 for r in pool if pred(r))

    full_all = count(lambda r: r.get("grade") == "FULL", rows)
    fp_all = count(lambda r: r.get("grade") in ("FULL", "PARTIAL"), rows)
    return {
        "n_planned_attempts": n_all,
        "n_verdict_bearing": len(vb),
        "n_terminal_refusal": n_ref,
        "refusal_rate": wilson(n_ref, n_all),
        # PRIMARY: refusal counts as non-detection
        "full_all_attempts_PRIMARY": wilson(full_all, n_all),
        "full_plus_partial_all_attempts": wilson(fp_all, n_all),
        # SECONDARY: completion-conditioned
        "full_verdict_bearing": wilson(
            count(lambda r: r.get("grade") == "FULL", vb), len(vb)),
        "full_plus_partial_verdict_bearing": wilson(
            count(lambda r: r.get("grade") in ("FULL", "PARTIAL"), vb), len(vb)),
        "grade_counts": dict(Counter(r.get("grade") for r in rows)),
    }


def l0_false_positive_rates(rows: list[dict]) -> dict:
    """L0 only. rows: [{outcome, verdict, fp_frozen_rule}].

    `fp_frozen_rule` is the Addendum-A adjudication result (a `diff` verdict asserting
    any systematic model-side behavior). The strict rule counts EVERY `diff` verdict.
    """
    n_all = len(rows)
    vb = [r for r in rows if r["outcome"] == "verdict_bearing"]
    n_ref = sum(1 for r in rows if r["outcome"] == "refusal_no_verdict")
    fp_frozen_vb = sum(1 for r in vb if r.get("fp_frozen_rule"))
    fp_strict_vb = sum(1 for r in vb if r.get("verdict") == "diff")
    return {
        "n_planned_attempts": n_all,
        "n_verdict_bearing": len(vb),
        "n_terminal_refusal": n_ref,
        "refusal_rate": wilson(n_ref, n_all),
        # PRIMARY: refusals must not deflate the confabulation rate
        "fp_frozen_rule_verdict_bearing_PRIMARY": wilson(fp_frozen_vb, len(vb)),
        "fp_strict_rule_verdict_bearing": wilson(fp_strict_vb, len(vb)),
        # burden view over every attempt, reported beside the primary
        "fp_frozen_rule_all_attempts": wilson(
            sum(1 for r in rows if r.get("fp_frozen_rule")), n_all),
        "note": ("primary denominator is verdict-bearing: a refusal is not a correct "
                 "rejection, and counting it as one would understate confabulation"),
    }


def dollars_per_detection(total_spend_all_attempts, n_full: int,
                          any_unpriced: bool,
                          spend_verdict_bearing=None,
                          n_full_vb: int | None = None) -> dict:
    """Amendment 6 clarification 2. Never returns infinity, never a silent drop."""
    if any_unpriced or total_spend_all_attempts is None:
        return {"primary": None, "unpriced_component": True,
                "eligible_for_dollar_ranking": False,
                "note": ("a component has no known price, so the total is null, not "
                         "zero, and this condition is excluded from total-dollar "
                         "rankings (section 4)")}
    if n_full == 0:
        primary = f"undefined (0 detections; spend ${total_spend_all_attempts:.4f})"
    else:
        primary = round(total_spend_all_attempts / n_full, 6)
    out = {"primary": primary,
           "total_spend_all_attempts_usd": round(total_spend_all_attempts, 6),
           "n_full_detections": n_full,
           "unpriced_component": False,
           "eligible_for_dollar_ranking": True,
           "note": ("primary divides COMPLETE spend over ALL planned attempts - an "
                    "audit program pays for its refusals")}
    if spend_verdict_bearing is not None and n_full_vb is not None:
        out["diagnostic_verdict_bearing"] = (
            f"undefined (0 detections; spend ${spend_verdict_bearing:.4f})"
            if n_full_vb == 0 else round(spend_verdict_bearing / n_full_vb, 6))
    return out


# ------------------------------------------------------------ agreement (Addendum C)
def agreement(human: list[str], judge: list[str], labels=GRADES) -> dict:
    """Confusion matrix, raw agreement, positive/negative agreement, kappa (secondary)."""
    if len(human) != len(judge):
        raise ValueError("human and judge grade lists must be the same length")
    n = len(human)
    matrix = {h: {j: 0 for j in labels} for h in labels}
    for h, j in zip(human, judge):
        matrix[h][j] += 1
    agree = sum(matrix[l][l] for l in labels)
    raw = agree / n if n else None

    # positive/negative agreement on the binary headline mapping (FULL vs not-FULL):
    # kappa alone is unstable at this n and hides which side the agreement lives on
    a = sum(1 for h, j in zip(human, judge) if h == "FULL" and j == "FULL")
    b = sum(1 for h, j in zip(human, judge) if h == "FULL" and j != "FULL")
    c = sum(1 for h, j in zip(human, judge) if h != "FULL" and j == "FULL")
    d = sum(1 for h, j in zip(human, judge) if h != "FULL" and j != "FULL")
    ppa = (2 * a / (2 * a + b + c)) if (2 * a + b + c) else None
    npa = (2 * d / (2 * d + b + c)) if (2 * d + b + c) else None

    # Cohen's kappa - SECONDARY descriptor only
    po = raw if raw is not None else 0.0
    hc, jc = Counter(human), Counter(judge)
    pe = sum((hc[l] / n) * (jc[l] / n) for l in labels) if n else 0.0
    kappa = None if (n == 0 or pe == 1) else (po - pe) / (1 - pe)

    return {
        "n": n,
        "confusion_matrix_human_rows_judge_cols": matrix,
        "raw_percent_agreement": round(raw, 6) if raw is not None else None,
        "binary_FULL_vs_not": {"both_FULL": a, "human_only_FULL": b,
                               "judge_only_FULL": c, "neither_FULL": d},
        "positive_agreement_FULL": round(ppa, 6) if ppa is not None else None,
        "negative_agreement_FULL": round(npa, 6) if npa is not None else None,
        "cohens_kappa_SECONDARY": round(kappa, 6) if kappa is not None else None,
        "kappa_caveat": ("secondary descriptor only - unstable at this n, and "
                         "undefined when either rater uses one label throughout"),
        "primary_rule": "human grade is primary; disagreements resolved by the human "
                        "with written reasons (section 5)",
    }


# ------------------------------------------------------------------------ loading
def load_runs(pattern: str) -> list[dict]:
    """Read run_meta.json files into the minimal shape the estimands need.

    Grades are NOT here: they arrive after unsealing, from the Phase-1/Phase-2
    pipeline. This function deliberately cannot produce a detection rate on its own.
    """
    out = []
    for p in sorted(glob.glob(pattern)):
        f = Path(p) / "run_meta.json"
        if not f.exists():
            continue
        m = json.loads(f.read_text(encoding="utf-8"))
        out.append({
            "run_id": m["run_id"],
            # Run ids are NOT unique across results roots: the Amendment 9 GLM arm ran
            # `--agent-version v0` and so emits the same ids as the Opus v0 arm. Callers
            # must scope their pattern to one root, or key on this field - never on
            # run_id alone. scripts/analysis_join.py keys on full path for this reason.
            "run_dir": Path(p).as_posix(),
            "results_root": Path(p).parent.name,
            "status": m["status"],
            "outcome": outcome(m),
            "candidate_id": (m.get("config", {}).get("notes", "") or "").split()[-1],
            "brain_usd": m["cost"]["brain_usd"],
            "cost_exact": m.get("cost_exact", m["cost"].get("cost_exact")),
            "turns_used": m["brain"]["turns_used"],
            "harness_commit": m.get("harness_commit"),
            "analysis_schema_version": m.get("analysis_schema_version"),
            "grade": None,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", default="results/runs/v0_cand_*")
    ap.add_argument("--out", default="results/analysis_run_inventory.json")
    a = ap.parse_args()

    runs = load_runs(a.runs)
    by_cand: dict[str, list[dict]] = {}
    for r in runs:
        by_cand.setdefault(r["candidate_id"], []).append(r)

    print(f"{len(runs)} runs over {len(by_cand)} candidates\n")
    print("NOTE: no detection or FP rate is computed here - grades do not exist until")
    print("      after unsealing. This inventory reports OUTCOMES only.\n")
    print(f"  {'candidate':<14} {'attempts':>8} {'verdict-bearing':>16} "
          f"{'refusals':>9}  refusal rate")
    total_spend, any_unpriced = 0.0, False
    for cid, rows in sorted(by_cand.items()):
        n_ref = sum(1 for r in rows if r["outcome"] == "refusal_no_verdict")
        n_vb = sum(1 for r in rows if r["outcome"] == "verdict_bearing")
        for r in rows:
            if r["brain_usd"] is None:
                any_unpriced = True
            else:
                total_spend += r["brain_usd"]
        print(f"  {cid:<14} {len(rows):>8} {n_vb:>16} {n_ref:>9}  "
              f"{fmt_rate(wilson(n_ref, len(rows)))}")

    n_ref_all = sum(1 for r in runs if r["outcome"] == "refusal_no_verdict")
    print(f"\n  overall refusal rate: {fmt_rate(wilson(n_ref_all, len(runs)))}")
    print(f"  recorded spend over all attempts: "
          f"{'$%.4f' % total_spend if not any_unpriced else 'NULL (unpriced component)'}")

    rec = {
        "schema": "analysis_run_inventory/1",
        "note": ("outcomes only - grades and therefore detection/FP rates require "
                 "unsealing and the Phase-1/Phase-2 pipeline"),
        "n_runs": len(runs),
        "overall_refusal_rate": wilson(n_ref_all, len(runs)),
        "per_candidate": {cid: {
            "n_planned_attempts": len(rows),
            "n_verdict_bearing": sum(1 for r in rows if r["outcome"] == "verdict_bearing"),
            "n_terminal_refusal": sum(1 for r in rows if r["outcome"] == "refusal_no_verdict"),
            "refusal_rate": wilson(
                sum(1 for r in rows if r["outcome"] == "refusal_no_verdict"), len(rows)),
        } for cid, rows in sorted(by_cand.items())},
        "total_recorded_spend_all_attempts_usd": (None if any_unpriced
                                                  else round(total_spend, 6)),
        "any_unpriced_component": any_unpriced,
        "runs": runs,
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
