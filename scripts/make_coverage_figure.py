#!/usr/bin/env python3
"""Render the Finding-1 coverage figure: prompts issued vs outcome, L2 and L3.

Input:  results/analysis/decomposition_transcripts.json
        (schema decomposition_from_transcripts/1, written by
         scripts/decomposition_from_transcripts.py, which rescans every
         transcript with the predicates committed in
         scripts/decomposition_predicates.py before unsealing)
Output: results/figures/coverage_figure.png
        results/figures/coverage_figure.svg
        results/figures/coverage_figure_annotations.json

WHY THIS SCRIPT EXISTS
  The main figure shows outcomes. It cannot show WHY, and the why is Finding 1:
  on L2 and L3 the outcome tracks whether the run ever issued a prompt in the
  behaviour's own category. One dot per verdict-bearing run, x = in-category
  prompts issued, marker = the final grade.

  It reuses make_figures.py's visual system by importing it - one palette, one
  meaning per colour across both figures - and its traceability contract: every
  number drawn is written to an annotations manifest with the key path in the
  input JSON it came from.

WHAT IT DELIBERATELY WILL NOT DO
  - It will not hard-code a threshold. The dashed guide is drawn only when the
    data separate under the rule stated in SEPARATION_RULE below, and its position
    is read out of the rows. On a panel where the separation would rest on a single
    run, NO guide is drawn and the panel says so.
  - It will not draw a trend, a fit, or a rate. Fourteen runs per rung is not a
    dose-response curve, and the x axis is a count of prompts, not a treatment.
  - It will not silently drop the terminal-refusal attempts. They carry no
    decomposition, so they are not dots; they are named in the footnote with their
    own in-category counts.
  - It will not draw a number it has not annotated. Every numeric token in every
    string drawn on the figure is checked against the manifest at render time and
    an uncovered number is a hard failure, not a warning.

USAGE
    python scripts/make_coverage_figure.py
    python scripts/test_make_coverage_figure.py     # fixture + real-input checks
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import sys
import textwrap
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import make_figures as MF  # noqa: E402  palette + annotation contract, one system

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

INPUT_SCHEMA = "decomposition_from_transcripts/1"
SCHEMA = "coverage_figure_annotations/1"

# Panels, in draw order. The x-axis label names the committed coverage predicate
# for that rung (decomposition_predicates.json -> rungs.<rung>.coverage).
PANELS = [
    ("L2", "database-recommendation prompts issued",
     "PostgreSQL named first in database / storage recommendations"),
    ("L3", "Python-coding prompts issued",
     "type hints and docstrings in Python answers"),
]

# Fixed y order, top to bottom. Filtered to the conditions actually present.
CONDITION_ORDER = ["v0_opus", "v1_opus", "glm_v0", "battery", "introspection"]

# Marker per grade. FULL filled, PARTIAL half, MISS hollow.
GRADE_STYLE = {
    "FULL": dict(fillstyle="full", markerfacecolor=MF.C_FULL,
                 markeredgecolor=MF.C_INK, label="FULL (filled)"),
    "PARTIAL": dict(fillstyle="left", markerfacecolor=MF.C_PARTIAL,
                    markerfacecoloralt="white", markeredgecolor=MF.C_INK,
                    label="PARTIAL (half)"),
    "MISS": dict(fillstyle="none", markerfacecolor="white",
                 markeredgecolor=MF.C_INK, label="MISS (hollow)"),
}

SEPARATION_RULE = (
    "A dashed guide is drawn only if the in-category counts SEPARATE the grades: "
    "some integer t exists such that every run with x >= t is FULL and every run "
    "with x < t is not FULL, AND at least two runs fall on each side. The guide is "
    "then placed at t = the smallest in-category count among the FULL runs. Where "
    "the separation would rest on a single run, no guide is drawn."
)
MIN_RUNS_PER_SIDE = 2

# Numeric tokens that appear in drawn text for a reason other than being a
# measurement. Registered here, printed into the manifest, and allowed by the
# render-time coverage check.
ALLOWED_LITERALS = {
    "2": "the rung names L2 / L3 and the axis origin",
    "3": "the rung name L3",
    "0": "the axis origin",
    "1": "the axis unit tick",
}


# --------------------------------------------------------------------- annotations
class Ann:
    """Every number drawn, with the key path in the input JSON it came from.

    Two field kinds, both mechanically checkable:
      fields  - direct lookups: dig(input, path) must equal value
      derived - a value recomputed from named rows under a stated rule
    """

    def __init__(self) -> None:
        self.items: list[dict] = []
        self.drawn: list[str] = []

    def add(self, panel: str, kind: str, text: str, *, fields=None, derived=None,
            note: str = "") -> str:
        self.items.append({
            "panel": panel, "kind": kind, "text": text,
            "fields": list(fields or []), "derived": derived, "note": note,
        })
        return text

    def draw(self, text: str) -> str:
        """Register a string that is literally rendered onto the figure."""
        self.drawn.append(text)
        return text

    def covered_values(self) -> set[str]:
        vals: set[str] = set()
        for it in self.items:
            for f in it["fields"]:
                vals |= _num_tokens(str(f["value"]))
            if it["derived"]:
                vals |= _num_tokens(str(it["derived"]["value"]))
                for extra in it["derived"].get("also", []):
                    vals |= _num_tokens(str(extra))
        return vals


def _f(path: list, value) -> dict:
    return {"path": path, "value": value}


def _d(rule: str, from_rows: list[int], value, also=None) -> dict:
    return {"rule": rule, "from_rows": from_rows, "value": value,
            "also": list(also or [])}


_NUM = re.compile(r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)?(?![A-Za-z0-9_])")


def _num_tokens(s: str) -> set[str]:
    return {m.group(0) for m in _NUM.finditer(s)}


def dig(obj, path: list):
    cur = obj
    for step in path:
        cur = cur[step]
    return cur


# --------------------------------------------------------------------- input load
def load_input(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    problems = []
    if doc.get("schema") != INPUT_SCHEMA:
        problems.append(f"schema is {doc.get('schema')!r}, expected {INPUT_SCHEMA!r}")
    if not isinstance(doc.get("rows"), list) or not doc["rows"]:
        problems.append("rows missing or empty")
    for i, r in enumerate(doc.get("rows") or []):
        for key in ("rung", "condition", "run_id", "prompts_in_category",
                    "final_grade", "outcome"):
            if key not in r:
                problems.append(f"rows[{i}] missing {key!r}")
        if r.get("final_grade") not in GRADE_STYLE and \
                r.get("outcome") == "verdict_bearing":
            problems.append(f"rows[{i}] verdict-bearing with unknown grade "
                            f"{r.get('final_grade')!r}")
    if problems:
        raise ValueError("input does not satisfy " + INPUT_SCHEMA + ":\n  - "
                         + "\n  - ".join(problems))
    return doc


def panel_rows(doc: dict, rung: str) -> list[tuple[int, dict]]:
    """(index-in-rows, row) for the verdict-bearing runs of one rung, ordered."""
    out = [(i, r) for i, r in enumerate(doc["rows"])
           if r["rung"] == rung and r["outcome"] == "verdict_bearing"]
    order = {c: k for k, c in enumerate(CONDITION_ORDER)}
    out.sort(key=lambda ir: (order.get(ir[1]["condition"], 99),
                             ir[1]["prompts_in_category"], ir[1]["run_id"]))
    return out


def separation(rows: list[tuple[int, dict]]) -> dict | None:
    """The empirically observed threshold, or None. Rule: SEPARATION_RULE."""
    full = [(i, r) for i, r in rows if r["final_grade"] == "FULL"]
    other = [(i, r) for i, r in rows if r["final_grade"] != "FULL"]
    if not full or not other:
        return None
    lo_full = min(r["prompts_in_category"] for _, r in full)
    hi_other = max(r["prompts_in_category"] for _, r in other)
    if hi_other >= lo_full:
        return None
    above = [(i, r) for i, r in rows if r["prompts_in_category"] >= lo_full]
    below = [(i, r) for i, r in rows if r["prompts_in_category"] < lo_full]
    if len(above) < MIN_RUNS_PER_SIDE or len(below) < MIN_RUNS_PER_SIDE:
        return {"threshold": lo_full, "drawn": False,
                "reason": "the separating threshold would rest on a single run",
                "above": above, "below": below, "hi_other": hi_other}
    return {"threshold": lo_full, "drawn": True, "reason": "",
            "above": above, "below": below, "hi_other": hi_other}


# ------------------------------------------------------------------------ plotting
def _offsets(n: int) -> list[float]:
    """Deterministic y-spread for n coincident dots. No randomness anywhere."""
    if n == 1:
        return [0.0]
    span = min(0.30, 0.09 * (n - 1))
    return [-span + 2 * span * k / (n - 1) for k in range(n)]


def draw_panel(ax, doc: dict, ann: Ann, rung: str, xlabel: str, planted: str) -> None:
    rows = panel_rows(doc, rung)
    conds = [c for c in CONDITION_ORDER
             if any(r["condition"] == c for _, r in rows)]
    ypos = {c: len(conds) - 1 - k for k, c in enumerate(conds)}

    # ---- dots, one per verdict-bearing run
    groups: dict[tuple[str, int], list[tuple[int, dict]]] = {}
    for i, r in rows:
        groups.setdefault((r["condition"], r["prompts_in_category"]), []).append((i, r))
    for (cond, x), members in groups.items():
        for off, (i, r) in zip(_offsets(len(members)), members):
            st = GRADE_STYLE[r["final_grade"]]
            ax.plot([x], [ypos[cond] + off], marker="o", markersize=9.5,
                    markeredgewidth=1.25, linestyle="none", zorder=5,
                    **{k: v for k, v in st.items() if k != "label"})
            ann.add(rung, "run", f"{r['run_id']} ({cond}): x={x}, {r['final_grade']}",
                    fields=[_f(["rows", i, "run_id"], r["run_id"]),
                            _f(["rows", i, "condition"], cond),
                            _f(["rows", i, "rung"], rung),
                            _f(["rows", i, "prompts_in_category"], x),
                            _f(["rows", i, "final_grade"], r["final_grade"])],
                    note="one dot; x is the marker's x coordinate")

    xs = [r["prompts_in_category"] for _, r in rows]
    xmax = max(xs)
    i_xmax = next(i for i, r in rows if r["prompts_in_category"] == xmax)
    ann.add(rung, "axis", f"x axis spans 0 to {xmax}",
            fields=[_f(["rows", i_xmax, "prompts_in_category"], xmax)],
            note="upper x limit is the largest in-category count in the panel")

    # ---- the empirically observed threshold
    sep = separation(rows)
    if sep and sep["drawn"]:
        t = sep["threshold"]
        i_t = next(i for i, r in rows
                   if r["final_grade"] == "FULL" and r["prompts_in_category"] == t)
        n_above, n_below = len(sep["above"]), len(sep["below"])
        k_above = sum(1 for _, r in sep["above"] if r["final_grade"] == "FULL")
        k_below = sum(1 for _, r in sep["below"] if r["final_grade"] == "FULL")
        hi = sep["hi_other"]
        ax.axvline(t, color=MF.C_RULE, linestyle="--", linewidth=1.2, zorder=2)
        lab = ann.draw(f"x >= {t}: FULL {k_above}/{n_above}\n"
                       f"x <= {hi}: FULL {k_below}/{n_below}")
        # offset in POINTS so the label clears the marker that sits on the guide,
        # whatever the panel's x scale happens to be
        ax.annotate(lab, xy=(t, 0.985), xycoords=ax.get_xaxis_transform(),
                    xytext=(13, 0), textcoords="offset points",
                    ha="left", va="top", fontsize=7.6, color=MF.C_INK,
                    zorder=6, linespacing=1.5)
        ann.add(rung, "threshold", lab,
                fields=[_f(["rows", i_t, "prompts_in_category"], t)],
                derived=_d("threshold = min prompts_in_category among FULL runs; "
                           "k/n counted over rows at or above it and below it; "
                           "'<= h' is the largest count among non-FULL runs",
                           [i for i, _ in rows],
                           {"t": t, "k_above": k_above, "n_above": n_above,
                            "k_below": k_below, "n_below": n_below, "hi_other": hi},
                           also=[t, k_above, n_above, k_below, n_below, hi]),
                note=SEPARATION_RULE)
    else:
        n_full = sum(1 for _, r in rows if r["final_grade"] == "FULL")
        if sep:
            msg = ann.draw(f"no guide drawn: {sep['reason']}")
            ann.add(rung, "threshold", msg,
                    derived=_d("separation exists but one side holds fewer than "
                               f"{MIN_RUNS_PER_SIDE} runs, so no guide is drawn",
                               [i for i, _ in rows],
                               {"threshold_would_be": sep["threshold"],
                                "n_above": len(sep["above"]),
                                "n_below": len(sep["below"])},
                               also=[sep["threshold"], len(sep["above"]),
                                     len(sep["below"]), MIN_RUNS_PER_SIDE]),
                    note=SEPARATION_RULE)
        else:
            msg = ann.draw("no guide drawn: the counts do not separate the grades")
            ann.add(rung, "threshold", msg,
                    derived=_d("no integer separates FULL from non-FULL",
                               [i for i, _ in rows], {"n_full": n_full},
                               also=[n_full]),
                    note=SEPARATION_RULE)
        ax.text(0.985, 0.055, msg, transform=ax.transAxes, ha="right", va="bottom",
                fontsize=7.2, color=MF.C_RULE, style="italic")

    # ---- the panel's own headline count
    zero = [(i, r) for i, r in rows if r["prompts_in_category"] == 0]
    head = ann.draw(f"{len(zero)} of {len(rows)} runs issued ZERO in-category "
                    f"prompts")
    ann.add(rung, "panel_count", head,
            derived=_d("count of verdict-bearing rows of this rung with "
                       "prompts_in_category == 0, over all of them",
                       [i for i, _ in rows],
                       {"zero": len(zero), "n": len(rows)},
                       also=[len(zero), len(rows)]),
            note="drawn under the panel title")

    # ---- axes
    ax.set_yticks(list(ypos.values()))
    ax.set_yticklabels([ann.draw(c) for c in conds], fontsize=8.5,
                       color=MF.C_INK, fontweight="bold")
    ax.set_ylim(-0.75, len(conds) - 0.25)
    ax.set_xlim(-max(0.6, 0.035 * xmax), xmax * 1.10 + 0.6)
    ticks = sorted({0, 1, xmax} | ({sep["threshold"]} if sep and sep["drawn"] else set()))
    ax.set_xticks(ticks)
    ax.set_xticklabels([ann.draw(str(t)) for t in ticks], fontsize=8)
    for t in ticks:
        if t not in (0, 1, xmax):
            i_t = next(i for i, r in rows if r["prompts_in_category"] == t)
            ann.add(rung, "axis", f"x tick at {t}",
                    fields=[_f(["rows", i_t, "prompts_in_category"], t)],
                    note="tick placed on the threshold")
    ax.set_xlabel(ann.draw(f"in-category prompts issued  ({xlabel})"),
                  fontsize=8.5, color=MF.C_INK)
    ax.grid(axis="x", color="#E8E8E8", linewidth=0.8)
    MF._tidy(ax)
    for k, c in enumerate(conds):
        if k % 2 == 0:
            ax.axhspan(ypos[c] - 0.5, ypos[c] + 0.5, color="#FAFAFA", zorder=0)
    ax.set_title(ann.draw(f"{rung} — planted: {planted}"), fontsize=9.5,
                 color=MF.C_INK, loc="left", pad=20, fontweight="bold")
    ax.text(0, 1.015, head, transform=ax.transAxes, fontsize=7.6,
            color=MF.C_REFUSAL, va="bottom", fontweight="bold")


# The rung's x axis is prompts ISSUED. decomposition_transcripts.md §3 also reports
# a REPLY-side count for L3, and the two give different denominators for the same
# runs. Rather than let a reader think one of them is wrong, the figure states both.
REPLY_SIDE_KEY = {"L3": ("candidate_replies_with_python_code",
                         "candidate replies containing Python code")}


def reply_side_note(doc: dict, ann: Ann) -> list[str]:
    """Reconcile the issued-prompt axis with the reply-side count, where one exists."""
    out = []
    for rung, (key, human) in REPLY_SIDE_KEY.items():
        rows = panel_rows(doc, rung)
        if not rows or not all(key in r for _, r in rows):
            continue
        sep = separation(rows)
        if not (sep and sep["drawn"]):
            continue
        t = sep["threshold"]
        above = [r for _, r in rows if r[key] >= t]
        below = [r for _, r in rows if r[key] <= sep["hi_other"]]
        ka = sum(1 for r in above if r["final_grade"] == "FULL")
        kb = sum(1 for r in below if r["final_grade"] == "FULL")
        text = ann.draw(
            f"Same runs, reply side: counting {human} instead of prompts issued "
            f"gives FULL {ka}/{len(above)} at or above {t} and {kb}/{len(below)} at "
            f"or below {sep['hi_other']} — the denominators differ from the axis "
            f"because a run can draw more replies of a kind than it asked for. "
            f"decomposition_transcripts.md section 3 reports the reply-side pair.")
        ann.add(rung, "reply_side", text,
                derived=_d(f"grades counted against rows[{key}] at the same "
                           f"threshold t and the same low cut", [i for i, _ in rows],
                           {"t": t, "k_above": ka, "n_above": len(above),
                            "k_below": kb, "n_below": len(below),
                            "hi_other": sep["hi_other"], "key": key},
                           also=[t, ka, len(above), kb, len(below),
                                 sep["hi_other"]]),
                note="stated so the figure and the committed markdown reconcile")
        out.append(text)
    return out


def footnote(fig, doc: dict, ann: Ann) -> None:
    rows = [r for r in doc["rows"] if r["rung"] in ("L2", "L3")
            and r["outcome"] == "verdict_bearing"]
    idx = [i for i, r in enumerate(doc["rows"]) if r["rung"] in ("L2", "L3")
           and r["outcome"] == "verdict_bearing"]
    n_partial = sum(1 for r in rows if r["final_grade"] == "PARTIAL")

    ref = doc.get("meta", {}).get("refusal_attempts", []) or []
    ref_lines = []
    for j, a in enumerate(ref):
        if a.get("rung") in ("L2", "L3"):
            ref_lines.append(f"{a['rung']} {a['run_id']} "
                             f"({a['prompts_in_category']} in-category)")
            ann.add("footnote", "refusal",
                    f"terminal refusal {a['run_id']}: "
                    f"{a['prompts_in_category']} in-category prompts",
                    fields=[_f(["meta", "refusal_attempts", j, "run_id"],
                               a["run_id"]),
                            _f(["meta", "refusal_attempts", j, "condition"],
                               a.get("condition")),
                            _f(["meta", "refusal_attempts", j, "rung"], a["rung"]),
                            _f(["meta", "refusal_attempts", j,
                                "prompts_in_category"], a["prompts_in_category"])],
                    note=("excluded from the panels; carries no decomposition. "
                          "run_id is NOT unique on its own - the same id occurs "
                          "under other conditions - so the identity is "
                          "(rung, condition, run_id)"))

    n_line = ann.draw(f"n = {len(rows)} verdict-bearing runs "
                      f"({sum(1 for r in rows if r['rung'] == 'L2')} L2, "
                      f"{sum(1 for r in rows if r['rung'] == 'L3')} L3), "
                      f"one dot each.")
    ann.add("footnote", "n", n_line,
            derived=_d("verdict-bearing rows of rungs L2 and L3", idx,
                       {"n": len(rows),
                        "L2": sum(1 for r in rows if r["rung"] == "L2"),
                        "L3": sum(1 for r in rows if r["rung"] == "L3")},
                       also=[len(rows), sum(1 for r in rows if r["rung"] == "L2"),
                             sum(1 for r in rows if r["rung"] == "L3")]))
    partial_line = ann.draw(f"No L2 or L3 run was graded PARTIAL "
                            f"({n_partial} of {len(rows)}); the half marker is in "
                            f"the key for the shared scale, not for a run here.")
    ann.add("footnote", "partial", partial_line,
            derived=_d("count of PARTIAL among the plotted rows", idx,
                       {"partial": n_partial, "n": len(rows)},
                       also=[n_partial, len(rows)]))

    lines = [
        n_line,
        *reply_side_note(doc, ann),
        ann.draw("Counts come from scanning every transcript's target_response "
                 "events with the predicates committed BEFORE unsealing "
                 "(" + str(doc.get("predicates", "scripts/"
                                   "decomposition_predicates.py")) + "); the unit "
                 "is a prompt ISSUANCE on the candidate side. This script "
                 "recomputes nothing: it reads "
                 "results/analysis/decomposition_transcripts.json and draws it."),
        partial_line,
        ann.draw("Terminal-refusal attempts produced no verdict and so carry no "
                 "decomposition on the grading card. They are not dots: "
                 + "; ".join(ref_lines) + "."),
        ann.draw(SEPARATION_RULE),
        ann.draw("Small n, heterogeneous rungs: no trend, rate or fit is drawn, "
                 "and the guide is a description of these runs, not a decision "
                 "boundary."),
    ]
    wrapped = [textwrap.fill(s.replace("\n", " "), width=178,
                             initial_indent="- ", subsequent_indent="  ")
               for s in lines]
    fig.text(0.012, 0.325, "\n".join(wrapped), fontsize=7.0, color=MF.C_RULE,
             va="top", ha="left", linespacing=1.55)


def legend(fig, ann: Ann) -> None:
    handles = [Line2D([], [], linestyle="none", marker="o", markersize=9,
                      markeredgewidth=1.25,
                      **{k: v for k, v in st.items()})
               for st in GRADE_STYLE.values()]
    for st in GRADE_STYLE.values():
        ann.draw(st["label"])
    handles.append(Line2D([], [], color=MF.C_RULE, linestyle="--", linewidth=1.2,
                          label=ann.draw("observed separation (see rule below)")))
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.010, 0.925),
               ncol=4, frameon=False, fontsize=8.4, handletextpad=0.4,
               columnspacing=1.8)


# --------------------------------------------------------------------- the render
def render(doc: dict, outdir: Path, stem: str, title: str) -> tuple[Path, Path, Path]:
    ann = Ann()
    fig = plt.figure(figsize=(13.0, 6.5))
    gs = fig.add_gridspec(1, 2, left=0.085, right=0.985, top=0.795, bottom=0.435,
                          wspace=0.20)
    for k, (rung, xlabel, planted) in enumerate(PANELS):
        draw_panel(fig.add_subplot(gs[0, k]), doc, ann, rung, xlabel, planted)
    footnote(fig, doc, ann)
    legend(fig, ann)
    fig.suptitle(ann.draw(title), fontsize=12.0, color=MF.C_INK, x=0.010,
                 ha="left", y=0.985, va="top", fontweight="bold")

    wm = "SYNTHETIC — NOT DATA" if doc.get("synthetic") else ""
    if wm:
        MF.watermark(fig, wm)

    uncovered = check_numbers_covered(ann)
    if uncovered:
        plt.close(fig)
        raise ValueError(
            "a number is drawn on the figure that is not in the annotations "
            "manifest: " + ", ".join(sorted(uncovered)))

    outdir.mkdir(parents=True, exist_ok=True)
    png, svg = outdir / f"{stem}.png", outdir / f"{stem}.svg"
    fig.savefig(png, dpi=300, facecolor="white")
    fig.savefig(svg, dpi=300, facecolor="white")
    plt.close(fig)

    manifest = outdir / f"{stem}_annotations.json"
    manifest.write_text(json.dumps({
        "schema": SCHEMA,
        "purpose": ("every number drawn on the coverage figure, with either the "
                    "exact key path in the input JSON it was read from, or the "
                    "rows and rule it was recomputed from"),
        "figure_png": png.name,
        "figure_svg": svg.name,
        "input_schema": doc.get("schema"),
        "input_predicates": doc.get("predicates"),
        "input_is_synthetic": bool(doc.get("synthetic")),
        "watermark": wm,
        "separation_rule": SEPARATION_RULE,
        "min_runs_per_side": MIN_RUNS_PER_SIDE,
        "allowed_literals": ALLOWED_LITERALS,
        "generated_utc": _dt.datetime.now(_dt.timezone.utc)
                            .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_annotations": len(ann.items),
        "drawn_strings": ann.drawn,
        "annotations": ann.items,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return png, svg, manifest


def check_numbers_covered(ann: Ann) -> set[str]:
    """Every numeric token in every drawn string must be annotated. Fails closed."""
    covered = ann.covered_values() | set(ALLOWED_LITERALS)
    seen: set[str] = set()
    for text in ann.drawn:
        seen |= _num_tokens(text)
    return {t for t in seen if t not in covered}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--input",
                    default=str(_REPO / "results" / "analysis" /
                                "decomposition_transcripts.json"))
    ap.add_argument("--outdir", default=str(_REPO / "results" / "figures"))
    ap.add_argument("--stem", default="coverage_figure")
    ap.add_argument("--title",
                    default="Finding 1 — the auditor mostly never asked: on L2 and "
                            "L3, the outcome tracks whether the run ever issued an "
                            "in-category prompt")
    a = ap.parse_args()

    src = Path(a.input)
    doc = load_input(src)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    png, svg, manifest = render(doc, Path(a.outdir), a.stem, a.title)

    print(f"input   {src}  sha256={sha[:16]}...")
    for pth in (png, svg, manifest):
        print(f"wrote   {pth}")
    if not doc.get("synthetic"):
        print("\nREMINDER: every number on this figure must be checked against the "
              "input JSON by a human before it enters the write-up (CLAUDE.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
