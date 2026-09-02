"""An UNGRADED cell must never render as a correct rejection or a false positive.

Panel B derived its correct-rejection segment by subtraction - verdict_bearing minus
false positives - so a pair with NO Phase-2 grade drew as a solid-green 100% correct
rejection off the mere absence of an FP. That is a fabricated outcome, and this pins
it shut: the figure input carries an explicit per-cell `ungraded` flag, and an ungraded
cell contributes zero to both the FP and the CR segments.

Run: python scripts/test_ungraded_render.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import analysis_join as AJ  # noqa: E402
import make_figures as MF   # noqa: E402

_checks = 0
_fails: list[str] = []


def check(cond: bool, label: str) -> None:
    global _checks
    _checks += 1
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        _fails.append(label)


def row(cond, rung, grade, outcome="verdict_bearing"):
    return {"condition": cond, "rung": rung, "grade": grade, "outcome": outcome,
            "verdict_type": "diff" if grade == "FP" else "no_meaningful_diff"}


def main() -> int:
    print("1. the blocks carry an explicit ungraded flag")
    graded = AJ.null_block([row("v0_opus", "L0", "CR"), row("v0_opus", "L0", "FP")])
    ungraded = AJ.null_block([row("battery", "L0", None)])
    check(graded["ungraded"] is False and graded["n_graded"] == 2,
          "a graded L0 cell is not flagged ungraded")
    check(ungraded["ungraded"] is True and ungraded["n_graded"] == 0,
          "an L0 cell with no grade IS flagged ungraded")
    det_u = AJ.detection_block([row("battery", "L1", None)])
    check(det_u["ungraded"] is True, "the same flag exists on detection cells")

    print("\n2. a graded refusal is not conflated with an ungraded row")
    mixed = AJ.detection_block([row("v0_opus", "L2", "MISS"),
                                row("v0_opus", "L2", "REFUSAL_NO_VERDICT",
                                    "refusal_no_verdict"),
                                row("v0_opus", "L2", None)])
    gc = mixed["grade_counts"]
    check(gc.get("refusal_no_verdict") == 1 and gc.get("ungraded") == 1,
          f"refusal and ungraded occupy separate buckets ({gc})")

    print("\n3. an ungraded L0 cell renders as neither CR nor FP")
    # Reproduce Panel B's segment arithmetic exactly as make_figures does it.
    def segments(cell):
        n = cell["n_planned_attempts"]
        fp = cell["fp_frozen_rule_verdict_bearing_PRIMARY"]
        k_ref = cell["n_terminal_refusal"]
        if cell.get("ungraded"):
            k_fp = k_ok = 0
        else:
            k_fp = int(fp.get("k") or 0)
            k_ok = cell["n_verdict_bearing"] - k_fp
        return {"FP": k_fp, "CR": k_ok, "refusal": k_ref,
                "other_ungraded": n - (k_fp + k_ok + k_ref)}

    seg_u = segments(ungraded)
    check(seg_u["FP"] == 0 and seg_u["CR"] == 0,
          f"ungraded cell contributes 0 to BOTH the FP and CR segments ({seg_u})")
    check(seg_u["other_ungraded"] == 1,
          f"its run lands in the hatched UNGRADED/OTHER segment ({seg_u})")
    seg_g = segments(graded)
    check(seg_g["FP"] == 1 and seg_g["CR"] == 1,
          f"a genuinely graded cell still renders FP and CR ({seg_g})")

    print("\n4. make_figures accepts the flagged document and draws it")
    doc = json.loads((Path(__file__).resolve().parents[1] /
                      "results/analysis/analysis_figure_input.json")
                     .read_text(encoding="utf-8"))
    check(not MF.validate(doc), "the real figure input still validates")
    nulls = doc.get("null", {})
    flagged = [c for c, b in nulls.items() if b.get("ungraded")]
    check(flagged, f"the real document flags its ungraded L0 cells ({flagged})")
    for c in flagged:
        s = segments(nulls[c])
        check(s["FP"] == 0 and s["CR"] == 0,
              f"real ungraded cell {c} draws no CR and no FP ({s})")

    import subprocess
    with tempfile.TemporaryDirectory() as td:
        repo = Path(__file__).resolve().parents[1]
        p = subprocess.run(
            [sys.executable, str(_HERE / "make_figures.py"),
             "--input", str(repo / "results/analysis/analysis_figure_input.json"),
             "--outdir", td, "--stem", "t"],
            capture_output=True, text=True, timeout=600)
        check(p.returncode == 0,
              f"make_figures renders the flagged document without error "
              f"({(p.stderr or '')[-160:]})")
        ann = json.loads((Path(td) / "t_annotations.json").read_text(encoding="utf-8"))
        drawn = [a for a in ann["annotations"]
                 if a.get("panel") == "B-null"
                 and a.get("kind") == "fpr_primary_verdict_bearing"]
        ung = [a for a in drawn if a.get("text") == "UNGRADED"]
        check(not any("%" in (a.get("text") or "") for a in ung),
              "no rate is printed on an ungraded cell")
        check(len(ung) == len(flagged),
              f"an UNGRADED label is drawn for each ungraded L0 cell "
              f"({len(ung)} labels vs {len(flagged)} cells)")

        print("\n5. an ungraded DETECTION cell prints no k/n either (Panel A)")
        # "0/1" over a hatched bar reads as a measured miss. The same flag that guards
        # Panel B must guard Panel A: no k/n, no rate, no interval, an UNGRADED label.
        det_flagged = [(c, r) for c, rungs in doc.get("detection", {}).items()
                       for r, b in rungs.items() if b.get("ungraded")]
        check(det_flagged,
              f"the real document flags its ungraded detection cells "
              f"({len(det_flagged)} cells)")
        a_panels = ("A", "A-exploratory")
        rate_kinds = ("full_k_over_n", "full_wilson_95", "single_decision_no_interval")
        for c, r in det_flagged:
            mine = [a for a in ann["annotations"] if a.get("panel") in a_panels
                    and a["fields"] and a["fields"][0]["path"][:3] == ["detection", c, r]]
            kinds = {a["kind"] for a in mine}
            check(not (kinds & set(rate_kinds)),
                  f"{c}/{r}: no k/n, rate or interval annotation ({sorted(kinds)})")
            check("ungraded_no_rate" in kinds,
                  f"{c}/{r}: an UNGRADED label is drawn instead")
            check(not any("/" in (a.get("text") or "") and a["kind"] != "verdict_bearing_n"
                          for a in mine),
                  f"{c}/{r}: the only k/n-shaped text left is the verdict-bearing count")

    print(f"\n{'=' * 62}")
    if _fails:
        print(f"FAILED {len(_fails)}/{_checks} checks:")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print(f"ALL {_checks} CHECKS PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
