#!/usr/bin/env python3
"""Reconstruct ACTIVITY SPANS from records that already exist. Not an hours ledger.

WHY THIS SCRIPT EXISTS
  The application form asks for an hours figure and no timer was kept. Two of the
  three options are bad: overstating is worse than a large honest number, and
  hiding the fact that no timer ran is worst of all. The third option is to say
  exactly what the repo can and cannot witness, and let Ebin state his own figure
  beside it.

  writeup/HOURS_LEDGER_TEMPLATE.md is the ledger, and it stays blank until a human
  fills it. This script does NOT fill it and does not compete with it. It emits a
  separate document, writeup/HOURS_RECONSTRUCTION.md, containing only spans that
  are literally recorded in files:

    (a) git commit author timestamps       -> when a file was written
    (b) grading-row save timestamps        -> when Ebin pressed save on a card

WHAT IT WILL NOT DO
  - It will not produce a "true hours" number, a best estimate, or a midpoint.
  - It will not pad a single-commit session to any nonzero duration.
  - It will not add the grading total to the git total: they overlap in wall-clock
    time, and the overlap is measured and printed rather than assumed away.
  - It will not decide whether a MIXED session was work or waiting. Only Ebin knows
    what he was doing while a training ran; the rule says that is what decides it.

  Every rule the script applies is stated in the output, including the keyword table
  used to categorise commits, so a reader can disagree with a specific row rather
  than with the number.

THE ONE ARITHMETIC RULE
  Sessions: events are sorted; a gap STRICTLY GREATER than --gap-minutes (default 90)
  starts a new session. A session's SPAN is (last event - first event). A session of
  one event has a span of zero. That is deliberate: work happened, but this record
  does not witness its duration, and inventing one would be an estimate.

USAGE
    python scripts/hours_reconstruction.py
    python scripts/hours_reconstruction.py --git-log fixtures/log.tsv --phase1 ... --phase2 ...
    python scripts/test_hours_reconstruction.py       # synthetic fixtures
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30), "IST")
UNIT_SEP = "\x1f"  # git --pretty field separator; cannot occur in a subject line

DEFAULT_GAP_MINUTES = 90

# ------------------------------------------------------------------ categorisation
# ORDERED. First rule whose needle appears in the lowercased subject wins. The whole
# table is printed into the output document so the inference is auditable line by
# line: to challenge a row you challenge a specific needle, not a hidden heuristic.
#
# The prefixes are this repo's own commit conventions ("docs:", "writeup:",
# "phase-a:", ...), which is why prefix-shaped needles come first.
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("docs/decisions", [
        "docs:", "prereg amendment", "preregistration freeze", "decision log",
    ]),
    ("write-up", [
        "writeup:", "write-up", "exec-summary", "exec summary", "citation",
        "form-answer",
    ]),
    ("setup/infra", [
        "scaffold:", "pre-clock", "gate0", "gate 0", "initial commit", "merge:",
        "license", "checkpoint:", "ops:", "pod setup", "pod rebuild", "env setup",
    ]),
    ("grading", [
        "phase-1 claims complete", "phase 2 complete", "phase 2 extension complete",
        "adjudication complete", "re-adjudication", "phase-1 mechanical extension",
        "phase 2 checkpoint", "unsealed - ", "unsealed — ",
    ]),
    ("grading tools", [
        "grading ui", "grading helper", "phase 1 grading", "phase-1 grading",
        "judge:", "judge pass", "phase 2:", "phase 2 ", "phase1:", "phase1/",
        "unseal:", "addendum d",
    ]),
    ("harness", [
        "phase-a", "harness", "agent:", "serve", "fix:", "v1:", "recorder",
        "tool schema", "config", "unit test",
    ]),
    ("analysis", [
        "analysis", "join:", "join ", "figures:", "figure", "screen:", "audit:",
        "tests:", "agreement", "decomposition", "receipt:", "comparison",
        "unpriced",
    ]),
    ("campaign (data collection)", [
        "campaign", "sealed - ", "sealed arm", "sealed serving",
        "seal prerequisite", "baselines", "task a", "task d", "task e",
        "dev-null", "dev evidence", "dev deconfounding", "exploratory:", "probe",
    ]),
    ("training", [
        "phase-b", "phase-c", "phase-d", "phase-e", "train", "ladder", "rung",
        "dataset", "matrix", "canary", "l4", "express", "prompts", "suites",
    ]),
]

UNCATEGORIZED = "uncategorized"

# Clock class per category. The RULE, stated once and applied mechanically:
#   COUNTED   - the category is working time under the plan's rule
#   UNCOUNTED - the plan names it as free (generic setup; waiting)
#   MIXED     - the plan makes it turn on what Ebin was doing meanwhile, which no
#               file in this repo records; the script refuses to guess.
CLOCK_CLASS: dict[str, str] = {
    "docs/decisions": "COUNTED",
    "write-up": "COUNTED",
    "grading": "COUNTED",
    "grading tools": "COUNTED",
    "analysis": "COUNTED",
    "harness": "COUNTED",
    "campaign (data collection)": "MIXED",
    "training": "MIXED",
    "setup/infra": "UNCOUNTED",
    UNCATEGORIZED: "MIXED",
}

CLASS_NOTE = {
    "COUNTED": "project code, analysis, planning, decisions and write-up: counted",
    "UNCOUNTED": "generic env/GPU/tooling setup: named as free by the plan",
    "MIXED": ("launching and supervising is counted, waiting is free provided you "
              "were doing something else; git cannot tell those apart"),
}


def categorize(subject: str) -> tuple[str, str]:
    """Return (category, the needle that matched). First matching rule wins."""
    s = subject.lower()
    for category, needles in CATEGORY_RULES:
        for needle in needles:
            if needle in s:
                return category, needle
    return UNCATEGORIZED, ""


# ------------------------------------------------------------------------- loading
def parse_git_log_text(text: str) -> list[dict]:
    """Parse `git log --pretty=format:%aI<US>%s` output (any order) into events."""
    events = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if UNIT_SEP in line:
            iso, subject = line.split(UNIT_SEP, 1)
        elif "|" in line:  # fixture-friendly fallback
            iso, subject = line.split("|", 1)
        else:
            raise ValueError(f"unparseable git-log line: {line!r}")
        events.append({"when": _iso_to_ist(iso.strip()), "label": subject.strip()})
    events.sort(key=lambda e: e["when"])
    return events


def run_git_log(repo: Path) -> str:
    p = subprocess.run(
        ["git", "log", f"--pretty=format:%aI{UNIT_SEP}%s"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
    )
    if p.returncode != 0:
        raise RuntimeError(f"git log failed in {repo}: {(p.stderr or '').strip()}")
    return p.stdout


def _iso_to_ist(iso: str) -> _dt.datetime:
    """Parse an ISO-8601 instant (any offset, or trailing Z) and express it in IST."""
    if iso.endswith(("Z", "z")):
        iso = iso[:-1] + "+00:00"
    dt = _dt.datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        raise ValueError(f"timestamp has no timezone, refusing to guess one: {iso!r}")
    return dt.astimezone(IST)


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def grading_events(phase1: Path, phase2: Path) -> tuple[list[dict], dict]:
    """Ebin's hands-on grading saves, human rows only.

    Phase 1: a row is human iff extracted_by == "human". The mechanical rows carry
             extracted_by == "mechanical:scripts/phase1_mechanical_extract.py" and all
             share ONE timestamp (the script's run), so they are script time, not
             hands-on time, and are excluded.
    Phase 2: a row is human iff human_grade is non-null. Judge-only rows carry
             human_grade == null and are excluded.

    Each surviving line is a SAVE EVENT, not a distinct row: the logs are
    append-only and a re-saved card appears again. Both counts are reported.
    """
    p1 = load_jsonl(phase1)
    p2 = load_jsonl(phase2)

    ev: list[dict] = []
    for r in p1:
        if r.get("extracted_by") == "human" and r.get("extracted_utc"):
            ev.append({"when": _iso_to_ist(r["extracted_utc"]), "label": "phase1",
                       "key": ("phase1", r.get("run_id"))})
    for r in p2:
        if r.get("human_grade") and r.get("graded_utc"):
            ev.append({"when": _iso_to_ist(r["graded_utc"]), "label": "phase2",
                       "key": ("phase2", r.get("condition"), r.get("run_id"))})
    ev.sort(key=lambda e: e["when"])

    stats = {
        "phase1_rows_total": len(p1),
        "phase1_human_saves": sum(1 for e in ev if e["label"] == "phase1"),
        "phase1_human_distinct": len({e["key"] for e in ev if e["label"] == "phase1"}),
        "phase1_mechanical_rows": sum(
            1 for r in p1 if str(r.get("extracted_by", "")).startswith("mechanical")),
        "phase2_rows_total": len(p2),
        "phase2_human_saves": sum(1 for e in ev if e["label"] == "phase2"),
        "phase2_human_distinct": len({e["key"] for e in ev if e["label"] == "phase2"}),
        "phase2_judge_only_rows": sum(1 for r in p2 if not r.get("human_grade")),
        "phase2_adjudicated_saves": sum(1 for r in p2 if r.get("adjudicated_grade")),
    }
    return ev, stats


# ---------------------------------------------------------------------- sessionise
def sessionize(events: list[dict], gap_minutes: int) -> list[dict]:
    """Group time-sorted events. A gap > gap_minutes starts a new session."""
    if not events:
        return []
    gap = _dt.timedelta(minutes=gap_minutes)
    sessions: list[dict] = []
    current = [events[0]]
    for prev, ev in zip(events, events[1:]):
        if ev["when"] - prev["when"] > gap:
            sessions.append(_close(current))
            current = [ev]
        else:
            current.append(ev)
    sessions.append(_close(current))
    for i, s in enumerate(sessions, 1):
        s["n"] = i
    return sessions


def _close(evs: list[dict]) -> dict:
    return {
        "start": evs[0]["when"],
        "end": evs[-1]["when"],
        "span": evs[-1]["when"] - evs[0]["when"],
        "events": list(evs),
        "n_events": len(evs),
    }


def classify_session(session: dict) -> None:
    """Attach category counts and the COUNTED/UNCOUNTED/MIXED tag."""
    cats: dict[str, int] = {}
    for ev in session["events"]:
        cat, needle = categorize(ev["label"])
        ev["category"] = cat
        ev["matched"] = needle
        cats[cat] = cats.get(cat, 0) + 1
    session["categories"] = cats
    classes = {CLOCK_CLASS[c] for c in cats}
    if classes == {"COUNTED"}:
        session["clock"] = "COUNTED"
    elif classes == {"UNCOUNTED"}:
        session["clock"] = "UNCOUNTED"
    else:
        session["clock"] = "MIXED"


# ------------------------------------------------------------------------- overlap
def overlap(a_start, a_end, b_start, b_end) -> _dt.timedelta:
    lo, hi = max(a_start, b_start), min(a_end, b_end)
    return hi - lo if hi > lo else _dt.timedelta(0)


def total_overlap(xs: list[dict], ys: list[dict]) -> _dt.timedelta:
    t = _dt.timedelta(0)
    for x in xs:
        for y in ys:
            t += overlap(x["start"], x["end"], y["start"], y["end"])
    return t


# -------------------------------------------------------------------- clock rule
def extract_clock_rule(plan: Path, max_words: int = 25) -> tuple[str, int]:
    """Pull the 20h-clock sentence VERBATIM from the execution plan.

    Located by anchor text, not by line number, and returned unedited. If the located
    quote exceeds max_words the script fails rather than trimming a quote it is
    presenting as verbatim.
    """
    text = plan.read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip().lstrip("-").strip()
        if "20h clock counts" in line:
            quote = line
            n = len(quote.split())
            if n > max_words:
                raise ValueError(
                    f"clock rule quote is {n} words (> {max_words}); refusing to "
                    f"trim a quote presented as verbatim: {quote!r}")
            return quote, n
    raise ValueError(f"clock rule sentence not found in {plan}")


# --------------------------------------------------------------------- formatting
def hm(td: _dt.timedelta) -> str:
    mins = int(round(td.total_seconds() / 60))
    return f"{mins // 60}h{mins % 60:02d}m"


def hours(td: _dt.timedelta) -> float:
    return round(td.total_seconds() / 3600.0, 2)


def _cats(session: dict) -> str:
    return ", ".join(f"{c} x{n}" for c, n in
                     sorted(session["categories"].items(), key=lambda kv: -kv[1]))


def _end(session: dict) -> str:
    """End time, marked +1d when the session crossed midnight."""
    days = (session["end"].date() - session["start"].date()).days
    return session["end"].strftime("%H:%M") + (f" (+{days}d)" if days else "")


# ----------------------------------------------------------------------- rendering
def render(git_sessions, grade_sessions, gstats, rule, rule_words, gap, meta) -> str:
    L: list[str] = []
    add = L.append

    add("# Hours reconstruction — activity spans from the record, NOT a ledger")
    add("")
    add(f"Generated by `scripts/hours_reconstruction.py` on "
        f"{meta['generated_ist']} IST. Regenerate with one command; do not hand-edit.")
    add("")
    add("**Read this first.** No timer was kept. This document therefore does not "
        "contain an hours figure, and no number in it should be copied into the "
        "form as one. What it contains is every span this repository can actually "
        "witness: when a commit was authored, and when a grading card was saved. "
        "A commit timestamp marks the moment a file was written, not the effort "
        "that produced it; the thinking, reading, orchestration, supervision and "
        "verification around it leave no trace here. The blank ledger in "
        "`writeup/HOURS_LEDGER_TEMPLATE.md` is still the thing Ebin fills in. This "
        "is a memory aid with its arithmetic shown, and the honest framing is: "
        "*here is what the record proves happened, here is the figure I state, "
        "and here is why they differ.*")
    add("")
    add("**The session rule (the only arithmetic in this document).** Events are "
        f"sorted by timestamp; a gap of **more than {gap} minutes** starts a new "
        "session. A session's span is `last event − first event`. A session with "
        "one event has a span of **zero** — work happened, but this record does "
        "not witness its duration, and padding it would be an estimate. All times "
        "are IST (UTC+05:30).")
    add("")

    # ------------------------------------------------------------------ 1 · rule
    add("---")
    add("")
    add("## 1 · The clock rule this is measured against")
    add("")
    add(f"Verbatim from `{meta['plan_rel']}` ({rule_words} words):")
    add("")
    add(f"> {rule}")
    add("")
    add("Applied mechanically, per category:")
    add("")
    add("| clock class | categories | why |")
    add("|---|---|---|")
    for klass in ("COUNTED", "MIXED", "UNCOUNTED"):
        cats = sorted(c for c, k in CLOCK_CLASS.items() if k == klass)
        add(f"| **{klass}** | {', '.join('`' + c + '`' for c in cats)} | "
            f"{CLASS_NOTE[klass]} |")
    add("")
    add("A session is **COUNTED** if every commit in it is a counted category, "
        "**UNCOUNTED** if every commit is an uncounted category, and **MIXED** "
        "otherwise. MIXED is not a hedge: the plan's own rule for training and "
        "campaign time turns on what Ebin was doing meanwhile, and no file in this "
        "repo records that. Resolving MIXED is his call, not the script's.")
    add("")

    # -------------------------------------------------- 2 · keyword table (audit)
    add("---")
    add("")
    add("## 2 · The keyword table (so the inference is auditable)")
    add("")
    add("Commit subjects are lowercased and matched against this **ordered** table; "
        "the first rule with a matching needle wins. Each session row below prints "
        "the categories it resolved to, and §3.1 prints the needle that fired for "
        "every single commit.")
    add("")
    add("| order | category | clock | needles (first match wins) |")
    add("|---|---|---|---|")
    for i, (cat, needles) in enumerate(CATEGORY_RULES, 1):
        add(f"| {i} | `{cat}` | {CLOCK_CLASS[cat]} | "
            f"{', '.join('`' + n.strip() + '`' for n in needles)} |")
    add(f"| — | `{UNCATEGORIZED}` | {CLOCK_CLASS[UNCATEGORIZED]} | "
        "nothing matched; treated as MIXED so it cannot silently inflate the "
        "counted total |")
    add("")

    # -------------------------------------------------------- 3 · git sessions
    n_commits = sum(s["n_events"] for s in git_sessions)
    add("---")
    add("")
    add("## 3 · Git sessions")
    add("")
    add(f"{n_commits} commits, {len(git_sessions)} sessions, "
        f"{git_sessions[0]['start'].strftime('%Y-%m-%d %H:%M')} to "
        f"{git_sessions[-1]['end'].strftime('%Y-%m-%d %H:%M')} IST.")
    add("")
    add("| # | date (IST) | start | end | span | commits | clock | categories |")
    add("|---|---|---|---|---|---|---|---|")
    for s in git_sessions:
        add(f"| {s['n']} | {s['start'].strftime('%Y-%m-%d')} | "
            f"{s['start'].strftime('%H:%M')} | {_end(s)} | "
            f"{hm(s['span'])} | {s['n_events']} | {s['clock']} | {_cats(s)} |")
    add("")
    tot = {k: _dt.timedelta(0) for k in ("COUNTED", "MIXED", "UNCOUNTED")}
    for s in git_sessions:
        tot[s["clock"]] += s["span"]
    add(f"- COUNTED session span: **{hm(tot['COUNTED'])}** "
        f"({hours(tot['COUNTED'])} h) over "
        f"{sum(1 for s in git_sessions if s['clock'] == 'COUNTED')} sessions")
    add(f"- MIXED session span: **{hm(tot['MIXED'])}** ({hours(tot['MIXED'])} h) over "
        f"{sum(1 for s in git_sessions if s['clock'] == 'MIXED')} sessions")
    add(f"- UNCOUNTED session span: **{hm(tot['UNCOUNTED'])}** "
        f"({hours(tot['UNCOUNTED'])} h) over "
        f"{sum(1 for s in git_sessions if s['clock'] == 'UNCOUNTED')} sessions")
    add(f"- sessions of a single commit (span zero by rule): "
        f"**{sum(1 for s in git_sessions if s['n_events'] == 1)}**")
    add("")
    add(f"{sum(1 for s in git_sessions if s['clock'] == 'MIXED')} of "
        f"{len(git_sessions)} sessions are MIXED, which is the honest reading of "
        "the record rather than a failure of the rule: a working session that "
        "touched a training or a campaign as well as code and decisions is MIXED by "
        "construction, and the plan makes those turn on what Ebin was doing while "
        "they ran. **No attempt is made to prorate a MIXED span across its "
        "categories** — that would be exactly the estimate this document exists to "
        "avoid. What can be counted without estimating is how many commits each "
        "category produced:")
    add("")
    add("| category | clock | commits | share |")
    add("|---|---|---|---|")
    comp: dict[str, int] = {}
    for s in git_sessions:
        for c, k in s["categories"].items():
            comp[c] = comp.get(c, 0) + k
    for c, k in sorted(comp.items(), key=lambda kv: -kv[1]):
        add(f"| `{c}` | {CLOCK_CLASS[c]} | {k} | {100.0 * k / n_commits:.0f}% |")
    add("")
    add("That is a count of commits, not of hours, and the two are not "
        "proportional: a one-line fix and a day's ladder build are one commit each.")
    add("")

    add("### 3.1 · Every commit, with the needle that categorised it")
    add("")
    add("| session | time (IST) | category | needle | subject |")
    add("|---|---|---|---|---|")
    for s in git_sessions:
        for ev in s["events"]:
            subj = ev["label"].replace("|", "\\|")
            if len(subj) > 110:
                subj = subj[:107] + "..."
            needle = f"`{ev['matched']}`" if ev["matched"] else "—"
            add(f"| {s['n']} | {ev['when'].strftime('%m-%d %H:%M')} | "
                f"`{ev['category']}` | {needle} | {subj} |")
    add("")

    # ----------------------------------------------------------- 4 · grading time
    add("---")
    add("")
    add("## 4 · Hands-on grading time (exact, from the grading logs)")
    add("")
    add("This is the one block of work with a real per-action timestamp. Each line "
        "in `results/phase1_claims.jsonl` and `results/phase2_grades.jsonl` records "
        "when a card was saved.")
    add("")
    add("**Row selection, stated so it can be checked:**")
    add("")
    add("- Phase 1 — human iff `extracted_by == \"human\"`. The "
        f"{gstats['phase1_mechanical_rows']} rows carrying "
        "`extracted_by == \"mechanical:scripts/phase1_mechanical_extract.py\"` are "
        "excluded: they all share a single timestamp (the script's run), so they "
        "are script time, not hands-on time.")
    add("- Phase 2 — human iff `human_grade` is non-null. The "
        f"{gstats['phase2_judge_only_rows']} judge-only rows (`human_grade == null`) "
        "are excluded.")
    add("- Both logs are **append-only**: a re-saved card appears again. The spans "
        "below are over SAVE EVENTS, which is the right unit for elapsed time; the "
        "distinct-row counts are given beside them and are the right unit for "
        "workload.")
    add("")
    add("| log | save events (human) | distinct rows | rows in file |")
    add("|---|---|---|---|")
    add(f"| phase 1 claims | {gstats['phase1_human_saves']} | "
        f"{gstats['phase1_human_distinct']} | {gstats['phase1_rows_total']} |")
    add(f"| phase 2 grades | {gstats['phase2_human_saves']} | "
        f"{gstats['phase2_human_distinct']} | {gstats['phase2_rows_total']} |")
    add(f"| — of which adjudication saves | {gstats['phase2_adjudicated_saves']} | | |")
    add("")

    if grade_sessions:
        add("| # | date (IST) | start | end | span | saves | phase 1 | phase 2 |")
        add("|---|---|---|---|---|---|---|---|")
        for s in grade_sessions:
            n1 = sum(1 for e in s["events"] if e["label"] == "phase1")
            n2 = s["n_events"] - n1
            add(f"| {s['n']} | {s['start'].strftime('%Y-%m-%d')} | "
                f"{s['start'].strftime('%H:%M')} | {_end(s)} | "
                f"{hm(s['span'])} | {s['n_events']} | {n1} | {n2} |")
        add("")
        gtot = sum((s["span"] for s in grade_sessions), _dt.timedelta(0))
        gsaves = sum(s["n_events"] for s in grade_sessions)
        add(f"- **total grading span: {hm(gtot)} ({hours(gtot)} h)** over "
            f"{len(grade_sessions)} sessions, {gsaves} save events")
        if gtot.total_seconds() > 0:
            add(f"- saves per hour: **{gsaves / (gtot.total_seconds() / 3600):.1f}**; "
                f"distinct rows per hour: "
                f"**{(gstats['phase1_human_distinct'] + gstats['phase2_human_distinct']) / (gtot.total_seconds() / 3600):.1f}**")
        add(f"- singleton sessions (span zero by rule): "
            f"**{sum(1 for s in grade_sessions if s['n_events'] == 1)}**")
        add("")
        add("This total is itself a **lower bound**, for a structural reason: a "
            "session's span starts at the save of its FIRST card, so the time spent "
            "reading that first transcript is outside the span. Every session "
            "undercounts by at least one card's work.")
        add("")
        gnote = meta["grading_overlap"]
        add(f"**Do not add this to §3.** The grading sessions overlap the git "
            f"sessions by **{hm(gnote)}** ({hours(gnote)} h) of wall clock — Ebin "
            "was committing on the same days he was grading. §3 and §4 are two "
            "views of one timeline, not two addends.")
    else:
        add("_No human grading events found in the supplied logs._")
    add("")

    # --------------------------------------------------------------- 5 · per day
    add("---")
    add("")
    add("## 5 · Per calendar day (IST)")
    add("")
    add("A session is assigned to the calendar day of its **start**, so a session "
        "crossing midnight lands wholly on the earlier day. Spans are summed inside "
        "the day; nothing is prorated.")
    add("")
    days = sorted({s["start"].date() for s in git_sessions} |
                  {s["start"].date() for s in grade_sessions})
    add("| day (IST) | COUNTED span | MIXED span | UNCOUNTED span | grading span | "
        "commits |")
    add("|---|---|---|---|---|---|")
    day_tot = {k: _dt.timedelta(0) for k in ("COUNTED", "MIXED", "UNCOUNTED")}
    grand_grade = _dt.timedelta(0)
    grand_commits = 0
    for d in days:
        row = {k: _dt.timedelta(0) for k in ("COUNTED", "MIXED", "UNCOUNTED")}
        nc = 0
        for s in git_sessions:
            if s["start"].date() == d:
                row[s["clock"]] += s["span"]
                nc += s["n_events"]
        g = sum((s["span"] for s in grade_sessions if s["start"].date() == d),
                _dt.timedelta(0))
        for k in row:
            day_tot[k] += row[k]
        grand_grade += g
        grand_commits += nc
        add(f"| {d.isoformat()} | {hm(row['COUNTED'])} | {hm(row['MIXED'])} | "
            f"{hm(row['UNCOUNTED'])} | {hm(g)} | {nc} |")
    add(f"| **total** | **{hm(day_tot['COUNTED'])}** | **{hm(day_tot['MIXED'])}** | "
        f"**{hm(day_tot['UNCOUNTED'])}** | **{hm(grand_grade)}** | "
        f"**{grand_commits}** |")
    add("")

    # ---------------------------------------------------------------- 6 · bounds
    lo = day_tot["COUNTED"]
    hi = day_tot["COUNTED"] + day_tot["MIXED"]
    add("---")
    add("")
    add("## 6 · What these numbers bound, and what they do not")
    add("")
    add("| bound | value | what it is |")
    add("|---|---|---|")
    add(f"| commit-visible COUNTED span | **{hm(lo)}** ({hours(lo)} h) | "
        "sum of sessions where every commit is a counted category |")
    add(f"| commit-visible COUNTED + MIXED span | **{hm(hi)}** ({hours(hi)} h) | "
        "the same, plus every training/campaign session in full |")
    add(f"| hands-on grading span | **{hm(grand_grade)}** ({hours(grand_grade)} h) | "
        "measured separately in §4; overlaps the two rows above |")
    add("")
    add("**Neither row is an upper bound on hours worked, and neither is a lower "
        "bound in the ordinary sense.** Specifically:")
    add("")
    add("- Work that produced no commit is invisible: reading, planning, reviewing "
        "agent output, verifying numbers by hand, the twin reviews, and every "
        "decision made before it was written down.")
    add("- Orchestration time is invisible. This project was run by directing "
        "agents; the human minutes spent specifying, reading and rejecting their "
        "output land between commits, and a gap in this table is equally "
        "consistent with deep work and with sleep.")
    add("- The lead-in to each session is invisible: a session begins at its first "
        "commit, and whatever preceded that commit is outside the span.")
    add("- Conversely, a long span is not evidence of continuous work. A session "
        "may contain breaks shorter than the gap rule.")
    n_zero_git = sum(1 for s in git_sessions if s["n_events"] == 1)
    n_zero_gr = sum(1 for s in grade_sessions if s["n_events"] == 1)
    add(f"- {n_zero_git} git session{'s' if n_zero_git != 1 else ''} and "
        f"{n_zero_gr} grading session{'s' if n_zero_gr != 1 else ''} have a span of "
        "exactly zero because they contain a single event.")
    add("- The MIXED span is not a residual to be split. Under the quoted rule it "
        "resolves entirely on what Ebin was doing during trainings and campaigns.")
    add("")
    add("**Therefore this document states no total.** The figure on the form is "
        "Ebin's to state from memory and calendar, exactly as "
        "`writeup/HOURS_LEDGER_TEMPLATE.md` requires; these spans are context to "
        "sanity-check it against, and the honest disclosure is that no timer ran.")
    add("")
    add("The +2h write-up allowance is a separate budget and is not derived here "
        "either. Sessions categorised `write-up` are shown as COUNTED because the "
        "script cannot see which of them were the executive summary; the split "
        "between the main write-up and the +2h allowance is a human call.")
    add("")
    add("---")
    add("")
    add(f"Inputs: `{meta['git_source']}` · `{meta['phase1_rel']}` · "
        f"`{meta['phase2_rel']}` · `{meta['plan_rel']}`. "
        f"Gap rule: > {gap} min. No file under `data/sealed/` is read.")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------- main
def build(repo: Path, git_log_file: Path | None, phase1: Path, phase2: Path,
          plan: Path, gap: int) -> tuple[str, dict]:
    if git_log_file:
        raw = git_log_file.read_text(encoding="utf-8")
        git_source = str(git_log_file)
    else:
        raw = run_git_log(repo)
        git_source = "git log --pretty=format:%aI%x1f%s (this repo, all commits)"

    git_sessions = sessionize(parse_git_log_text(raw), gap)
    for s in git_sessions:
        classify_session(s)

    gev, gstats = grading_events(phase1, phase2)
    grade_sessions = sessionize(gev, gap)

    rule, words = extract_clock_rule(plan)

    def rel(p: Path) -> str:
        """Repo-relative if possible, else parent-relative ('../x'), else absolute."""
        rp = p.resolve()
        try:
            return rp.relative_to(REPO).as_posix()
        except ValueError:
            pass
        try:
            return "../" + rp.relative_to(REPO.parent).as_posix()
        except ValueError:
            return rp.as_posix()

    meta = {
        "generated_ist": _dt.datetime.now(IST).strftime("%Y-%m-%d %H:%M"),
        "git_source": git_source,
        "phase1_rel": rel(phase1),
        "phase2_rel": rel(phase2),
        "plan_rel": rel(plan),
        "grading_overlap": total_overlap(git_sessions, grade_sessions),
    }
    md = render(git_sessions, grade_sessions, gstats, rule, words, gap, meta)
    return md, {"git_sessions": git_sessions, "grade_sessions": grade_sessions,
                "gstats": gstats, "rule": rule, "meta": meta}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=str(REPO))
    ap.add_argument("--git-log", default=None,
                    help="read commits from a file of '<iso>\\x1f<subject>' lines "
                         "(or '<iso>|<subject>') instead of running git")
    ap.add_argument("--phase1", default=str(REPO / "results" / "phase1_claims.jsonl"))
    ap.add_argument("--phase2", default=str(REPO / "results" / "phase2_grades.jsonl"))
    ap.add_argument("--plan",
                    default=str(REPO.parent / "neel-mats-12" /
                                "03-B13-EXECUTION-PLAN.md"))
    ap.add_argument("--gap-minutes", type=int, default=DEFAULT_GAP_MINUTES)
    ap.add_argument("--out", default=str(REPO / "writeup" / "HOURS_RECONSTRUCTION.md"))
    a = ap.parse_args()

    md, ctx = build(Path(a.repo), Path(a.git_log) if a.git_log else None,
                    Path(a.phase1), Path(a.phase2), Path(a.plan), a.gap_minutes)

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")

    # stdout receipt: the keyword table, so the inference is auditable without
    # opening the document.
    print("keyword table (ordered; first match wins)")
    for i, (cat, needles) in enumerate(CATEGORY_RULES, 1):
        print(f"  {i:2}. {cat:28} [{CLOCK_CLASS[cat]:9}] "
              f"{', '.join(n.strip() for n in needles)}")
    print(f"      {UNCATEGORIZED:28} [{CLOCK_CLASS[UNCATEGORIZED]:9}] "
          "(no needle matched)")

    gs, ds = ctx["git_sessions"], ctx["grade_sessions"]
    unc = [e["label"] for s in gs for e in s["events"]
           if e["category"] == UNCATEGORIZED]
    print(f"\ngit: {sum(s['n_events'] for s in gs)} commits in {len(gs)} sessions "
          f"(gap > {a.gap_minutes} min)")
    for k in ("COUNTED", "MIXED", "UNCOUNTED"):
        t = sum((s["span"] for s in gs if s["clock"] == k), _dt.timedelta(0))
        print(f"  {k:9} {hm(t):>8}  ({sum(1 for s in gs if s['clock'] == k)} sessions)")
    print(f"  uncategorized commits: {len(unc)}")
    for label in unc:
        print(f"    - {label[:90]}")
    gt = sum((s["span"] for s in ds), _dt.timedelta(0))
    print(f"grading: {sum(s['n_events'] for s in ds)} human save events in "
          f"{len(ds)} sessions, span {hm(gt)}")
    print(f"overlap with git sessions: {hm(ctx['meta']['grading_overlap'])}")
    print(f"\nwrote   {out}")
    print("\nThis document states NO hours total by design. The form figure is "
          "Ebin's to state (writeup/HOURS_LEDGER_TEMPLATE.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
