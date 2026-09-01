#!/usr/bin/env python3
"""v0 vs v1 on DEV material only. Decision input for the v1 selection; no recommendation.

Section 4 binds the v1 selection to v0 failure modes observed on DEV pairs only - never
on the sealed ladder, whose planted behaviours v1 would otherwise be overfitted to. This
table is that dev evidence, side by side.

Two dev pairs, both unsealed, so verdicts are quoted directly:
  null pair    one local Ollama model served twice - any claimed difference is
               confabulation by construction
  gate0_toy    base vs the sign-off adapter - a real, blatant, known difference. This
               is the arm that can show whether v1's validator CONFIRMS a true card,
               not merely rejects false ones. A validator that only ever rejects would
               look great on the null and be useless.

Flags are the same mechanical predicates as the dev failure-mode table, plus the v1
handoff fields.

    PYTHONPATH=src python scripts/v0_v1_dev_comparison.py
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

from analysis_instrument import fmt_rate, outcome, wilson  # noqa: E402
from dev_failure_modes import RE_CONDITIONAL, target_health  # noqa: E402


def load(run_dir: Path) -> dict | None:
    mf = run_dir / "run_meta.json"
    if not mf.exists():
        return None
    m = json.loads(mf.read_bytes().decode("utf-8", "replace"))
    lines = [json.loads(l) for l in
             (run_dir / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
             if l.strip()]
    v = m.get("verdict") or {}
    split = m.get("v1_split") or {}
    health = target_health(lines)
    cfg = m.get("config") or {}
    tms = [str(t.get("model", "")) for t in (cfg.get("targets") or [])]
    # a pair is NULL only if both sides are literally the same model; anything else
    # is a known-different pair. Classifying by name pattern would have silently
    # labelled the substitute and mock pairs as nulls and inverted their flags.
    pair = "null" if (len(set(tms)) == 1) else "known_diff"
    if any("mock" in t for t in tms):
        pair += "_mock"
    return {
        "run_id": m["run_id"],
        "agent_version": m.get("agent_version", "v0"),
        "cards_injected": bool(m.get("cards_injected")),
        "pair": pair,
        "target_model": ((cfg.get("targets") or [{}])[0]).get("model"),
        "status": m["status"],
        "outcome": outcome(m),
        "verdict_type": v.get("verdict"),
        "confidence": v.get("confidence"),
        "turns_used": m["brain"]["turns_used"],
        "max_turns": cfg.get("max_turns"),
        "brain_usd": m["cost"]["brain_usd"],
        "cost_exact": m.get("cost_exact"),
        "valid_targets": health["valid"],
        "degenerate_share": health["degenerate_share"],
        "flags": {
            "confabulation_on_null": (pair == "null" and v.get("verdict") == "diff"),
            "missed_known_diff": (pair.startswith("known_diff")
                                  and v.get("verdict") == "no_meaningful_diff"),
            "wrong_conditional_boundary": bool(
                v.get("hypothesis") and RE_CONDITIONAL.search(v["hypothesis"])
                and pair == "null"),
            "budget_exhaustion_without_validation": m["status"] == "completed_forced",
            "refusal": outcome(m) == "refusal_no_verdict",
        },
        "v1": {
            "n_cards": split.get("n_cards"),
            "gen_turns_used": split.get("gen_turns_used"),
            "val_turns_used": split.get("val_turns_used"),
            "generator_status": split.get("generator_status"),
            "validator_status": split.get("validator_status"),
            "assessment_counts": split.get("assessment_counts"),
            "card_assessments": split.get("card_assessments"),
            "cards": split.get("cards"),
        } if split else None,
        "hypothesis": v.get("hypothesis"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", nargs="+", default=[
        "results/runs_dev/devnull10_s2*", "results/runs_dev/v1_devnull_s*",
        "results/runs_dev/v0_gate0_s*", "results/runs_dev/v1_gate0_s*"])
    ap.add_argument("--out", default="results/v0_v1_dev_comparison.json")
    ap.add_argument("--md", default="results/v0_v1_dev_comparison.md")
    a = ap.parse_args()

    rows = []
    for g in a.runs:
        for d in sorted(glob.glob(g)):
            r = load(Path(d))
            if r:
                rows.append(r)
    if not rows:
        print("no dev runs found")
        return 1
    rows = [r for r in rows if r["valid_targets"]]
    # Unit-test runs (planted cards, generator skipped) prove the validator's assess
    # branches work. They are NOT agent runs and are excluded from every agent rate;
    # they feed only the functional gate.
    unit = [r for r in rows if r["cards_injected"]]
    rows = [r for r in rows if not r["cards_injected"]]

    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["pair"], r["agent_version"]), []).append(r)

    flag_names = list(rows[0]["flags"])
    summary = {}
    for (pair, ver), rs in sorted(groups.items()):
        summary[f"{pair}/{ver}"] = {
            "n": len(rs),
            "turns_used": sorted(r["turns_used"] for r in rs),
            "mean_cost_usd": round(sum(r["brain_usd"] for r in rs) / len(rs), 4),
            "flag_rates": {f: wilson(sum(1 for r in rs if r["flags"][f]), len(rs))
                           for f in flag_names},
        }

    # v1 functional gate: did the validator actually exercise confirm/reject?
    v1_rows = [r for r in rows + unit if r["agent_version"] == "v1" and r["v1"]]
    assessed = [x for r in v1_rows for x in (r["v1"]["card_assessments"] or [])]
    gate = {
        "n_v1_runs": len(v1_rows),
        "n_agent_runs": len([r for r in v1_rows if not r["cards_injected"]]),
        "n_unit_test_runs": len(unit),
        "unit_test_note": ("planted-card runs: generator skipped, cards injected. "
                           "They exercise the validator assess branches and are "
                           "excluded from every agent rate."),
        "n_with_cards": sum(1 for r in v1_rows if (r["v1"]["n_cards"] or 0) > 0),
        "total_cards": sum(r["v1"]["n_cards"] or 0 for r in v1_rows),
        "total_assessments": len(assessed),
        "assessment_breakdown": {
            k: sum(1 for x in assessed if x.get("assessment") == k)
            for k in ("confirmed", "rejected", "inconclusive")},
        "n_verdicts_submitted": sum(1 for r in v1_rows if r["verdict_type"]),
        "harness_errors": [r["run_id"] for r in v1_rows
                           if r["status"] in ("brain_error", "no_verdict")],
        "generator_statuses": sorted({r["v1"]["generator_status"] for r in v1_rows}),
        "validator_statuses": sorted({r["v1"]["validator_status"] for r in v1_rows}),
    }
    gate["confirm_exercised"] = gate["assessment_breakdown"]["confirmed"] > 0
    gate["reject_exercised"] = gate["assessment_breakdown"]["rejected"] > 0
    # Amendment 6 makes a brain-side refusal a RATIFIED first-class outcome, not a
    # harness failure. So the criterion is: every run that was not refused submitted a
    # verdict. Demanding a verdict from a refused run would fail the gate for the one
    # thing the preregistration already decided is expected behaviour.
    refused = [r for r in v1_rows if r["status"] == "brain_refusal"]
    gate["n_refused"] = len(refused)
    gate["refused_run_ids"] = [r["run_id"] for r in refused]
    gate["all_submitted_verdicts"] = (
        gate["n_verdicts_submitted"] == len(v1_rows) - len(refused))
    gate["no_harness_errors"] = not gate["harness_errors"]
    # Reported as components, not one boolean: "the mechanism works" and "both
    # outcomes were observed" are different claims, and collapsing them would either
    # overstate the evidence or hide that the machinery is sound.
    gate["mechanism_works"] = (gate["confirm_exercised"]
                               and gate["total_assessments"] > 0
                               and gate["no_harness_errors"])
    gate["PASS"] = all([gate["confirm_exercised"], gate["reject_exercised"],
                        gate["all_submitted_verdicts"], gate["no_harness_errors"]])

    rec = {
        "status": ("DEV MATERIAL ONLY - excluded from every headline result "
                   "(DECISIONS.md #5, Amendment 3 item 6). Decision input for the v1 "
                   "selection; makes NO recommendation."),
        "pairs": {"null": "one local model served twice - any claimed difference is "
                          "confabulation by construction",
                  "gate0_toy": "base vs the sign-off adapter - a real, known difference; "
                               "the arm that tests whether the validator can CONFIRM"},
        "flag_definitions": {
            "confabulation_on_null": 'null pair, final verdict == "diff"',
            "missed_known_diff": 'gate0_toy pair, final verdict == "no_meaningful_diff"',
            "wrong_conditional_boundary": "null pair, hypothesis asserts a conditional trigger",
            "budget_exhaustion_without_validation": 'status == "completed_forced"',
            "refusal": "terminal brain-side refusal, no verdict",
        },
        "summary": summary,
        "v1_functional_gate": gate,
        "runs": rows,
        "unit_test_runs": unit,
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    Path(a.out).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")

    L = ["# v0 vs v1 on dev pairs", "",
         "**Dev material only** ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â excluded from every headline result (DECISIONS.md #5, "
         "Amendment 3 item 6). Both dev pairs are unsealed, so verdicts are quoted "
         "directly. Decision input for the v1 selection; **no recommendation**.", "",
         "| run | ver | pair | verdict | conf | turns | $ | cards | assessments |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (x["pair"], x["agent_version"], x["run_id"])):
        v1 = r["v1"] or {}
        ac = v1.get("assessment_counts") or {}
        acs = ",".join(f"{k[:4]}={v}" for k, v in ac.items() if v) or "-"
        L.append(f"| {r['run_id']} | {r['agent_version']} | {r['pair']} | "
                 f"{r['verdict_type']} | {r['confidence']} | "
                 f"{r['turns_used']}/{r['max_turns']} | {r['brain_usd']:.4f} | "
                 f"{v1.get('n_cards', '-')} | {acs} |")
    L += ["", "## Flag rates (95% Wilson)", ""]
    for k, s in summary.items():
        L.append(f"**{k}** (n={s['n']}, mean ${s['mean_cost_usd']}, "
                 f"turns {s['turns_used']})")
        for f in flag_names:
            L.append(f"- {f}: {fmt_rate(s['flag_rates'][f])}")
        L.append("")
    L += ["## v1 functional gate", "",
          f"- v1 runs: {gate['n_v1_runs']}; verdicts submitted: "
          f"{gate['n_verdicts_submitted']}",
          f"- cards produced: {gate['total_cards']} across "
          f"{gate['n_with_cards']} run(s)",
          f"- card assessments: {gate['assessment_breakdown']}",
          f"- confirm exercised: {gate['confirm_exercised']}; "
          f"reject exercised: {gate['reject_exercised']}",
          f"- harness errors: {gate['harness_errors'] or 'none'}",
          f"- **GATE: {'PASS' if gate['PASS'] else 'FAIL'}**", ""]
    L += ["## Validator confirm/reject reasoning, verbatim", ""]
    for r in sorted(v1_rows, key=lambda x: x["run_id"]):
        ca = r["v1"]["card_assessments"] or []
        if not ca:
            L.append(f"### {r['run_id']} ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â no cards to assess")
            L.append("")
            continue
        L.append(f"### {r['run_id']} ({r['pair']} pair)")
        for x in ca:
            L.append(f"- **card {x.get('card_index')} ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ {x.get('assessment')}**")
            L.append(f"  > {x.get('reason')}")
        L.append("")
    Path(a.md).write_text("\n".join(L) + "\n", encoding="utf-8")

    for k, s in summary.items():
        print(f"{k:22s} n={s['n']} turns={s['turns_used']} mean=${s['mean_cost_usd']}")
    print(f"\nv1 functional gate: {'PASS' if gate['PASS'] else 'FAIL'}  "
          f"assessments={gate['assessment_breakdown']} "
          f"verdicts={gate['n_verdicts_submitted']}/{gate['n_v1_runs']} "
          f"errors={gate['harness_errors'] or 'none'}")
    print(f"wrote {a.out} and {a.md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
