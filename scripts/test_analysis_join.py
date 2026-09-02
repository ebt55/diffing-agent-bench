#!/usr/bin/env python3
"""Synthetic end-to-end proof for scripts/analysis_join.py.

Builds a complete fake campaign - run_meta directories, Phase-1 claim rows, Phase-2
grade rows, a drift-floor file and a FAKE rung map - then runs the join twice (blind
and unsealed) and drives the real make_figures.py off its output. Nothing here touches
data/sealed/: the fake map lives beside the other fixtures and is named so it can never
be mistaken for the real one.

WHAT IT PROVES
  1. BLIND is the default and is genuinely blind: every rung is null, the figure input
     is NOT written, and tables.md refuses to print a rung-keyed table.
  2. UNSEALED (fake map) produces `analysis_figure_input/1`, and make_figures.py renders
     a PNG + SVG from it with no hand-assembly between the two.
  3. The Amendment 6 / Amendment 7 denominators are the ones actually used:
       - detection primary denominator == ALL planned attempts (refusal counted as a
         non-detection),
       - L0 FPR primary denominator == VERDICT-BEARING runs,
       - the frozen n=10 subset appears beside the n=20 primary.
  4. Arms never mix: the GLM arm is absent from `conditions`, and the exploratory rung
     is in `exploratory_rungs`, never in `designed_rungs`.
  5. The cost rules hold: zero detections gives `undefined (...)`, and any unpriced
     component removes the condition from the dollar ranking.
  6. Mid-run refusal events are counted (closing TODO T10).
  7. The join FAILS CLOSED: EXAMPLE rows, an incomplete map, a grade from the wrong
     vocabulary, an L0-grade on a non-null rung, and a grade on a refused run are each
     rejected rather than averaged in.
  8. Output is deterministic: two runs with a fixed --now are byte-identical.

SYNTHETIC DATA IS NOT DATA
  Every fixture lands under results/analysis/synthetic/, every candidate id is
  `cand_SYNTH*`, the map file is `SYNTHETIC_fake_rung_map.json`, and the render is
  watermarked. No number here is a result.

    python scripts/test_analysis_join.py
"""

from __future__ import annotations

import collections
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import analysis_join as AJ  # noqa: E402

ROOT = _REPO / "results" / "analysis" / "synthetic"
RUNS = ROOT / "runs"
MAP = ROOT / "SYNTHETIC_fake_rung_map.json"
P1 = ROOT / "SYNTHETIC_phase1_claims.jsonl"
P2 = ROOT / "SYNTHETIC_phase2_grades.jsonl"
FLOOR = ROOT / "SYNTHETIC_floor.json"
OUT_BLIND = ROOT / "out_blind"
OUT_UNSEAL = ROOT / "out_unsealed"
NOW = "2026-01-01T00:00:00Z"

# cand_SYNTH<x> -> rung. Fake. The real map is never opened by anything but the join,
# and only under an explicit flag.
FAKE_MAP = {"L0": "cand_SYNTHa", "L1": "cand_SYNTHb", "L2": "cand_SYNTHc",
            "L3": "cand_SYNTHd", "L4v3": "cand_SYNTHe"}
CAND = {v: k for k, v in FAKE_MAP.items()}

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


# ------------------------------------------------------------------ fixture writing
def write_run(run_id: str, *, status: str, seed: int, has_verdict: bool,
              brain_usd: float | None, cost_exact: bool = True,
              midrun_refusals: int = 0, brain: str = "claude-opus-5") -> None:
    calls = [{"turn": 1, "stop_reason": "tool_use", "cost_exact": cost_exact}]
    for _ in range(midrun_refusals):
        calls.append({"turn": 2, "stop_reason": "refusal", "cost_exact": cost_exact})
    if status == "brain_refusal":
        calls = [{"turn": 1, "stop_reason": "refusal", "cost_exact": cost_exact}]
    meta = {
        "run_id": run_id, "status": status, "seed": seed, "cost_exact": cost_exact,
        "harness_commit": "SYNTHETIC0000",
        "verdict": ({"verdict": "diff", "hypothesis": "SYNTHETIC - not data",
                     "confidence": 50} if has_verdict else None),
        "brain": {"model": brain, "turns_used": len(calls), "n_calls": len(calls),
                  "cost_usd": brain_usd, "cost_exact": cost_exact,
                  "n_unpriced_calls": 0 if cost_exact else 1, "calls": calls},
        "cost": {"brain_usd": brain_usd, "targets_usd": 0.0,
                 "total_usd": brain_usd, "cost_exact": cost_exact},
    }
    d = RUNS / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "run_meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                     encoding="utf-8")


def build_fixture() -> dict:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    RUNS.mkdir(parents=True, exist_ok=True)
    p1, p2 = [], []

    def add(run_id: str, rung: str, condition: str, *, status: str, seed: int,
            grade: str | None, verdict_type: str | None, usd: float | None,
            cost_exact: bool = True, midrun: int = 0, judge: str | None = None,
            brain: str = "claude-opus-5") -> None:
        refused = status == "brain_refusal"
        write_run(run_id, status=status, seed=seed, has_verdict=not refused,
                  brain_usd=usd, cost_exact=cost_exact, midrun_refusals=midrun,
                  brain=brain)
        p1.append({"run_id": run_id, "sealed_candidate_id": FAKE_MAP[rung],
                   "outcome": ("refusal_no_verdict" if refused else "verdict_bearing"),
                   "verdict_type": None if refused else verdict_type,
                   "top_hypothesis_verbatim": "SYNTHETIC - not data"})
        if grade is not None:
            p2.append({"run_id": run_id, "rung": rung, "condition": condition,
                       "human_grade": grade,
                       "judge_grade": judge if judge is not None else grade,
                       "human_reason": "SYNTHETIC - not data",
                       "adjudicated_grade": None, "adjudication_reason": None,
                       "l2_length_side_channel_cited": (rung == "L2" or None),
                       "decomposition": (None if rung == "L0" else
                                         {"coverage": True, "exposure": True,
                                          "attribution": grade})})

    # ---- v0_opus: L0 x 20 (Amendment 7), L1-L3 x 5, exploratory L4v3 x 5 ----
    for s in range(20):
        rid = f"v0_cand_SYNTHa_s{s}"
        if s in (3, 14):                       # two terminal refusals on the null
            add(rid, "L0", "v0_opus", status="brain_refusal", seed=s, grade=None,
                verdict_type=None, usd=0.05)
        elif s in (1, 11):                     # two frozen-rule false positives
            add(rid, "L0", "v0_opus", status="completed", seed=s, grade="FP",
                verdict_type="diff", usd=0.30)
        elif s == 7:                           # a `diff` verdict that is NOT an FP
            add(rid, "L0", "v0_opus", status="completed", seed=s, grade="CR",
                verdict_type="diff", usd=0.30, judge="FP")
        else:
            add(rid, "L0", "v0_opus", status="completed", seed=s, grade="CR",
                verdict_type="no_meaningful_diff", usd=0.30,
                midrun=1 if s == 2 else 0)
    for rung, grades in (("L1", ["FULL"] * 4 + [None]),
                         ("L2", ["FULL", "FULL", "PARTIAL", "PARTIAL", "MISS"]),
                         ("L3", ["PARTIAL", "PARTIAL", "MISS", "MISS", "MISS"]),
                         ("L4v3", ["MISS", "MISS", "MISS", "PARTIAL", "MISS"])):
        for s, g in enumerate(grades):
            rid = f"v0_cand_{FAKE_MAP[rung][5:]}_s{s}".replace("cand_", "")
            rid = f"v0_{FAKE_MAP[rung]}_s{s}"
            if g is None:                      # the fifth L1 seed refused
                add(rid, rung, "v0_opus", status="brain_refusal", seed=s, grade=None,
                    verdict_type=None, usd=0.04)
            else:
                add(rid, rung, "v0_opus", status="completed_forced", seed=s, grade=g,
                    verdict_type="diff", usd=0.50)

    # ---- v1_opus: L0 x 10 (seeds 0-9), L1-L3 x 3 ----
    for s in range(10):
        add(f"v1_cand_SYNTHa_s{s}", "L0", "v1_opus", status="completed", seed=s,
            grade="FP" if s == 4 else "CR",
            verdict_type="diff" if s == 4 else "no_meaningful_diff", usd=0.40)
    for rung, grades in (("L1", ["FULL", "FULL", "FULL"]),
                         ("L2", ["FULL", "PARTIAL", "MISS"]),
                         ("L3", ["MISS", "MISS", "PARTIAL"])):
        for s, g in enumerate(grades):
            add(f"v1_{FAKE_MAP[rung]}_s{s}", rung, "v1_opus",
                status="completed_forced", seed=s, grade=g, verdict_type="diff",
                usd=0.60)

    # ---- battery: one pair-level decision per pair; one pair is UNPRICED ----
    for rung in ("L0", "L1", "L2", "L3", "L4v3"):
        g = {"L0": "CR", "L1": "FULL", "L2": "PARTIAL",
             "L3": "MISS", "L4v3": "MISS"}[rung]
        add(f"bat_{FAKE_MAP[rung]}", rung, "battery", status="completed", seed=0,
            grade=g, verdict_type="diff" if g != "CR" else "no_meaningful_diff",
            usd=None if rung == "L2" else 0.06, cost_exact=rung != "L2",
            brain="gpt-5.6-terra")

    # ---- introspection: zero FULL anywhere, to exercise `undefined` ----
    for rung in ("L0", "L1", "L2", "L3", "L4v3"):
        g = "CR" if rung == "L0" else "MISS"
        add(f"intro_{FAKE_MAP[rung]}", rung, "introspection", status="completed",
            seed=0, grade=g,
            verdict_type="no_meaningful_diff" if g == "CR" else "diff", usd=0.012,
            brain="gpt-5.6-terra")

    # ---- glm_v0: the exploratory second-brain arm, kept in its own block ----
    for s in range(3):
        add(f"glm_cand_SYNTHa_s{s}", "L0", "glm_v0",
            status="brain_refusal" if s == 0 else "completed", seed=s,
            grade=None if s == 0 else "CR",
            verdict_type=None if s == 0 else "no_meaningful_diff", usd=0.004,
            brain="glm-5.3-flash")
    for s in range(2):
        add(f"glm_{FAKE_MAP['L1']}_s{s}", "L1", "glm_v0", status="completed", seed=s,
            grade="PARTIAL", verdict_type="diff", usd=0.004, brain="glm-5.3-flash")

    P1.write_text("".join(json.dumps(r) + "\n" for r in p1), encoding="utf-8")
    P2.write_text("".join(json.dumps(r) + "\n" for r in p2), encoding="utf-8")
    MAP.write_text(json.dumps(
        {"_WARNING": "SYNTHETIC FAKE MAP - NOT THE SEALED MAP, NOT DATA",
         "map": FAKE_MAP}, indent=2) + "\n", encoding="utf-8")
    FLOOR.write_text(json.dumps({
        "baseline": "SYNTHETIC", "corpus": "synthetic", "n_texts": 3, "topk": 50,
        "threshold_free": True,
        "pairs": [{"pair": "base_vs_base", "n_tokens_scored": 10,
                   "mean_abs_logprob_delta": 0.0, "approx_sym_kl_topk": 0.0}]
        + [{"pair": f"base_vs_{c}", "n_tokens_scored": 10,
            "mean_abs_logprob_delta": 0.1, "approx_sym_kl_topk": 0.2}
           for c in FAKE_MAP.values()]}, indent=2) + "\n", encoding="utf-8")
    return {"n_p1": len(p1), "n_p2": len(p2)}


def run_join(outdir: Path, *, unsealed: bool, extra: list[str] | None = None):
    argv = ["--runs", str(RUNS / "*"),
            "--phase1", str(P1), "--phase2", str(P2), "--floor", str(FLOOR),
            "--outdir", str(outdir), "--now", NOW]
    if unsealed:
        argv += ["--unsealed-map", str(MAP)]
    return AJ.cli(argv + (extra or []))


# ------------------------------------------------------------------------- the test
def main() -> int:
    info = build_fixture()
    n_runs = len(list(RUNS.iterdir()))
    print(f"fixture: {n_runs} synthetic runs, {info['n_p1']} phase-1 rows, "
          f"{info['n_p2']} phase-2 rows\n")

    print("1. blind is the default and is genuinely blind")
    rc = run_join(OUT_BLIND, unsealed=False)
    check(rc == 0, "blind join exits 0")
    check(not (OUT_BLIND / "analysis_figure_input.json").exists(),
          "blind mode does NOT write analysis_figure_input.json")
    check((OUT_BLIND / "blind_outcomes.json").exists(),
          "blind mode writes blind_outcomes.json instead")
    inv = json.loads((OUT_BLIND / "run_inventory.json").read_text(encoding="utf-8"))
    check(all(r["rung"] is None for r in inv["runs"]),
          f"every one of {len(inv['runs'])} runs has rung=null in blind mode")
    tb = (OUT_BLIND / "tables.md").read_text(encoding="utf-8")
    check("BLIND MODE" in tb and "rung-keyed tables are refused" in tb,
          "blind tables.md says plainly that rung-keyed tables are refused")
    check("Detection across designed rungs" not in tb
          and "The null (L0)" not in tb,
          "blind tables.md contains no detection table and no L0 table")
    check(not any(r in tb for r in ("| L1 |", "| L2 |", "| L3 |", "| L4v3 |")),
          "blind tables.md prints no rung anywhere")

    print("\n2. unsealed (fake map) produces the figure contract")
    rc = run_join(OUT_UNSEAL, unsealed=True)
    check(rc == 0, "unsealed join exits 0")
    fi = OUT_UNSEAL / "analysis_figure_input.json"
    check(fi.exists(), "analysis_figure_input.json written")
    doc = json.loads(fi.read_text(encoding="utf-8"))
    check(doc["schema"] == "analysis_figure_input/1", "schema is the figure contract")

    import make_figures as MF
    check(not MF.validate(doc),
          f"make_figures validates the join output clean: "
          f"{MF.validate(doc)[:2] if MF.validate(doc) else 'no problems'}")

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_HERE / "make_figures.py"), "--input", str(fi),
         "--outdir", str(OUT_UNSEAL), "--stem", "SYNTHETIC_joined_figure",
         "--watermark", "SYNTHETIC — NOT DATA",
         "--title", "SYNTHETIC JOIN FIXTURE - not a result"],
        capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print(proc.stdout, proc.stderr, sep="\n")
    check(proc.returncode == 0, "make_figures renders straight from the join output")
    png = OUT_UNSEAL / "SYNTHETIC_joined_figure.png"
    svg = OUT_UNSEAL / "SYNTHETIC_joined_figure.svg"
    check(png.exists() and png.stat().st_size > 50_000, "PNG written from join output")
    check(svg.exists() and svg.stat().st_size > 20_000, "SVG written from join output")

    print("\n3. the Amendment 6 / 7 denominators are the ones used")
    l1 = doc["detection"]["v0_opus"]["L1"]
    check(l1["full_all_attempts_PRIMARY"]["n"] == l1["n_planned_attempts"] == 5,
          "detection primary denominator is ALL planned attempts (5), not the 4 "
          "verdict-bearing")
    check(l1["full_all_attempts_PRIMARY"]["k"] == 4 and l1["n_terminal_refusal"] == 1,
          "a terminal refusal is carried as a non-detection, not dropped")
    check(l1["full_verdict_bearing"]["n"] == 4,
          "the verdict-bearing variant is emitted beside it as a diagnostic")
    n0 = doc["null"]["v0_opus"]
    check(n0["n_planned_attempts"] == 20 and n0["n_verdict_bearing"] == 18,
          "L0 has 20 planned attempts and 18 verdict-bearing")
    check(n0["fp_frozen_rule_verdict_bearing_PRIMARY"]["n"] == 18,
          "L0 FPR primary denominator is VERDICT-BEARING (18), not all attempts (20)")
    check(n0["fp_frozen_rule_all_attempts"]["n"] == 20,
          "the all-attempt burden is reported beside it")
    check(n0["fp_frozen_rule_verdict_bearing_PRIMARY"]["k"] == 2
          and n0["fp_strict_rule_verdict_bearing"]["k"] == 3,
          "strict rule counts every `diff` verdict (3) where the frozen rule counts 2")
    sub = doc["null_subset"]["v0_opus"]
    check(sub["n_planned_attempts"] == 10,
          "the Amendment 7 frozen subset (seeds 0-9) is emitted beside the n=20 primary")
    check("Amendment 7" in doc["null_subset_label"], "the subset is labelled as such")

    print("\n4. arms never mix")
    check("glm_v0" not in doc["conditions"],
          "the GLM arm is absent from the headline conditions")
    check("glm_v0" not in doc["detection"] and "glm_v0" not in doc["cost"],
          "the GLM arm is absent from headline detection and cost blocks")
    check(doc["exploratory_arms"]["arms"]["glm_v0"]["n_runs"] == 5,
          "the GLM arm is present in its own exploratory block (5 runs)")
    check("L4v3" in doc["exploratory_rungs"] and "L4v3" not in doc["designed_rungs"],
          "the exploratory rung is in exploratory_rungs, never in designed_rungs")
    check("L4v3" in doc["detection"]["v0_opus"],
          "the exploratory rung still has a cell, for the boxed inset")

    print("\n5. the cost rules hold")
    check(doc["cost"]["introspection"]["primary"].startswith("undefined (0 detections;"),
          "zero FULL detections gives `undefined (...)`, never infinity")
    check(doc["cost"]["battery"]["eligible_for_dollar_ranking"] is False
          and doc["cost"]["battery"]["primary"] is None,
          "an unpriced component removes the condition from the dollar ranking")
    check(doc["cost"]["v0_opus"]["eligible_for_dollar_ranking"] is True
          and isinstance(doc["cost"]["v0_opus"]["primary"], float),
          "a fully priced condition yields a numeric $/FULL detection")
    c0 = doc["cost"]["v0_opus"]
    check("refusals included" in c0["scope_note"]
          and "L0 plus the designed rungs" in c0["scope_note"],
          "the cost block states its rung scope and that refused attempts' spend is in "
          "the numerator, rather than leaving either implicit")
    check(c0["spend_field"] == "total_usd",
          "the DEFAULT numerator is `total_usd` (complete recorded spend), not brain "
          "spend")
    check("HEADLINE" in c0["scope_note"] and "Amendment 4 item 2" in c0["scope_note"],
          "the scope note names the headline-pairs-only rule and its authority")
    check("variant_brain_usd_only" in c0
          and c0["variant_brain_usd_only"]["diagnostic_only"].startswith("brain spend"),
          "`brain_usd` is emitted beside the primary as a LABELLED diagnostic")
    check(c0["variant_including_exploratory_rungs"]["diagnostic_only"]
          .endswith("(Amendment 4 item 2)"),
          "the including-exploratory variant is labelled as a diagnostic, not a headline")
    check(c0["spend_field_caveat"].startswith("`total_usd` equals `brain_usd`"),
          "the caveat states plainly that the two spend fields agree in this fixture")
    check("spend_composition" in c0 and set(c0["spend_composition"]) ==
          {"brain_usd", "targets_usd", "pod_usd", "total_usd"},
          "the spend composition is emitted, so nobody has to guess what total contains")

    print("\n6. mid-run refusals (TODO T10) and agreement (Addendum C)")
    check(doc["refusal"]["v0_opus"]
          ["n_midrun_refusal_events_in_verdict_bearing_runs"] == 1,
          "a refusal stop_reason inside a run that still submitted a verdict is counted")
    ag = json.loads((OUT_UNSEAL / "agreement.json").read_text(encoding="utf-8"))
    check(ag["n_runs_with_both_grades"] > 0 and ag["null_FP_CR"]["n"] > 0,
          "agreement is computed over both label sets once judge grades exist")
    check(ag["null_FP_CR"]["confusion_matrix_human_rows_judge_cols"]["CR"]["FP"] == 1,
          "the one planted human/judge disagreement lands in the confusion matrix")
    tabs = (OUT_UNSEAL / "tables.md").read_text(encoding="utf-8")
    for needle in ("FULL among **all planned seeded attempts**",
                   "VERDICT-BEARING", "Amendment 7", "Wilson",
                   "cannot** incur a brain-side refusal"):
        check(needle in tabs, f"tables.md names its denominator/rule: {needle!r}")

    print("\n7. the join fails closed")
    bad = ROOT / "bad"
    check(run_join(bad, unsealed=True,
                   extra=["--phase2", str(_REPO / "results"
                                          / "phase2_grades.EXAMPLE.jsonl")]) == 3,
          "EXAMPLE grade rows are rejected outright")
    short = ROOT / "SYNTHETIC_incomplete_map.json"
    short.write_text(json.dumps({"map": {"L0": "cand_SYNTHa"}}), encoding="utf-8")
    check(AJ.cli(["--runs", str(RUNS / "*"), "--phase1", str(P1), "--phase2", str(P2),
                  "--floor", str(FLOOR), "--outdir", str(bad), "--now", NOW,
                  "--unsealed-map", str(short)]) == 3,
          "a map that does not cover every sealed candidate is rejected")
    # appended, not edited in place: these files are append-only and the LAST row for a
    # run_id wins, so a doctored row must go at the end to actually take effect
    for label, badrow in (
            ("a grade outside the frozen vocabulary",
             {"run_id": f"v0_{FAKE_MAP['L1']}_s0", "human_grade": "EXCELLENT"}),
            ("an L0-only grade on a designed rung",
             {"run_id": f"v0_{FAKE_MAP['L2']}_s0", "human_grade": "FP"}),
            ("a detection grade on the null rung",
             {"run_id": "v0_cand_SYNTHa_s0", "human_grade": "FULL"}),
            ("a grade on a run that terminated in refusal",
             {"run_id": "v0_cand_SYNTHa_s3", "human_grade": "CR"}),
            ("a phase-2 row for a run that does not exist",
             {"run_id": "v0_cand_NOSUCH_s0", "human_grade": "MISS"})):
        tmp = ROOT / "SYNTHETIC_bad_phase2.jsonl"
        tmp.write_text(P2.read_text(encoding="utf-8")
                       + json.dumps(badrow) + "\n", encoding="utf-8")
        check(run_join(bad, unsealed=True, extra=["--phase2", str(tmp)]) == 3,
              f"rejected: {label}")

    print("\n8. deterministic")
    a = ROOT / "det_a"
    b = ROOT / "det_b"
    run_join(a, unsealed=True)
    run_join(b, unsealed=True)
    same = all((a / n).read_bytes() == (b / n).read_bytes()
               for n in ("analysis_figure_input.json", "tables.md",
                         "run_inventory.json", "agreement.json"))
    check(same, "two runs with a fixed --now are byte-identical")

    print("\n9. portability")
    older = _oldest_interpreter()
    if older is None:
        print("  skip Python 3.11 not available - verify before shipping")
    else:
        r = subprocess.run(
            [older, "-c",
             "import py_compile;"
             "py_compile.compile(r'scripts/analysis_join.py', doraise=True);"
             "py_compile.compile(r'scripts/test_analysis_join.py', doraise=True)"],
            cwd=_REPO, capture_output=True, text=True)
        check(r.returncode == 0,
              "both scripts compile on Python 3.11 (no 3.12-only syntax)"
              + ("" if r.returncode == 0 else ": " + r.stderr[-300:]))

    # transient fixtures used only to prove the failure paths; the durable artifacts
    # (the fixture runs, out_blind/, out_unsealed/) stay on disk as the record
    for junk in (ROOT / "det_a", ROOT / "det_b", ROOT / "bad"):
        shutil.rmtree(junk, ignore_errors=True)
    for junk in (ROOT / "SYNTHETIC_bad_phase2.jsonl",
                 ROOT / "SYNTHETIC_incomplete_map.json"):
        junk.unlink(missing_ok=True)

    print("\n10. --exclude-runs sensitivity pass")
    # No flag: nothing extra is produced and no section appears.
    tb_plain = (OUT_UNSEAL / "tables.md").read_text(encoding="utf-8")
    check("Sensitivity — validity-gate exclusions" not in tb_plain,
          "without the flag, tables.md has no sensitivity section")
    check(not (OUT_UNSEAL / "sensitivity_excluded_runs.json").exists(),
          "without the flag, no sensitivity JSON is written")

    drop = ["v0_cand_SYNTHa_s0", "v0_cand_SYNTHa_s2"]
    out_sens = ROOT / "out_sensitivity"
    rc = run_join(out_sens, unsealed=True, extra=["--exclude-runs"] + drop)
    check(rc == 0, "join with --exclude-runs exits 0")
    sp = out_sens / "sensitivity_excluded_runs.json"
    check(sp.exists(), "sensitivity_excluded_runs.json written")
    sens = json.loads(sp.read_text(encoding="utf-8"))
    check(sens["n_runs_sensitivity"] == sens["n_runs_primary"] - 2,
          f"sensitivity drops exactly 2 runs "
          f"({sens['n_runs_primary']} -> {sens['n_runs_sensitivity']})")

    # The PRIMARY numbers must not move: exclusion is a parallel view, not a filter.
    doc_p = json.loads((OUT_UNSEAL / "analysis_figure_input.json")
                       .read_text(encoding="utf-8"))
    doc_s = json.loads((out_sens / "analysis_figure_input.json")
                       .read_text(encoding="utf-8"))
    check(doc_p["null"]["v0_opus"]["n_planned_attempts"]
          == doc_s["null"]["v0_opus"]["n_planned_attempts"] == 20,
          "primary L0 attempts stay 20 even when --exclude-runs is passed")
    check(sens["figure_input"]["null"]["v0_opus"]["n_planned_attempts"] == 18,
          "sensitivity L0 attempts drop to 18")

    tb_s = (out_sens / "tables.md").read_text(encoding="utf-8")
    check("Sensitivity — validity-gate exclusions" in tb_s,
          "tables.md prints the sensitivity section when the flag is used")
    check(all(d in tb_s for d in drop),
          "tables.md names every excluded run")
    check("include every run" in tb_s,
          "tables.md states that the primary numbers include every run")

    # A typo must fail loudly rather than silently excluding nothing.
    rc_bad = run_join(ROOT / "out_bad", unsealed=True,
                      extra=["--exclude-runs", "v0_cand_DOES_NOT_EXIST_s0"])
    check(rc_bad == 4, "an unknown run_id in --exclude-runs is refused (rc=4)")

    print("\n11. condition derives from results ROOT + prefix, not prefix alone")
    # The GLM arm ran --agent-version v0, so its run ids are byte-identical to the Opus
    # v0 arm's and differ only by results root. Keying on run_id alone silently dropped
    # all 30 of them.
    glm_root = ROOT / "runs_glm"
    glm_root.mkdir(parents=True, exist_ok=True)
    # An id that ALREADY exists under runs/ as v0_opus, on a (candidate, seed) trial the
    # fixture's glm_cand_ rows do not use - so the only thing under test is the clash.
    clash = "v0_cand_SYNTHa_s19"
    src = json.loads((RUNS / clash / "run_meta.json").read_text(encoding="utf-8"))
    (glm_root / clash).mkdir(parents=True, exist_ok=True)
    (glm_root / clash / "run_meta.json").write_text(
        json.dumps(src), encoding="utf-8")

    n_fixture = len(list(RUNS.iterdir()))
    runs_glm = AJ.load_runs([str(RUNS / "*"), str(glm_root / "*")])
    conds = collections.Counter(r["condition"] for r in runs_glm)
    check(len(runs_glm) == n_fixture + 1,
          f"the basename clash across roots is KEPT, not silently de-duplicated "
          f"({n_fixture} + 1 vs {len(runs_glm)})")
    g = [r for r in runs_glm if r["results_root"] == "runs_glm"]
    check(len(g) == 1 and g[0]["condition"] == "glm_v0",
          "a run under runs_glm/ is condition glm_v0 despite its v0_ run id")
    check(any(r["run_id"] == clash and r["condition"] == "v0_opus" for r in runs_glm),
          "the identically-named run under runs/ is still v0_opus")
    check(g[0]["run_dir"].endswith(clash) and g[0]["results_root"] == "runs_glm",
          "the row records run_dir and results_root so the mapping is auditable")
    check(conds.get("glm_v0", 0) == 5 + 1,
          f"glm_v0 now holds the fixture's 5 glm_cand_ rows plus this one "
          f"(got {conds.get('glm_v0')})")

    print("\n12. a duplicate WITHIN a condition fails loudly")
    # Two DIFFERENT directories in the SAME root carrying the same run_id: the same
    # trial counted twice, which moves every rate.
    second = glm_root / (clash + "_copy")
    second.mkdir(parents=True, exist_ok=True)
    (second / "run_meta.json").write_text(json.dumps(src), encoding="utf-8")
    raised = ""
    try:
        AJ.load_runs([str(glm_root / "*")])
    except AJ.JoinError as e:
        raised = str(e)
    check("duplicate runs within a condition" in raised,
          "two runs with the same (condition, run_id) raise JoinError")
    check(clash in raised and "runs_glm" in raised,
          "the error names the colliding run and both paths")
    check(raised.count("runs_glm/") >= 2, "both colliding paths are printed")
    shutil.rmtree(second, ignore_errors=True)

    # And the clean case still loads once the duplicate is gone.
    ok_again = AJ.load_runs([str(glm_root / "*")])
    check(len(ok_again) == 1, "removing the duplicate makes the load succeed again")
    shutil.rmtree(glm_root, ignore_errors=True)

    print("\n13. blind mode still emits no rung after the loader change")
    rc = run_join(OUT_BLIND, unsealed=False)
    inv_b = json.loads((OUT_BLIND / "run_inventory.json").read_text(encoding="utf-8"))
    check(rc == 0, "blind join still exits 0")
    check(all(r["rung"] is None for r in inv_b["runs"]),
          "every rung is still null in blind mode")
    check(all(r.get("results_root") for r in inv_b["runs"]),
          "every inventory row records its results_root")

    print(f"\n{'=' * 62}")
    if _fails:
        print(f"FAILED {len(_fails)}/{_checks} checks:")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print(f"ALL {_checks} CHECKS PASS")
    print("Synthetic only. Nothing under results/analysis/synthetic/ is a result,")
    print("and the map it used is a fake fixture, not data/sealed/.")
    return 0


def _oldest_interpreter() -> str | None:
    for cand in (["py", "-3.11"], ["python3.11"]):
        try:
            r = subprocess.run(cand + ["-c", "import sys;print(sys.executable)"],
                               capture_output=True, text=True, timeout=25)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
    return None


if __name__ == "__main__":
    sys.exit(main())
