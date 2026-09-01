#!/usr/bin/env python3
"""Screen every run's TARGET replies for degenerate output. Mechanical, blind-safe.

Motivation: a local dev backend once emitted a constant string for a whole batch, the
agent correctly reported "no difference", and that would have scored as a clean
correct rejection had a health check not caught it. That failure mode is invisible in
aggregate outcome flags. The sealed campaign runs against the pod's vLLM rather than
that box, and campaign_serving_smoke checks generation and logprobs per model, but
nothing screened the campaign TRANSCRIPTS. This does.

BLIND-SAFE BY CONSTRUCTION: this script reads only the `text` field of
`target_response` events, and emits only counts. It never reads, prints or stores a
verdict, a hypothesis, a prompt or any reply content - so it can be run and its output
committed before unsealing without exposing anything a grader must not see.

Same rule as the dev screen: a run is flagged if more than 10% of its target replies
are degenerate (empty, or <=2 distinct characters).

    PYTHONPATH=src python scripts/screen_target_health.py
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

from dev_failure_modes import MAX_DEGENERATE_SHARE, is_degenerate  # noqa: E402


def screen(run_dir: Path) -> dict | None:
    tp = run_dir / "transcript.jsonl"
    if not tp.exists():
        return None
    n = deg = err = empty = 0
    hit_lengths: list[int] = []
    for line in tp.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("type") != "target_response":
            continue
        n += 1
        t = r.get("text") or ""
        if r.get("error"):
            err += 1
        if not t.strip():
            empty += 1
        if is_degenerate(t):
            deg += 1
            hit_lengths.append(len(t.strip()))
    share = (deg / n) if n else 1.0
    # Length of each hit, so the two regimes stay distinguishable. The dev-backend
    # failure was long constant strings (31 chars) across ~all replies; an ultra-short
    # but legitimate answer ("4", "42") also has <=2 distinct characters and is a known
    # false positive of this rule. Lengths are counts, not content - blind-safe.
    return {"run_id": run_dir.name, "n_target_responses": n, "n_degenerate": deg,
            "n_empty": empty, "n_errors": err,
            "degenerate_hit_lengths": sorted(hit_lengths),
            "max_hit_length": max(hit_lengths) if hit_lengths else 0,
            "degenerate_share": round(share, 4),
            "flagged": (n == 0) or (share > MAX_DEGENERATE_SHARE)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--globs", nargs="+", default=[
        "results/runs/v0_cand_*", "results/runs/bat_cand_*", "results/runs/intro_cand_*"])
    ap.add_argument("--out", default="results/target_health_screen.json")
    a = ap.parse_args()

    groups: dict[str, list[dict]] = {}
    for g in a.globs:
        label = ("v0 campaign" if "v0_" in g else
                 "baseline 1 battery" if "bat_" in g else
                 "baseline 3 introspection" if "intro_" in g else g)
        rows = [r for r in (screen(Path(d)) for d in sorted(glob.glob(g))) if r]
        if rows:
            groups.setdefault(label, []).extend(rows)

    print(f"rule: flag a run if >{MAX_DEGENERATE_SHARE:.0%} of TARGET replies are "
          f"degenerate (empty or <=2 distinct characters)")
    print("output is counts only - no verdicts, hypotheses or transcript content\n")

    all_rows, flagged = [], []
    for label, rows in groups.items():
        n_tr = sum(r["n_target_responses"] for r in rows)
        n_deg = sum(r["n_degenerate"] for r in rows)
        n_err = sum(r["n_errors"] for r in rows)
        f = [r for r in rows if r["flagged"]]
        flagged += f
        all_rows += rows
        print(f"=== {label}: {len(rows)} runs ===")
        print(f"  {'run_id':<24} {'replies':>8} {'degen':>6} {'share':>7} {'errors':>7}  status")
        for r in rows:
            print(f"  {r['run_id']:<24} {r['n_target_responses']:>8} "
                  f"{r['n_degenerate']:>6} {r['degenerate_share']*100:>6.1f}% "
                  f"{r['n_errors']:>7}  {'FLAGGED' if r['flagged'] else 'ok'}")
        print(f"  group totals: {n_tr} target replies, {n_deg} degenerate "
              f"({100*n_deg/n_tr if n_tr else 0:.2f}%), {n_err} errors, "
              f"{len(f)} run(s) flagged\n")

    tot = sum(r["n_target_responses"] for r in all_rows)
    deg = sum(r["n_degenerate"] for r in all_rows)
    err = sum(r["n_errors"] for r in all_rows)
    rec = {
        "screen": "target_health/1",
        "rule": (f"flagged if >{MAX_DEGENERATE_SHARE:.0%} of target replies are "
                 f"degenerate (empty or <=2 distinct characters)"),
        "blind_safe": ("reads only target_response text; emits only counts. No "
                       "verdicts, hypotheses, prompts or reply content are read, "
                       "printed or stored, so this may be run and committed before "
                       "unsealing"),
        "n_runs_screened": len(all_rows),
        "n_target_replies": tot,
        "n_degenerate": deg,
        "n_empty": sum(r["n_empty"] for r in all_rows),
        "n_errors": err,
        "overall_degenerate_share": round(deg / tot, 6) if tot else None,
        "n_runs_flagged": len(flagged),
        "flagged_run_ids": [r["run_id"] for r in flagged],
        "validity_verdict": ("CLEAN - no run exceeds the degeneracy threshold"
                             if not flagged else
                             "VALIDITY ISSUE - flagged runs must be resolved before grading"),
        "hit_interpretation": {
            "max_hit_length_across_all_runs": max(
                [r["max_hit_length"] for r in all_rows] or [0]),
            "n_empty_replies": sum(r["n_empty"] for r in all_rows),
            "note": ("The rule flags any reply with <=2 distinct characters, so an "
                     "ultra-short but perfectly valid answer ('4', '42') is a known "
                     "false positive. The failure this screen exists to catch looked "
                     "completely different: long constant strings (31 characters) "
                     "across ~100% of a run's replies. Read max_hit_length together "
                     "with the share - short hits at a low rate are terse answers, "
                     "long hits at a high rate are a broken backend."),
        },
        "groups": {k: v for k, v in groups.items()},
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")

    print("=" * 68)
    print(f"TOTAL: {len(all_rows)} runs, {tot} target replies, {deg} degenerate "
          f"({100*deg/tot if tot else 0:.3f}%), {err} errors")
    if flagged:
        print(f"\n*** VALIDITY ISSUE: {len(flagged)} run(s) exceed the threshold ***")
        for r in flagged:
            print(f"    {r['run_id']}: {r['n_degenerate']}/{r['n_target_responses']} "
                  f"({r['degenerate_share']*100:.1f}%)")
        print("    Resolve before grading.")
    else:
        print("\nCLEAN - no run exceeds the degeneracy threshold.")
    mx = max([r["max_hit_length"] for r in all_rows] or [0])
    n_empty = sum(r["n_empty"] for r in all_rows)
    print(f"hits: {deg} reply(ies), longest {mx} chars, {n_empty} empty. "
          f"The rule also catches valid ultra-short answers; the failure it targets "
          f"was 31-char constant strings across ~100% of a run.")
    print(f"wrote {a.out}")
    return 0 if not flagged else 1


if __name__ == "__main__":
    sys.exit(main())
