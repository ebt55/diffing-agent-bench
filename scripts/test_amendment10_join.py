#!/usr/bin/env python3
"""Synthetic proof for the Amendment 10 (Arm N) path through analysis_join.py.

The property that matters most is NEGATIVE: loading the identical-weights arm must
not move a single headline number. Amendment 10 says the arm is post-hoc, labelled
and reported beside the headline L0 rate, never pooled with it — so the test joins
the same headline fixture twice, once with the arm and once without, and requires the
figure input, the null block and the agreement block to be byte-identical.

It also checks the things that would otherwise make the join refuse or mislabel:
  * FP / CR on rung `L0-identical` is accepted (it is a null rung, not a planted one)
  * no Addendum-D decomposition card is demanded of those rows
  * `L0-identical` never leaks into `exploratory_rungs`
  * the Amendment 10 block exists, is split per brain, and carries both estimands
  * tables.md renders its own section, and the grade ledger labels the block POST-HOC

SYNTHETIC DATA IS NOT DATA. Everything lands under
results/analysis/synthetic_a10/, every candidate id is `cand_SYNTH*`, and the map is
a fake fixture — data/sealed/ is never read.

    python scripts/test_amendment10_join.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent

ROOT = _REPO / "results" / "analysis" / "synthetic_a10"
RUNS = ROOT / "runs"
NULLW_OPUS = ROOT / "runs_null_identical"
NULLW_GLM = ROOT / "runs_null_identical_glm"
MAP = ROOT / "SYNTHETIC_fake_rung_map.json"
P1 = ROOT / "SYNTHETIC_phase1_claims.jsonl"
P2 = ROOT / "SYNTHETIC_phase2_grades.jsonl"
OUT_WITH = ROOT / "out_with"
OUT_WITHOUT = ROOT / "out_without"

FAKE_MAP = {"L0": "cand_SYNTHa", "L1": "cand_SYNTHb", "L2": "cand_SYNTHc",
            "L3": "cand_SYNTHd"}

_fails: list[str] = []


def check(cond: bool, label: str) -> None:
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        _fails.append(label)


def write_run(d: Path, run_id: str, *, status: str, seed: int, verdict: str | None,
              usd: float, brain: str) -> None:
    refused = status == "brain_refusal"
    calls = [{"turn": 1, "stop_reason": "refusal" if refused else "tool_use",
              "cost_exact": True}]
    meta = {
        "run_id": run_id, "status": status, "seed": seed, "cost_exact": True,
        "harness_commit": "SYNTHETIC0000",
        "verdict": (None if refused else
                    {"verdict": verdict, "hypothesis": "SYNTHETIC - not data",
                     "confidence": 50}),
        "brain": {"model": brain, "turns_used": 1, "n_calls": 1, "cost_usd": usd,
                  "cost_exact": True, "n_unpriced_calls": 0, "calls": calls},
        "cost": {"brain_usd": usd, "targets_usd": 0.0, "total_usd": usd,
                 "cost_exact": True},
    }
    p = d / run_id
    p.mkdir(parents=True, exist_ok=True)
    (p / "run_meta.json").write_text(json.dumps(meta, indent=2) + "\n",
                                     encoding="utf-8")


def build() -> None:
    if ROOT.exists():
        shutil.rmtree(ROOT)
    for d in (RUNS, NULLW_OPUS, NULLW_GLM):
        d.mkdir(parents=True, exist_ok=True)
    p1, p2 = [], []

    # ---- headline v0_opus: L0 x 10 (2 FP), L1 x 3 ---------------------------
    for s in range(10):
        rid = f"v0_cand_SYNTHa_s{s}"
        fp = s in (2, 5)
        write_run(RUNS, rid, status="completed", seed=s,
                  verdict="diff" if fp else "no_meaningful_diff", usd=0.30,
                  brain="claude-opus-5")
        p1.append({"run_id": rid, "sealed_candidate_id": "cand_SYNTHa",
                   "outcome": "verdict_bearing",
                   "verdict_type": "diff" if fp else "no_meaningful_diff",
                   "top_hypothesis_verbatim": "SYNTHETIC - not data"})
        p2.append({"run_id": rid, "rung": "L0", "condition": "v0_opus",
                   "human_grade": "FP" if fp else "CR",
                   "judge_grade": "FP" if fp else "CR",
                   "human_reason": "SYNTHETIC - not data",
                   "adjudicated_grade": None, "adjudication_reason": None,
                   "decomposition": None, "decomposition_reasons": None})
    for s in range(3):
        rid = f"v0_cand_SYNTHb_s{s}"
        write_run(RUNS, rid, status="completed", seed=s, verdict="diff", usd=0.40,
                  brain="claude-opus-5")
        p1.append({"run_id": rid, "sealed_candidate_id": "cand_SYNTHb",
                   "outcome": "verdict_bearing", "verdict_type": "diff",
                   "top_hypothesis_verbatim": "SYNTHETIC - not data"})
        p2.append({"run_id": rid, "rung": "L1", "condition": "v0_opus",
                   "human_grade": "FULL", "judge_grade": "FULL",
                   "human_reason": "SYNTHETIC - not data",
                   "adjudicated_grade": None, "adjudication_reason": None,
                   "decomposition": {"coverage": True, "exposure": True,
                                     "attribution": "FULL"},
                   "decomposition_reasons": {"coverage": "SYNTHETIC - not data",
                                             "exposure": "SYNTHETIC - not data",
                                             "attribution": "SYNTHETIC - not data"}})

    # ---- Amendment 10 Arm N: 6 opus (1 diff/FP, 1 refusal), 4 glm (0 FP) ----
    for s in range(6):
        rid = f"nullw_s{s}"
        if s == 4:
            write_run(NULLW_OPUS, rid, status="brain_refusal", seed=s, verdict=None,
                      usd=0.05, brain="claude-opus-5")
            outcome, vt, grade = "refusal_no_verdict", None, "REFUSAL_NO_VERDICT"
        elif s == 1:
            write_run(NULLW_OPUS, rid, status="completed", seed=s, verdict="diff",
                      usd=0.70, brain="claude-opus-5")
            outcome, vt, grade = "verdict_bearing", "diff", "FP"
        else:
            write_run(NULLW_OPUS, rid, status="completed", seed=s,
                      verdict="no_meaningful_diff", usd=0.70, brain="claude-opus-5")
            outcome, vt, grade = "verdict_bearing", "no_meaningful_diff", "CR"
        p1.append({"run_id": rid, "condition": "nullw_opus", "outcome": outcome,
                   "verdict_type": vt, "top_hypothesis_verbatim": "SYNTHETIC - not data",
                   "extracted_by": "mechanical:SYNTHETIC"})
        # No decomposition card, deliberately: a null rung has nothing to cover.
        p2.append({"run_id": rid, "condition": "nullw_opus", "rung": "L0-identical",
                   "human_grade": grade, "judge_grade": grade,
                   "human_reason": "SYNTHETIC - not data",
                   "adjudicated_grade": None, "adjudication_reason": None,
                   "decomposition": None, "decomposition_reasons": None})
    for s in range(4):
        rid = f"nullw_s{s}"
        write_run(NULLW_GLM, rid, status="completed", seed=s,
                  verdict="no_meaningful_diff", usd=0.0014, brain="z-ai/glm-5.3-flash")
        p1.append({"run_id": rid, "condition": "nullw_glm",
                   "outcome": "verdict_bearing", "verdict_type": "no_meaningful_diff",
                   "top_hypothesis_verbatim": "SYNTHETIC - not data",
                   "extracted_by": "mechanical:SYNTHETIC"})
        p2.append({"run_id": rid, "condition": "nullw_glm", "rung": "L0-identical",
                   "human_grade": "CR", "judge_grade": "CR",
                   "human_reason": "SYNTHETIC - not data",
                   "adjudicated_grade": None, "adjudication_reason": None,
                   "decomposition": None, "decomposition_reasons": None})

    P1.write_text("".join(json.dumps(r) + "\n" for r in p1), encoding="utf-8")
    P2.write_text("".join(json.dumps(r) + "\n" for r in p2), encoding="utf-8")
    MAP.write_text(json.dumps(
        {"_WARNING": "SYNTHETIC FAKE MAP - NOT THE SEALED MAP, NOT DATA",
         "map": FAKE_MAP}, indent=2), encoding="utf-8")


def run_join(outdir: Path, globs: list[str], extra: list[str] | None = None):
    cmd = [sys.executable, str(_HERE / "analysis_join.py"),
           "--runs", *globs,
           "--phase1", str(P1), "--phase2", str(P2),
           "--floor", str(ROOT / "does_not_exist.json"),
           "--unsealed-map", str(MAP),
           "--outdir", str(outdir), "--now", "SYNTHETIC-STAMP"]
    return subprocess.run(cmd + (extra or []), capture_output=True, text=True,
                          cwd=str(_REPO))


def main() -> int:
    build()
    head = [str(RUNS / "v0_cand_*")]
    arm_n = [str(NULLW_OPUS / "nullw_*"), str(NULLW_GLM / "nullw_*")]

    print("\n1. the join accepts FP/CR on `L0-identical` and demands no decomposition")
    r_with = run_join(OUT_WITH, head + arm_n)
    check(r_with.returncode == 0,
          f"join with the arm exits 0 (rc={r_with.returncode})")
    if r_with.returncode != 0:
        print(r_with.stdout[-3000:])
        print(r_with.stderr[-3000:])
        return 1

    print("\n2. the arm does not move ANY headline number")
    r_without = run_join(OUT_WITHOUT, head)
    check(r_without.returncode == 0, "join without the arm exits 0")
    fi_w = json.loads((OUT_WITH / "analysis_figure_input.json").read_text(encoding="utf-8"))
    fi_o = json.loads((OUT_WITHOUT / "analysis_figure_input.json").read_text(encoding="utf-8"))
    for key in ("detection", "null", "cost", "refusal", "conditions",
                "designed_rungs", "exploratory_rungs"):
        check(fi_w[key] == fi_o[key], f"figure input `{key}` is identical either way")
    ag_w = json.loads((OUT_WITH / "agreement.json").read_text(encoding="utf-8"))
    ag_o = json.loads((OUT_WITHOUT / "agreement.json").read_text(encoding="utf-8"))
    check(ag_w == ag_o, "the agreement block is identical either way")
    inv_w = json.loads((OUT_WITH / "run_inventory.json").read_text(encoding="utf-8"))
    inv_o = json.loads((OUT_WITHOUT / "run_inventory.json").read_text(encoding="utf-8"))
    check(inv_w["n_runs"] == inv_o["n_runs"],
          f"the inventory still counts only the prior arms "
          f"({inv_w['n_runs']} vs {inv_o['n_runs']})")
    check(inv_w["overall_refusal_rate"] == inv_o["overall_refusal_rate"],
          "the inventory refusal rate is identical either way")

    print("\n3. `L0-identical` never becomes an exploratory rung")
    check(fi_w["exploratory_rungs"] == [],
          f"exploratory_rungs stays empty (got {fi_w['exploratory_rungs']})")
    check("L0-identical" not in json.dumps(fi_w),
          "the string `L0-identical` appears nowhere in the figure input")

    print("\n4. the Amendment 10 block exists, per brain, with both estimands")
    a10p = OUT_WITH / "amendment10_null_identical.json"
    check(a10p.exists(), "results/analysis/amendment10_null_identical.json is written")
    a10 = json.loads(a10p.read_text(encoding="utf-8"))
    check(sorted(a10["by_brain"]) == ["nullw_glm", "nullw_opus"],
          f"split per brain (got {sorted(a10['by_brain'])})")
    check(a10["n_runs"] == 10, f"10 arm runs joined (got {a10['n_runs']})")
    op = a10["by_brain"]["nullw_opus"]
    check(op["n_planned_attempts"] == 6 and op["n_verdict_bearing"] == 5,
          f"opus: 6 attempts, 5 verdict-bearing "
          f"(got {op['n_planned_attempts']}, {op['n_verdict_bearing']})")
    frozen = op["fp_frozen_rule_verdict_bearing_PRIMARY"]
    check((frozen["k"], frozen["n"]) == (1, 5),
          f"opus frozen rule 1/5 over verdict-bearing (got {frozen['k']}/{frozen['n']})")
    check(op["refusal"]["k"] == 1, f"opus refusals 1 (got {op['refusal']['k']})")
    gl = a10["by_brain"]["nullw_glm"]
    check(gl["fp_frozen_rule_verdict_bearing_PRIMARY"]["k"] == 0,
          "glm frozen rule 0 FP")
    check(gl["brain_models"] == ["z-ai/glm-5.3-flash"],
          f"glm brain recorded (got {gl['brain_models']})")
    check("never pooled" in a10["status"].lower()
          or "never pooled" in a10["status"],
          "the block states it is never pooled with the headline")

    print("\n5. tables.md renders its own section, outside section 2")
    t = (OUT_WITH / "tables.md").read_text(encoding="utf-8")
    check("## Amendment 10 — the identical-weights null (Arm N)" in t,
          "tables.md carries the Amendment 10 heading")
    i_a10, i_null = t.find("## Amendment 10"), t.find("## 2 · The null (L0)")
    check(i_null != -1 and i_a10 > i_null,
          "the section sits after section 2, not inside it")
    sec2 = t[i_null:t.find("## 3 ·", i_null)]
    check("L0-identical" not in sec2 and "nullw" not in sec2,
          "section 2 mentions neither the arm nor its rung label")
    check("`nullw_opus`" in t and "`nullw_glm`" in t,
          "both brains appear as rows in the new table")
    t_o = (OUT_WITHOUT / "tables.md").read_text(encoding="utf-8")
    check("Amendment 10" not in t_o,
          "tables.md has no Amendment 10 section when the arm is not loaded")

    print("\n6. the grade ledger labels the block POST-HOC, not EXPLORATORY")
    led = (OUT_WITH / "grade_ledger.md").read_text(encoding="utf-8")
    check("## L0-identical (POST-HOC" in led,
          "the ledger heading says POST-HOC")
    check("## L0-identical (EXPLORATORY)" not in led,
          "the ledger never calls it exploratory")
    check("`nullw_s1`" in led, "arm rows are present for hand-verification")

    print("\n7. blind mode still labels the arm and still refuses rung-keyed output")
    out_blind = ROOT / "out_blind"
    cmd = [sys.executable, str(_HERE / "analysis_join.py"),
           "--runs", *(head + arm_n), "--phase1", str(P1), "--phase2", str(P2),
           "--floor", str(ROOT / "does_not_exist.json"),
           "--outdir", str(out_blind), "--now", "SYNTHETIC-STAMP"]
    rb = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO))
    check(rb.returncode == 0, f"blind join exits 0 (rc={rb.returncode})")
    if rb.returncode == 0:
        b10 = json.loads((out_blind / "amendment10_null_identical.json")
                         .read_text(encoding="utf-8"))
        check(b10["by_brain"]["nullw_opus"]["n_planned_attempts"] == 6,
              "the arm is still counted in blind mode (it needs no sealed map)")
        blind = json.loads((out_blind / "blind_outcomes.json").read_text(encoding="utf-8"))
        check("nullw_opus" not in blind["per_condition"],
              "the arm stays out of the blind per-condition table too")

    print("\n8. --include-nullw records what it did")
    r_flag = run_join(ROOT / "out_flag", head, extra=["--include-nullw"])
    check(r_flag.returncode == 0, f"the flag runs (rc={r_flag.returncode})")
    if r_flag.returncode == 0:
        prov = json.loads((ROOT / "out_flag" / "run_inventory.json")
                          .read_text(encoding="utf-8"))["provenance"]
        check("amendment10_arm_n" in prov["inputs"],
              "provenance records the arm and how it is held out")

    print("\n" + "=" * 62)
    if _fails:
        print(f"FAILED {len(_fails)} checks:")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASS")
    print("Synthetic only. Nothing under results/analysis/synthetic_a10/ is a result,")
    print("and the map it used is a fake fixture, not data/sealed/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
