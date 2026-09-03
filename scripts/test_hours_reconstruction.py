#!/usr/bin/env python3
"""Synthetic fixture test for scripts/hours_reconstruction.py.

WHAT IT PROVES
  1. Sessionisation is exactly the stated rule: a gap STRICTLY GREATER than the
     threshold splits; a gap exactly equal to it does not.
  2. A single-event session has a span of zero. Nothing is padded.
  3. The keyword table is applied in order, first match wins, and the printed
     needle is the one that actually fired.
  4. COUNTED / UNCOUNTED / MIXED follows the stated session rule (all-counted,
     all-uncounted, otherwise mixed).
  5. Human-only row selection: mechanical Phase-1 rows and judge-only Phase-2 rows
     are excluded; append-only re-saves are counted as save events and reported
     separately from distinct rows.
  6. The clock rule is lifted VERBATIM from the plan and the script REFUSES to
     trim a quote it presents as verbatim.
  7. The rendered document contains the totals that independent arithmetic in this
     test computes, and contains NO single "true hours" figure line.
  8. The real `git log` subprocess path parses into the same event shape as the
     fixture path (proved against a throwaway git repo, not this one).

SYNTHETIC DATA IS NOT DATA
  Every timestamp and subject below is invented to exercise the arithmetic. None of
  it is a result and none of it is written anywhere near results/.

    python scripts/test_hours_reconstruction.py
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import hours_reconstruction as HR  # noqa: E402

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


# ------------------------------------------------------------------- fixture data
# IST timestamps. Designed so the session boundaries are checkable by hand:
#   S1  09:00, 10:00, 11:30           gaps 60, 90     -> one session, span 2h30m
#                                     (90 is NOT > 90: the boundary case)
#   S2  13:01                         gap 91          -> splits; single event, span 0
#   S3  20:00, 20:30                  gap 419         -> splits; span 30m
#   S4  next day 09:00, 09:45         -> span 45m
GIT_FIXTURE = [
    ("2026-01-01T09:00:00+05:30", "docs: decision 1 - ratified by Ebin"),
    ("2026-01-01T10:00:00+05:30", "analysis: join the graded rows"),
    ("2026-01-01T11:30:00+05:30", "phase 2: grading UI save path"),
    ("2026-01-01T13:01:00+05:30", "gate0 fix: vLLM adapter prefix blocker"),
    ("2026-01-01T20:00:00+05:30", "scaffold: repo skeleton (pre-clock setup)"),
    ("2026-01-01T20:30:00+05:30", "ops: pods terminated"),
    ("2026-01-02T09:00:00+05:30", "phase-c: train the ladder"),
    ("2026-01-02T09:45:00+05:30", "writeup: results section"),
]

# Expected: (span_minutes, n_events, clock)
GIT_EXPECT = [
    (150, 3, "COUNTED"),     # docs + analysis + grading tools -> all counted
    (0, 1, "UNCOUNTED"),     # gate0 fix -> setup/infra only
    (30, 2, "UNCOUNTED"),    # scaffold + ops -> setup/infra only
    (45, 2, "MIXED"),        # training (MIXED) + write-up (COUNTED)
]

# Category assignment the ordered table must produce, subject -> category.
CAT_EXPECT = {
    "docs: decision 1 - ratified by Ebin": "docs/decisions",
    "analysis: join the graded rows": "analysis",
    "phase 2: grading UI save path": "grading tools",
    "gate0 fix: vLLM adapter prefix blocker": "setup/infra",
    "scaffold: repo skeleton (pre-clock setup)": "setup/infra",
    "ops: pods terminated": "setup/infra",
    "phase-c: train the ladder": "training",
    "writeup: results section": "write-up",
}

# Grading fixtures, in UTC as the real logs are.
# human phase-1: 04:00, 04:20 (one is a RE-SAVE of the same run_id) ; 04:50
# mechanical rows share one timestamp and must be dropped
P1_FIXTURE = [
    {"run_id": "r1", "extracted_by": "human", "extracted_utc": "2026-01-05T04:00:00Z"},
    {"run_id": "r1", "extracted_by": "human", "extracted_utc": "2026-01-05T04:20:00Z"},
    {"run_id": "r2", "extracted_by": "human", "extracted_utc": "2026-01-05T04:50:00Z"},
    {"run_id": "r9", "extracted_by": "mechanical:scripts/phase1_mechanical_extract.py",
     "extracted_utc": "2026-01-05T23:00:00Z"},
    {"run_id": "r8", "extracted_by": "mechanical:scripts/phase1_mechanical_extract.py",
     "extracted_utc": "2026-01-05T23:00:00Z"},
]
# human phase-2: 05:10, 05:30 ; then a 2h gap -> 07:40, 07:50
# judge-only rows (human_grade null) must be dropped even though they carry a stamp
P2_FIXTURE = [
    {"run_id": "r1", "condition": "v0", "human_grade": "FULL",
     "graded_utc": "2026-01-05T05:10:00Z"},
    {"run_id": "r2", "condition": "v0", "human_grade": "MISS",
     "graded_utc": "2026-01-05T05:30:00Z"},
    {"run_id": "r3", "condition": "v0", "human_grade": None, "judge_grade": "MISS",
     "graded_utc": "2026-01-05T06:00:00Z"},
    {"run_id": "r4", "condition": "v0", "human_grade": "CR",
     "graded_utc": "2026-01-05T07:40:00Z"},
    {"run_id": "r4", "condition": "v0", "human_grade": "CR",
     "adjudicated_grade": "FULL", "graded_utc": "2026-01-05T07:50:00Z"},
]
# Sessions over the union (UTC 04:00 04:20 04:50 05:10 05:30 07:40 07:50):
#   gaps 20,30,20,20,130,10 -> split at 130 -> two sessions: 90m and 10m
GRADE_EXPECT = [(90, 5), (10, 2)]

PLAN_FIXTURE = (
    "# plan\n"
    "## 0. Rules of engagement\n"
    "- **This plan is sanctioned prep.**\n"
    "- The 20h clock counts your working time. Uncounted: general learning, "
    "GPU/env setup, and waiting on training runs.\n"
    "- Log hours in toggl from the first clocked minute.\n"
)
PLAN_QUOTE = ("The 20h clock counts your working time. Uncounted: general learning, "
              "GPU/env setup, and waiting on training runs.")


def write_fixtures(root: Path) -> tuple[Path, Path, Path, Path]:
    log = root / "SYNTHETIC_git_log.txt"
    log.write_text("".join(f"{iso}{HR.UNIT_SEP}{subj}\n" for iso, subj in GIT_FIXTURE),
                   encoding="utf-8")
    p1 = root / "SYNTHETIC_phase1.jsonl"
    p1.write_text("".join(json.dumps(r) + "\n" for r in P1_FIXTURE), encoding="utf-8")
    p2 = root / "SYNTHETIC_phase2.jsonl"
    p2.write_text("".join(json.dumps(r) + "\n" for r in P2_FIXTURE), encoding="utf-8")
    plan = root / "SYNTHETIC_plan.md"
    plan.write_text(PLAN_FIXTURE, encoding="utf-8")
    return log, p1, p2, plan


def mins(td: _dt.timedelta) -> int:
    return int(round(td.total_seconds() / 60))


def main() -> int:
    print(__doc__.splitlines()[0])
    tmp = Path(tempfile.mkdtemp(prefix="hours_recon_"))
    log, p1, p2, plan = write_fixtures(tmp)

    # ------------------------------------------------------- 1-4 git sessionisation
    print("\ngit sessions (gap rule, spans, categories, clock class)")
    events = HR.parse_git_log_text(log.read_text(encoding="utf-8"))
    check(len(events) == len(GIT_FIXTURE), "every fixture line parsed")
    check(all(e["when"].utcoffset() == _dt.timedelta(hours=5, minutes=30)
              for e in events), "timestamps expressed in IST")

    sessions = HR.sessionize(events, HR.DEFAULT_GAP_MINUTES)
    for s in sessions:
        HR.classify_session(s)
    check(len(sessions) == len(GIT_EXPECT),
          f"{len(GIT_EXPECT)} sessions from the fixture (gap > 90 min)")
    for got, (span, n, clock) in zip(sessions, GIT_EXPECT):
        check(mins(got["span"]) == span and got["n_events"] == n,
              f"session {got['n']}: span {span}m over {n} events")
        check(got["clock"] == clock, f"session {got['n']} tagged {clock}")
    check(mins(sessions[1]["span"]) == 0, "single-event session has span zero")
    check(any(mins(e["when"] - p["when"]) == HR.DEFAULT_GAP_MINUTES
              for p, e in zip(events, events[1:])),
          "fixture contains a gap of exactly 90 min (the boundary case)")
    check(len([s for s in sessions if any(
        mins(e2["when"] - e1["when"]) == HR.DEFAULT_GAP_MINUTES
        for e1, e2 in zip(s["events"], s["events"][1:]))]) == 1,
        "a gap of exactly 90 min does NOT split (rule is strictly greater)")

    print("\ncategory inference")
    for subject, expected in CAT_EXPECT.items():
        cat, needle = HR.categorize(subject)
        check(cat == expected and needle and needle in subject.lower(),
              f"{expected:14} <- {subject[:52]!r} via {needle!r}")
    check(HR.categorize("something with no keyword at all")[0] == HR.UNCATEGORIZED,
          "an unmatched subject is UNCATEGORIZED")
    check(HR.CLOCK_CLASS[HR.UNCATEGORIZED] == "MIXED",
          "UNCATEGORIZED is MIXED, so it cannot inflate the counted total")

    # -------------------------------------------------------------- 5 grading rows
    print("\ngrading rows (human only, save events vs distinct rows)")
    gev, gstats = HR.grading_events(p1, p2)
    check(gstats["phase1_human_saves"] == 3, "3 phase-1 human save events")
    check(gstats["phase1_human_distinct"] == 2,
          "2 distinct phase-1 rows (one re-save collapsed)")
    check(gstats["phase1_mechanical_rows"] == 2, "2 mechanical rows detected")
    check(all("23:00" not in e["when"].isoformat() for e in gev),
          "no mechanical timestamp entered the event stream")
    check(gstats["phase2_human_saves"] == 4, "4 phase-2 human save events")
    check(gstats["phase2_human_distinct"] == 3, "3 distinct phase-2 rows")
    check(gstats["phase2_judge_only_rows"] == 1, "the judge-only row is excluded")
    check(gstats["phase2_adjudicated_saves"] == 1, "the adjudication save is counted")

    gsessions = HR.sessionize(gev, HR.DEFAULT_GAP_MINUTES)
    check(len(gsessions) == len(GRADE_EXPECT), "2 grading sessions")
    for got, (span, n) in zip(gsessions, GRADE_EXPECT):
        check(mins(got["span"]) == span and got["n_events"] == n,
              f"grading session {got['n']}: span {span}m over {n} saves")

    # ------------------------------------------------------------ 6 verbatim quote
    print("\nclock rule (verbatim, refuses to trim)")
    quote, words = HR.extract_clock_rule(plan)
    check(quote == PLAN_QUOTE, "quote lifted verbatim from the plan")
    check(quote in PLAN_FIXTURE, "the quote is a literal substring of the source")
    check(words == len(PLAN_QUOTE.split()), f"word count reported ({words})")
    try:
        HR.extract_clock_rule(plan, max_words=5)
        check(False, "an over-long quote is REFUSED, not trimmed")
    except ValueError:
        check(True, "an over-long quote is REFUSED, not trimmed")
    try:
        HR.extract_clock_rule(tmp / "SYNTHETIC_phase1.jsonl")
        check(False, "a plan without the rule fails loudly")
    except ValueError:
        check(True, "a plan without the rule fails loudly")

    # ------------------------------------------------------- 7 rendered document
    print("\nrendered document")
    out = tmp / "SYNTHETIC_HOURS_RECONSTRUCTION.md"
    p = subprocess.run(
        [sys.executable, str(_HERE / "hours_reconstruction.py"),
         "--git-log", str(log), "--phase1", str(p1), "--phase2", str(p2),
         "--plan", str(plan), "--out", str(out)],
        capture_output=True, text=True, encoding="utf-8", cwd=str(HR.REPO))
    check(p.returncode == 0, f"CLI exits 0 (rc={p.returncode})")
    if p.returncode != 0:
        print((p.stdout or "") + (p.stderr or ""))
    md = out.read_text(encoding="utf-8")

    counted = sum((s["span"] for s in sessions if s["clock"] == "COUNTED"),
                  _dt.timedelta(0))
    uncounted = sum((s["span"] for s in sessions if s["clock"] == "UNCOUNTED"),
                    _dt.timedelta(0))
    mixed = sum((s["span"] for s in sessions if s["clock"] == "MIXED"),
                _dt.timedelta(0))
    gtot = sum((s["span"] for s in gsessions), _dt.timedelta(0))
    check(HR.hm(counted) in md, f"COUNTED total {HR.hm(counted)} appears in the doc")
    check(HR.hm(uncounted) in md,
          f"UNCOUNTED total {HR.hm(uncounted)} appears in the doc")
    check(HR.hm(mixed) in md, f"MIXED total {HR.hm(mixed)} appears in the doc")
    check(HR.hm(gtot) in md, f"grading total {HR.hm(gtot)} appears in the doc")
    check(HR.hm(counted + mixed) in md, "the COUNTED+MIXED upper row appears")
    check(quote in md, "the verbatim clock rule appears in the doc")
    for _, needles in HR.CATEGORY_RULES:
        for needle in needles:
            if f"`{needle.strip()}`" not in md:
                check(False, f"keyword table prints needle {needle!r}")
                break
        else:
            continue
        break
    else:
        check(True, "the whole keyword table is printed in the doc")
    for subject in CAT_EXPECT:
        if subject.replace("|", "\\|")[:40] not in md:
            check(False, f"per-commit row missing for {subject!r}")
            break
    else:
        check(True, "every commit appears in the per-commit audit table")

    banned = ("total hours worked", "true hours", "estimated hours",
              "best estimate", "actual hours")
    check(not any(b in md.lower() for b in banned),
          "the doc states no single 'true hours' figure")
    check("NO hours total" in p.stdout or "no total" in md.lower()
          or "states no total" in md.lower(),
          "the doc says plainly that it states no total")
    check("HOURS_LEDGER_TEMPLATE.md" in md,
          "the doc defers to the human ledger template")
    check("data/sealed/" in md and "No file under" in md,
          "the doc records that no sealed file was read")

    # --------------------------------------------------- 8 the real git log path
    print("\ngit subprocess path (throwaway repo, not this one)")
    repo = tmp / "repo"
    repo.mkdir()
    env = dict(os.environ, GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@e",
               GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@e",
               GIT_CONFIG_GLOBAL=str(tmp / "nonexistent_gitconfig"),
               GIT_CONFIG_NOSYSTEM="1")
    subprocess.run(["git", "init", "-q"], cwd=repo, env=env, check=True,
                   capture_output=True)
    for iso, subject in GIT_FIXTURE[:3]:
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", subject],
                       cwd=repo, check=True, capture_output=True,
                       env=dict(env, GIT_AUTHOR_DATE=iso, GIT_COMMITTER_DATE=iso))
    parsed = HR.parse_git_log_text(HR.run_git_log(repo))
    check([e["label"] for e in parsed] == [s for _, s in GIT_FIXTURE[:3]],
          "subjects round-trip through the real git log format")
    check([e["when"].isoformat() for e in parsed]
          == [HR._iso_to_ist(i).isoformat() for i, _ in GIT_FIXTURE[:3]],
          "author timestamps round-trip and land in IST")

    print(f"\n{_checks - len(_fails)}/{_checks} checks pass")
    print(f"synthetic fixtures under {tmp} (nothing written to results/)")
    if _fails:
        for f in _fails:
            print(f"  FAILED: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
