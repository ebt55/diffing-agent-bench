"""Adjudicate a run flagged by the degeneracy validity gate.

screen_target_health.py deliberately over-triggers: its rule is "reply has <=2
distinct characters", which catches a genuinely broken backend AND a legitimate
one-word answer. Its own output says so. When it flags a run, the flag must be
resolved on evidence rather than by lowering the threshold, because the threshold is
what caught a real invalidation once already (a local Ollama backend emitting a
constant "0000..." string for a whole batch, which made the agent's correct "no
difference" verdict look like a clean correct-rejection when it had measured nothing).

The discriminator is SHARE first, then DISTINCTNESS - in that order. An earlier
version of this script used distinctness alone and was caught by a control run: a
healthy run holding two identical one-word numeric answers has distinct == 1 and was
branded a broken backend. Brevity is not the fault and neither is repetition; the
fault is a constant string DOMINATING a run.

  below threshold    -> nothing to adjudicate; the gate did not flag it
  broken backend     -> flagged AND ~1 distinct value, i.e. the same constant string
                        over and over, typically concentrated on one target
  real short answers -> flagged but several different values, spread across both
                        targets, with the rest of the run answering normally

This prints shapes only - counts, lengths, character classes, distinct-value counts.
No reply text is emitted, so it is safe to run against sealed-campaign outputs.

Run: python scripts/adjudicate_degeneracy.py --runs "results/runs_glm/v0_cand_m3iq_s4"
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
from pathlib import Path


def degenerate(s: str | None) -> bool:
    s = (s or "").strip()
    return (not s) or len(set(s)) <= 2


def adjudicate(run_dir: Path, threshold: float = 0.10) -> dict:
    tr = [json.loads(l) for l in
          (run_dir / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
          if l.strip()]
    reps = [r for r in tr if r.get("type") == "target_response"]
    deg_rows = [r for r in reps if degenerate(r.get("text"))]
    deg = [(r.get("text") or "").strip() for r in deg_rows]
    n, k = len(reps), len(deg)

    cls: collections.Counter = collections.Counter()
    for d in deg:
        if not d:
            cls["empty"] += 1
        elif d.isdigit():
            cls["digits_only"] += 1
        elif d.isalpha():
            cls["letters_only"] += 1
        else:
            cls["punct_or_mixed"] += 1

    by_target = collections.Counter(r.get("label") or r.get("target") or "?"
                                    for r in deg_rows)
    healthy = [len((r.get("text") or "").strip()) for r in reps
               if not degenerate(r.get("text"))]
    distinct = len(set(deg))

    one_sided = len(by_target) == 1 and k > 0
    share = (k / n) if n else 0.0

    # Distinctness alone is NOT the signature, and assuming it was is a mistake this
    # script made until a control run caught it: a perfectly healthy run that happens
    # to contain two identical one-word numeric answers has distinct == 1 and would
    # have been branded a broken backend. The fault requires BOTH a constant string
    # AND that string dominating the run - the original invalidation was ~100% of a
    # batch. So share gates the verdict first.
    #
    # Below the validity threshold there is nothing to adjudicate: the gate did not
    # flag the run and a handful of short answers is normal.
    if k == 0:
        verdict = "NO_DEGENERATE_REPLIES"
    elif share <= threshold:
        verdict = "NOT_FLAGGED"
    elif distinct <= 1:
        verdict = "BROKEN_BACKEND"
    elif len(healthy) > k:
        verdict = "REAL_SHORT_ANSWERS"
    else:
        verdict = "INCONCLUSIVE"

    return {
        "run_id": run_dir.name,
        "n_target_replies": n,
        "n_degenerate": k,
        "degenerate_share": round(k / n, 4) if n else None,
        "distinct_degenerate_values": distinct,
        "all_identical": distinct == 1 and k > 0,
        "degenerate_lengths": sorted(len(d) for d in deg),
        "character_classes": dict(cls),
        "degenerate_by_target": dict(by_target),
        "one_sided": one_sided,
        "healthy_replies": len(healthy),
        "healthy_len_min": min(healthy) if healthy else None,
        "healthy_len_median": sorted(healthy)[len(healthy) // 2] if healthy else None,
        "healthy_len_max": max(healthy) if healthy else None,
        "validity_threshold": threshold,
        "adjudication": verdict,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--out", default="results/degeneracy_adjudication.json")
    ap.add_argument("--threshold", type=float, default=0.10,
                    help="the validity gate share; matches MAX_DEGENERATE_SHARE")
    a = ap.parse_args()

    rows = []
    for g in a.runs:
        for d in sorted(glob.glob(g)):
            p = Path(d)
            if (p / "transcript.jsonl").exists():
                rows.append(adjudicate(p, a.threshold))

    for r in rows:
        print(f"=== {r['run_id']} ===")
        print(f"  degenerate      : {r['n_degenerate']}/{r['n_target_replies']} "
              f"({(r['degenerate_share'] or 0) * 100:.1f}%)")
        print(f"  distinct values : {r['distinct_degenerate_values']} "
              f"(all identical: {r['all_identical']})")
        print(f"  lengths         : {r['degenerate_lengths']}")
        print(f"  classes         : {r['character_classes']}")
        print(f"  by target       : {r['degenerate_by_target']} "
              f"(one-sided: {r['one_sided']})")
        print(f"  healthy replies : {r['healthy_replies']} "
              f"len min/med/max = {r['healthy_len_min']}/"
              f"{r['healthy_len_median']}/{r['healthy_len_max']}")
        print(f"  ADJUDICATION    : {r['adjudication']}")

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(
        {"schema": "degeneracy_adjudication/1",
         "note": ("Shapes only - no reply text. Distinctness, not brevity, separates a "
                  "constant-string backend fault from legitimate short answers."),
         "runs": rows}, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

