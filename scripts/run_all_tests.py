"""Run every committed test and print one pass/fail table.

This is the "analysis instrument as code" receipt (PREREGISTRATION.md Addendum E): the
aggregation, the join, the figures and the grading tools all have synthetic-input tests
that run before unsealing, and this script is the single command that exercises them.

Every test here is synthetic or offline. None reads data/sealed/ and none makes a
billable API call.

Run: python scripts/run_all_tests.py
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# (label, argv) - ordered roughly by the pipeline stage they protect
TESTS = [
    ("analysis instrument (rates, Wilson, cost)", ["scripts/test_analysis_instrument.py"]),
    ("cost invariant (null-not-zero)", ["scripts/test_cost_invariant.py"]),
    ("budget guard (unpriced model fails closed)", ["scripts/test_budget_guard.py"]),
    ("v1 handoff (generator -> validator)", ["scripts/test_v1_handoff.py"]),
    ("KL bias (baseline floor)", ["scripts/test_kl_bias.py"]),
    ("analysis join (+ --exclude-runs sensitivity)", ["scripts/test_analysis_join.py"]),
    ("make_figures (renders from join output)", ["scripts/test_make_figures.py"]),
    ("phase 2 grading + judge (synthetic, no calls)",
     ["scripts/test_phase2_grading.py"]),
    ("unseal preconditions (temp git repo, fake map)", ["scripts/test_unseal.py"]),
    ("phase 2 render (real claims, no [object Object])",
     ["scripts/test_phase2_render.py"]),
]

# Scripts that must at least import and expose --help without side effects.
SMOKE = [
    ("phase1_grade --help", ["scripts/phase1_grade.py", "--help"]),
    ("phase2_grade --help", ["scripts/phase2_grade.py", "--help"]),
    ("judge_grade --help", ["scripts/judge_grade.py", "--help"]),
    ("analysis_join --help", ["scripts/analysis_join.py", "--help"]),
    ("make_figures --help", ["scripts/make_figures.py", "--help"]),
    ("adjudicate_degeneracy --help", ["scripts/adjudicate_degeneracy.py", "--help"]),
    ("verify_no_unpriced --help", ["scripts/verify_no_unpriced.py", "--help"]),
    ("unseal --help", ["scripts/unseal.py", "--help"]),
]


def run(argv: list[str], timeout: int = 900) -> tuple[bool, float, str]:
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable] + argv, cwd=REPO, capture_output=True,
                           text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, time.time() - t0, f"TIMEOUT after {timeout}s"
    dt = time.time() - t0
    if p.returncode == 0:
        tail = [l for l in (p.stdout or "").splitlines() if l.strip()]
        return True, dt, (tail[-1][:64] if tail else "")
    err = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()
    return False, dt, (err[-1][:64] if err else f"rc={p.returncode}")


def main() -> int:
    rows = []
    print("running committed tests\n")
    for label, argv in TESTS:
        ok, dt, note = run(argv)
        rows.append(("test", label, ok, dt, note))
        print(f"  {'PASS' if ok else 'FAIL'}  {label}  ({dt:.1f}s)")
    print("\nrunning CLI smoke checks\n")
    for label, argv in SMOKE:
        ok, dt, note = run(argv, timeout=120)
        rows.append(("smoke", label, ok, dt, note))
        print(f"  {'PASS' if ok else 'FAIL'}  {label}  ({dt:.1f}s)")

    n_pass = sum(1 for r in rows if r[2])
    print("\n" + "=" * 78)
    print(f"{'kind':6} {'check':46} {'result':7} {'secs':>6}")
    print("-" * 78)
    for kind, label, ok, dt, note in rows:
        print(f"{kind:6} {label:46.46} {'PASS' if ok else 'FAIL':7} {dt:6.1f}")
        if not ok and note:
            print(f"       -> {note}")
    print("-" * 78)
    print(f"{n_pass}/{len(rows)} checks pass")
    print("All synthetic or offline: no sealed read, no billable API call.")
    return 0 if n_pass == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
