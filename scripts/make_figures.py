#!/usr/bin/env python3
"""Render the two-panel main figure from the analysis instrument's own numbers.

Spec: writeup/FIGURE_SPEC.md. Estimands: PREREGISTRATION.md Amendment 6 clarification 2.
Uncertainty rule: Amendment 6 clarification 3 - every displayed binomial rate carries
k/n and a two-sided 95% Wilson interval.

WHY THIS SCRIPT EXISTS
  Addendum to Amendment 3, part E: "headline numbers are never hand-assembled."
  After unsealing, ONE command regenerates the real figure. This script does no
  statistics of its own: every rate and interval it draws is read out of the input
  JSON, and every Wilson interval is RE-COMPUTED with analysis_instrument.wilson()
  and compared against the input before anything is drawn. A mismatch is a hard
  failure, not a warning - a figure whose intervals disagree with the instrument
  would be the exact failure mode the addendum exists to prevent.

INPUT CONTRACT - schema "analysis_figure_input/1"
  The blocks below are the VERBATIM return values of the estimand functions in
  scripts/analysis_instrument.py. Nothing is reshaped, renamed or recomputed.

  {
    "schema": "analysis_figure_input/1",
    "synthetic": false,                  # true => watermark is forced on
    "generated_utc": "...",
    "provenance": {...},                 # free-form; echoed into the manifest
    "conditions":       ["agent v0", "agent v1", "Baseline 1 - fixed battery", ...],
    "designed_rungs":   ["L1", "L2", "L3"],
    "exploratory_rungs":["L4v3"],
    "detection": { condition: { rung: <analysis_instrument.detection_rates(...)> } },
    "null":      { condition: <analysis_instrument.l0_false_positive_rates(...)> },
    "null_subset": { condition: <same shape> },        # OPTIONAL, e.g. frozen n=10
    "null_subset_label": "seeds 0-9 (frozen n=10)",    # OPTIONAL
    "cost":      { condition: <analysis_instrument.dollars_per_detection(...)> },
    "single_decision_conditions": ["Baseline 1 - fixed battery", ...]   # OPTIONAL
  }

  `single_decision_conditions` marks conditions whose bar is ONE pair-level decision
  rather than seed-paired trials (r4 section 8). Their bars get no error bar, because
  an interval there would imply replication that does not exist. If the field is
  absent, any cell with n_planned_attempts == 1 is treated that way.

WHAT THIS SCRIPT DELIBERATELY WILL NOT DO
  - It will not invent a segment. If FULL+PARTIAL+MISS+refusals < planned attempts,
    the remainder is drawn as an explicit "UNGRADED / OTHER NO-VERDICT" segment and
    named in the caption. It is never silently absorbed into MISS.
  - It will not plot a trend line over L1-L3. They are heterogeneous designed
    conditions, not doses (r4 section 5, "claims to demote").
  - It will not put the exploratory rung in the main panel (Amendment 4 item 2).
  - It will not rank conditions by dollars when any component is unpriced.

USAGE
    python scripts/make_figures.py --input results/figures/figure_input.json
    python scripts/test_make_figures.py          # synthetic end-to-end proof

OUTPUTS (all under --outdir, default results/figures/)
    <stem>.png                  300 dpi
    <stem>.svg                  vector
    <stem>_annotations.json     every number drawn on the figure, with the exact
                                key path in the input JSON it came from
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import analysis_instrument as AI  # noqa: E402  single source of truth for wilson/fmt

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

SCHEMA = "analysis_figure_input/1"

# ------------------------------------------------------------------ visual system
# Okabe-Ito colourblind-safe palette. One meaning per colour, held across both
# panels: bluish green is always "the outcome we wanted", vermillion + hatch is
# always "the auditor did not finish". Refusal carries a hatch as well as a hue so
# it survives greyscale printing and is never confused with MISS.
C_FULL = "#009E73"   # bluish green
C_PARTIAL = "#56B4E9"   # sky blue
C_MISS = "#CFCFCF"   # neutral grey
C_REFUSAL = "#D55E00"   # vermillion
C_OTHER = "#FFFFFF"   # white + cross-hatch: present but unclassified
C_FP = "#CC79A7"   # reddish purple
C_CORRECT = C_FULL      # the good outcome, same hue as FULL by design
C_INK = "#1A1A1A"
C_RULE = "#8A8A8A"

HATCH_REFUSAL = "//"
HATCH_OTHER = "xx"

SEG_A = [
    ("FULL", C_FULL, None),
    ("PARTIAL", C_PARTIAL, None),
    ("MISS", C_MISS, None),
    ("REFUSAL / NO VERDICT", C_REFUSAL, HATCH_REFUSAL),
    ("UNGRADED / OTHER NO-VERDICT", C_OTHER, HATCH_OTHER),
]
SEG_B = [
    ("FALSE POSITIVE", C_FP, None),
    ("CORRECT REJECTION", C_CORRECT, None),
    ("REFUSAL / NO VERDICT", C_REFUSAL, HATCH_REFUSAL),
    ("UNGRADED / OTHER NO-VERDICT", C_OTHER, HATCH_OTHER),
]

WILSON_KEYS = (
    "refusal_rate",
    "full_all_attempts_PRIMARY",
    "full_plus_partial_all_attempts",
    "full_verdict_bearing",
    "full_plus_partial_verdict_bearing",
    "fp_frozen_rule_verdict_bearing_PRIMARY",
    "fp_strict_rule_verdict_bearing",
    "fp_frozen_rule_all_attempts",
)


# --------------------------------------------------------------------- annotations
class Annotations:
    """Every number drawn on the figure, with its key path in the input JSON.

    This is what makes "traceable to the input JSON" a testable property rather
    than a claim: scripts/test_make_figures.py walks each path and asserts the
    value matches.
    """

    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, panel: str, kind: str, text: str, fields: list[dict],
            note: str = "") -> str:
        self.items.append({"panel": panel, "kind": kind, "text": text,
                           "fields": fields, "note": note})
        return text


def _f(path: list, value) -> dict:
    return {"path": path, "value": value}


def dig(obj, path: list):
    for key in path:
        obj = obj[key]
    return obj


# ------------------------------------------------------------------- input loading
def _grade_count(grade_counts: dict, label: str) -> int:
    return int(grade_counts.get(label, 0) or 0)


def validate(doc: dict) -> list[str]:
    """Structural + arithmetic validation. Returns a list of problems (empty == ok).

    Fails closed. A figure is a claim; a figure built from a half-shaped input is a
    claim nobody checked.
    """
    p: list[str] = []
    if doc.get("schema") != SCHEMA:
        p.append(f"schema must be {SCHEMA!r}, got {doc.get('schema')!r}")
    for key in ("conditions", "designed_rungs", "detection", "null", "cost"):
        if key not in doc:
            p.append(f"missing required top-level key {key!r}")
    if p:
        return p

    conditions = doc["conditions"]
    rungs = list(doc["designed_rungs"]) + list(doc.get("exploratory_rungs", []))

    def check_wilson(block: dict, where: list) -> None:
        for wk in WILSON_KEYS:
            w = block.get(wk)
            if not isinstance(w, dict) or "k" not in w or "n" not in w:
                continue
            if w.get("rate") is None:
                continue
            ref = AI.wilson(w["k"], w["n"])
            for field in ("rate", "lo", "hi"):
                got, exp = w.get(field), ref.get(field)
                if exp is None:
                    continue
                if got is None or abs(float(got) - float(exp)) > 1e-6:
                    p.append(
                        f"{'.'.join(map(str, where + [wk, field]))}: input says {got}, "
                        f"analysis_instrument.wilson({w['k']},{w['n']}) says {exp}")

    for cond in conditions:
        det = doc["detection"].get(cond, {})
        for rung in rungs:
            cell = det.get(rung)
            if cell is None:
                continue  # legitimately not run; rendered as an explicit gap
            for key in ("n_planned_attempts", "n_verdict_bearing",
                        "n_terminal_refusal", "full_all_attempts_PRIMARY",
                        "grade_counts"):
                if key not in cell:
                    p.append(f"detection[{cond!r}][{rung!r}] missing {key!r}")
            if p:
                continue
            n = cell["n_planned_attempts"]
            gc = cell["grade_counts"]
            used = (_grade_count(gc, "FULL") + _grade_count(gc, "PARTIAL")
                    + _grade_count(gc, "MISS") + cell["n_terminal_refusal"])
            if used > n:
                p.append(f"detection[{cond!r}][{rung!r}]: graded+refused ({used}) "
                         f"exceeds planned attempts ({n})")
            if cell["full_all_attempts_PRIMARY"].get("n") != n:
                p.append(f"detection[{cond!r}][{rung!r}]: FULL interval denominator "
                         f"{cell['full_all_attempts_PRIMARY'].get('n')} != "
                         f"n_planned_attempts {n} (primary is ALL attempts)")
            if _grade_count(gc, "FULL") != cell["full_all_attempts_PRIMARY"].get("k"):
                p.append(f"detection[{cond!r}][{rung!r}]: grade_counts FULL "
                         f"{_grade_count(gc, 'FULL')} != interval k "
                         f"{cell['full_all_attempts_PRIMARY'].get('k')}")
            check_wilson(cell, ["detection", cond, rung])

    for block_name in ("null", "null_subset"):
        for cond, cell in (doc.get(block_name) or {}).items():
            for key in ("n_planned_attempts", "n_verdict_bearing",
                        "n_terminal_refusal",
                        "fp_frozen_rule_verdict_bearing_PRIMARY"):
                if key not in cell:
                    p.append(f"{block_name}[{cond!r}] missing {key!r}")
            if p:
                continue
            fp = cell["fp_frozen_rule_verdict_bearing_PRIMARY"]
            if fp.get("n") != cell["n_verdict_bearing"]:
                p.append(f"{block_name}[{cond!r}]: primary FPR denominator "
                         f"{fp.get('n')} != n_verdict_bearing "
                         f"{cell['n_verdict_bearing']} (primary is VERDICT-BEARING)")
            if (fp.get("k") or 0) > cell["n_verdict_bearing"]:
                p.append(f"{block_name}[{cond!r}]: FP count exceeds verdict-bearing n")
            if cell["n_verdict_bearing"] + cell["n_terminal_refusal"] > \
                    cell["n_planned_attempts"]:
                p.append(f"{block_name}[{cond!r}]: verdict-bearing + refusals exceed "
                         f"planned attempts")
            check_wilson(cell, [block_name, cond])

    for cond, cell in doc["cost"].items():
        if "primary" not in cell:
            p.append(f"cost[{cond!r}] missing 'primary'")
        if "eligible_for_dollar_ranking" not in cell:
            p.append(f"cost[{cond!r}] missing 'eligible_for_dollar_ranking'")
    return p


def load_input(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    problems = validate(doc)
    if problems:
        raise ValueError(
            "input does not satisfy " + SCHEMA + ":\n  - " + "\n  - ".join(problems))
    return doc


# ------------------------------------------------------------------------ plotting
def _stack(ax, x, width, counts: list[int], n: int, segments) -> None:
    """One stacked bar, as PROPORTION of planned attempts. Sums to <= 1.0."""
    bottom = 0.0
    for (label, colour, hatch), c in zip(segments, counts):
        if c <= 0:
            continue
        h = c / n
        ax.bar(x, h, width=width, bottom=bottom, color=colour, hatch=hatch,
               edgecolor=C_INK if colour == C_OTHER else "white",
               linewidth=0.7, zorder=3)
        bottom += h


def _tidy(ax) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(C_RULE)
    ax.spines["bottom"].set_color(C_RULE)
    ax.tick_params(colors=C_INK, labelsize=8)
    ax.set_axisbelow(True)


def _is_single_decision(doc: dict, cond: str, n: int) -> bool:
    marked = doc.get("single_decision_conditions")
    if marked is not None:
        return cond in marked
    return n == 1


def panel_a(ax, doc: dict, ann: Annotations, rungs: list[str], *,
            exploratory: bool = False) -> None:
    conditions = [c for c in doc["conditions"]
                  if any(doc["detection"].get(c, {}).get(r) for r in rungs)]
    if not conditions or not rungs:
        ax.axis("off")
        ax.text(0.5, 0.5, "no cells for this panel", ha="center", va="center",
                fontsize=8, color=C_RULE)
        return

    panel = "A-exploratory" if exploratory else "A"
    ncond = len(conditions)
    group_w = 0.82
    bar_w = group_w / ncond

    for gi, rung in enumerate(rungs):
        for ci, cond in enumerate(conditions):
            cell = doc["detection"].get(cond, {}).get(rung)
            x = gi + (ci - (ncond - 1) / 2) * bar_w
            if cell is None:
                ax.text(x, 0.02, "not run", rotation=90, ha="center", va="bottom",
                        fontsize=6.5, color=C_RULE)
                continue
            n = cell["n_planned_attempts"]
            gc = cell["grade_counts"]
            k_full = _grade_count(gc, "FULL")
            k_part = _grade_count(gc, "PARTIAL")
            k_miss = _grade_count(gc, "MISS")
            k_ref = cell["n_terminal_refusal"]
            k_other = n - (k_full + k_part + k_miss + k_ref)
            _stack(ax, x, bar_w * 0.88, [k_full, k_part, k_miss, k_ref, k_other],
                   n, SEG_A)

            w = cell["full_all_attempts_PRIMARY"]
            base = ["detection", cond, rung]
            kn = ann.add(panel, "full_k_over_n", f"{w['k']}/{w['n']}",
                         [_f(base + ["full_all_attempts_PRIMARY", "k"], w["k"]),
                          _f(base + ["full_all_attempts_PRIMARY", "n"], w["n"])],
                         note="FULL among ALL planned attempts (primary estimand)")
            single = _is_single_decision(doc, cond, n)
            top = w["rate"] if w["rate"] is not None else 0.0
            if not single and w["rate"] is not None:
                lo, hi = w["lo"], w["hi"]
                ax.errorbar(x, w["rate"], yerr=[[w["rate"] - lo], [hi - w["rate"]]],
                            fmt="none", ecolor=C_INK, elinewidth=1.1, capsize=2.6,
                            zorder=5)
                ann.add(panel, "full_wilson_95",
                        f"[{lo * 100:.1f}-{hi * 100:.1f}%]",
                        [_f(base + ["full_all_attempts_PRIMARY", "lo"], lo),
                         _f(base + ["full_all_attempts_PRIMARY", "hi"], hi)],
                        note="two-sided 95% Wilson, recomputed and matched against "
                             "analysis_instrument.wilson")
                top = max(top, hi)
            else:
                ann.add(panel, "single_decision_no_interval", "n=1 pair-level decision",
                        [_f(base + ["n_planned_attempts"], n)],
                        note="one pair-level decision, not seed-paired trials - no "
                             "interval drawn, because it would imply replication")
            ax.text(x, min(top + 0.035, 1.0), kn, ha="center", va="bottom",
                    fontsize=6.8, color=C_INK, zorder=6)

            vb = cell["n_verdict_bearing"]
            ann.add(panel, "verdict_bearing_n", f"vb {vb}/{n}",
                    [_f(base + ["n_verdict_bearing"], vb),
                     _f(base + ["n_planned_attempts"], n)],
                    note="Amendment 6 clarification 3: per-rung verdict-bearing n is "
                         "annotated so a refusal-thinned cell is not read as subtlety")
            ax.text(x, -0.055, f"vb {vb}/{n}", ha="center", va="top",
                    fontsize=5.9, color=C_RULE, rotation=90)

    ax.set_xticks(range(len(rungs)))
    ax.set_xticklabels(rungs, fontsize=9.5, color=C_INK, fontweight="bold")
    # the per-bar "vb k/n" annotations hang below the axis, so the rung label is
    # padded clear of them rather than drawn on top of them
    ax.tick_params(axis="x", pad=36, length=0)
    ax.set_ylim(0, 1.14)
    ax.set_yticks([0, .25, .5, .75, 1.0])
    ax.set_yticklabels(["0", "25%", "50%", "75%", "100%"])
    ax.set_xlim(-0.6, len(rungs) - 0.4)
    ax.grid(axis="y", color="#EDEDED", linewidth=0.7, zorder=0)
    _tidy(ax)

    if exploratory:
        ax.set_title("EXPLORATORY - excluded from every headline metric",
                     fontsize=7.5, color=C_REFUSAL, pad=14, fontweight="bold")
        for side in ("top", "right", "left", "bottom"):
            ax.spines[side].set_visible(True)
            ax.spines[side].set_color(C_REFUSAL)
            ax.spines[side].set_linewidth(1.1)
            ax.spines[side].set_linestyle((0, (4, 3)))
    else:
        ax.set_ylabel("share of planned seeded attempts", fontsize=8.5, color=C_INK)
        ax.set_title("A - End-to-end outcomes across designed rungs",
                     fontsize=11, color=C_INK, loc="left", pad=22, fontweight="bold")
        ax.text(0, 1.025, "bar = one condition; stack = every planned attempt. "
                          "Designed rungs, not a subtlety dose - no trend fitted.",
                transform=ax.transAxes, fontsize=7.4, color=C_RULE, va="bottom")
        ax.legend(handles=[Patch(facecolor=c, hatch=h,
                                 edgecolor=C_INK if c == C_OTHER else "white",
                                 label=lab) for lab, c, h in SEG_A],
                  loc="upper left", bbox_to_anchor=(0.0, -0.24), ncol=3,
                  fontsize=7, frameon=False, handlelength=1.5)
        cond_lab = "   ".join(f"{i + 1}. {c}" for i, c in enumerate(conditions))
        ax.text(0, -0.40, f"bars left to right within each rung:   {cond_lab}",
                transform=ax.transAxes, fontsize=7.2, color=C_INK, va="top")


def panel_b_null(ax, doc: dict, ann: Annotations) -> None:
    null = doc["null"]
    subset = doc.get("null_subset") or {}
    sub_label = doc.get("null_subset_label", "pre-Amendment-7 subset")
    conditions = [c for c in doc["conditions"] if c in null]
    if not conditions:
        ax.axis("off")
        return

    has_sub = any(c in subset for c in conditions)
    main_w, sub_w = (0.42, 0.24) if has_sub else (0.55, 0.0)

    for i, cond in enumerate(conditions):
        for cell, xoff, width, tag, block in (
                (null[cond], -sub_w / 2 if has_sub else 0.0, main_w, "primary", "null"),
                (subset.get(cond), (main_w / 2 + 0.03) if has_sub else None,
                 sub_w, "subset", "null_subset")):
            if cell is None or width in (None, 0.0) or xoff is None:
                continue
            n = cell["n_planned_attempts"]
            fp = cell["fp_frozen_rule_verdict_bearing_PRIMARY"]
            k_fp = int(fp.get("k") or 0)
            k_ref = cell["n_terminal_refusal"]
            k_ok = cell["n_verdict_bearing"] - k_fp
            k_other = n - (k_fp + k_ok + k_ref)
            _stack(ax, i + xoff, width, [k_fp, k_ok, k_ref, k_other], n, SEG_B)
            base = [block, cond]
            if tag == "primary":
                # a single pair-level decision gets k/n and NO interval, for the same
                # reason as Panel A: an interval there would imply replication
                single = _is_single_decision(doc, cond, n)
                keys = ("k", "n") if single else ("k", "n", "rate", "lo", "hi")
                shown = (f"{fp['k']}/{fp['n']}  (one pair-level decision)" if single
                         else AI.fmt_rate(fp))
                txt = ann.add("B-null", "fpr_primary_verdict_bearing", shown,
                              [_f(base + ["fp_frozen_rule_verdict_bearing_PRIMARY", key],
                                  fp.get(key)) for key in keys],
                              note="PRIMARY L0 estimand: frozen-rule FP among "
                                   "VERDICT-BEARING runs (Amendment 6 clar. 2)"
                                   + ("; no interval drawn for a pair-level decision"
                                      if single else ""))
                ax.text(i, 1.29, txt, ha="center", va="bottom", fontsize=7.6,
                        color=C_INK, fontweight="bold")
                strict = cell.get("fp_strict_rule_verdict_bearing")
                if isinstance(strict, dict) and strict.get("rate") is not None:
                    s_shown = (f"{strict['k']}/{strict['n']}" if single
                               else AI.fmt_rate(strict))
                    stxt = ann.add("B-null", "fpr_strict_rule", s_shown,
                                   [_f(base + ["fp_strict_rule_verdict_bearing", key],
                                       strict.get(key)) for key in keys],
                                   note="strict-rule sensitivity: every `diff` verdict "
                                        "counts as FP (Amendment 3 item 4)")
                    ax.text(i, 1.19, "strict rule  " + stxt, ha="center", va="bottom",
                            fontsize=6.4, color=C_RULE)
                ann.add("B-null", "refusal_count", f"{k_ref} refusals of {n}",
                        [_f(base + ["n_terminal_refusal"], k_ref),
                         _f(base + ["n_planned_attempts"], n)])
            else:
                # short form, rotated above its own narrow bar, so it cannot collide
                # with the primary rate printed over the group
                short = f"subset {fp['k']}/{fp['n']} = {fp['rate'] * 100:.1f}%"
                stxt = ann.add("B-null", "fpr_subset", short,
                               [_f(base + ["fp_frozen_rule_verdict_bearing_PRIMARY", key],
                                   fp.get(key)) for key in ("k", "n", "rate")],
                               note=f"{sub_label}: shown so a reader can verify the "
                                    f"estimate did not move when seeds were added "
                                    f"(Amendment 7). Full interval: {AI.fmt_rate(fp)}")
                ax.text(i + xoff, 1.08, stxt, ha="center", va="bottom",
                        fontsize=5.8, color=C_RULE)

    ax.set_xticks(range(len(conditions)))
    ax.set_xticklabels(conditions, fontsize=7.8, color=C_INK, fontweight="bold")
    ax.tick_params(axis="x", pad=7, length=0)
    ax.set_ylim(0, 1.42)
    ax.set_yticks([0, .5, 1.0])
    ax.set_yticklabels(["0", "50%", "100%"])
    ax.set_xlim(-0.65, len(conditions) - 0.35)
    ax.grid(axis="y", color="#EDEDED", linewidth=0.7, zorder=0)
    _tidy(ax)
    ax.set_ylabel("share of planned L0 attempts", fontsize=8.5, color=C_INK)
    ax.set_title("B - The null (L0): confabulation, correct rejection, non-completion",
                 fontsize=11, color=C_INK, loc="left", pad=30, fontweight="bold")
    note = ("bold rate = PRIMARY frozen-rule FPR among verdict-bearing runs; "
            "strict-rule sensitivity beneath it")
    if has_sub:
        note += f"; narrow bar = {sub_label}"
    ax.text(0, 1.02, note, transform=ax.transAxes, fontsize=7.2, color=C_RULE,
            va="bottom")
    ax.legend(handles=[Patch(facecolor=c, hatch=h,
                             edgecolor=C_INK if c == C_OTHER else "white", label=lab)
                       for lab, c, h in SEG_B],
              loc="upper left", bbox_to_anchor=(0.0, -0.14), ncol=2, fontsize=7,
              frameon=False, handlelength=1.5)


def panel_b_cost(ax, doc: dict, ann: Annotations) -> None:
    ax.axis("off")
    ax.set_title("Cost of operating the auditor", fontsize=9, color=C_INK,
                 loc="left", pad=8, fontweight="bold")
    ax.text(0, 0.955, "primary = complete recorded spend over ALL planned attempts\n"
                      "divided by FULL detections (an audit pays for its refusals)",
            fontsize=6.9, color=C_RULE, va="top", transform=ax.transAxes)

    y = 0.845
    any_unpriced = False
    for cond in doc["conditions"]:
        cell = doc["cost"].get(cond)
        if cell is None:
            continue
        base = ["cost", cond]
        ax.text(0, y, cond, fontsize=7.8, color=C_INK, fontweight="bold",
                transform=ax.transAxes, va="top")
        y -= 0.052
        if not cell.get("eligible_for_dollar_ranking", True):
            any_unpriced = True
            txt = ann.add("B-cost", "cost_unpriced",
                          "excluded from dollar ranking (unpriced component)",
                          [_f(base + ["eligible_for_dollar_ranking"],
                              cell.get("eligible_for_dollar_ranking")),
                           _f(base + ["unpriced_component"],
                              cell.get("unpriced_component"))],
                          note="Section 4 cost-null-not-zero rule")
            ax.text(0.03, y, txt, fontsize=7.0, color=C_REFUSAL,
                    transform=ax.transAxes, va="top")
            y -= 0.075
            continue
        primary = cell["primary"]
        if isinstance(primary, str):
            txt = ann.add("B-cost", "cost_undefined", primary,
                          [_f(base + ["primary"], primary)],
                          note="zero FULL detections: reported as `undefined` with the "
                               "spend, never as infinity and never dropped")
            ax.text(0.03, y, txt, fontsize=7.2, color=C_INK,
                    transform=ax.transAxes, va="top")
        else:
            txt = ann.add("B-cost", "cost_per_full", f"${primary:,.4f} per FULL detection",
                          [_f(base + ["primary"], primary)],
                          note="primary dollars-per-detection (Amendment 6 clar. 2)")
            ax.text(0.03, y, txt, fontsize=8.4, color=C_INK, fontweight="bold",
                    transform=ax.transAxes, va="top")
        y -= 0.05
        spend = cell.get("total_spend_all_attempts_usd")
        nfull = cell.get("n_full_detections")
        if spend is not None and nfull is not None:
            sub = ann.add("B-cost", "cost_inputs",
                          f"spend ${spend:,.4f}  /  {nfull} FULL",
                          [_f(base + ["total_spend_all_attempts_usd"], spend),
                           _f(base + ["n_full_detections"], nfull)],
                          note="numerator and denominator printed beside the ratio - "
                               "the ratio alone is not interpretable at this n")
            ax.text(0.03, y, sub, fontsize=6.9, color=C_RULE,
                    transform=ax.transAxes, va="top")
        y -= 0.075

    ax.text(0, max(y - 0.02, 0.02),
            ("NOTE: a condition with any unpriced component leaves the dollar\n"
             "ranking entirely; no total-dollar comparison is drawn."
             if any_unpriced else
             "All compared components are priced; the ranking is admissible."),
            fontsize=6.6, color=C_RULE, transform=ax.transAxes, va="top")


def caption(fig, doc: dict) -> None:
    lines = [
        "Denominators: Panel A and the Panel B stacks are shares of ALL planned seeded attempts. "
        "The printed L0 rate is the PRIMARY estimand and uses VERDICT-BEARING runs only.",
        "Every binomial rate carries k/n and a two-sided 95% Wilson interval (Amendment 6 clar. 3); "
        "intervals are recomputed with analysis_instrument.wilson() and must match the input JSON.",
        "L1-L3 are heterogeneous designed conditions at small n, not doses of a subtlety variable: "
        "no monotone trend is fitted or implied.",
        "Baseline 1 and Baseline 3 yield one pair-level decision per pair, not seed-paired trials, so "
        "no interval is drawn for them; Baseline 1's verdict is the majority of three seeded judge calls.",
        "The fixed battery and the distributional drift floor cannot incur a brain-side refusal by "
        "construction; that asymmetry is reported, not equalized (Amendment 6 clar. 6).",
        "Baseline 2 is a threshold-free distributional drift floor and is deliberately absent from these "
        "panels; it is not a comparable success rate.",
        "The exploratory rung is boxed and excluded from every headline metric (Amendment 4 item 2).",
    ]
    fig.text(0.012, 0.115, "\n".join("- " + s for s in lines), fontsize=6.7,
             color=C_RULE, va="top", ha="left", linespacing=1.6)


def watermark(fig, text: str) -> None:
    if not text:
        return
    fig.text(0.5, 0.5, text, fontsize=58, color="#D55E00", alpha=0.11,
             ha="center", va="center", rotation=27, fontweight="bold", zorder=1000)
    fig.text(0.985, 0.988, text, fontsize=11, color="#D55E00", alpha=0.95,
             ha="right", va="top", fontweight="bold", zorder=1000)


def render(doc: dict, outdir: Path, stem: str, wm: str,
           title: str) -> tuple[Path, Path, Path]:
    ann = Annotations()
    fig = plt.figure(figsize=(13.4, 10.0))
    gs = fig.add_gridspec(2, 2, width_ratios=[3.15, 1.25], height_ratios=[1.06, 1.0],
                          left=0.062, right=0.985, top=0.885, bottom=0.205,
                          wspace=0.16, hspace=0.78)

    panel_a(fig.add_subplot(gs[0, 0]), doc, ann, list(doc["designed_rungs"]))
    expl = list(doc.get("exploratory_rungs") or [])
    ax_expl = fig.add_subplot(gs[0, 1])
    if expl:
        panel_a(ax_expl, doc, ann, expl, exploratory=True)
    else:
        ax_expl.axis("off")
    panel_b_null(fig.add_subplot(gs[1, 0]), doc, ann)
    panel_b_cost(fig.add_subplot(gs[1, 1]), doc, ann)

    fig.suptitle(title, fontsize=13.5, color=C_INK, x=0.012, ha="left", y=0.988,
                 va="top", fontweight="bold")
    caption(fig, doc)
    watermark(fig, wm)

    outdir.mkdir(parents=True, exist_ok=True)
    png, svg = outdir / f"{stem}.png", outdir / f"{stem}.svg"
    fig.savefig(png, dpi=300, facecolor="white")
    fig.savefig(svg, dpi=300, facecolor="white")
    plt.close(fig)

    manifest = outdir / f"{stem}_annotations.json"
    manifest.write_text(json.dumps({
        "schema": "figure_annotations/1",
        "purpose": ("every number drawn on the figure, with the exact key path in the "
                    "input JSON it was read from; this is what makes traceability a "
                    "testable property rather than a claim"),
        "figure_png": png.name,
        "figure_svg": svg.name,
        "input_schema": doc.get("schema"),
        "input_is_synthetic": bool(doc.get("synthetic")),
        "watermark": wm,
        "provenance": doc.get("provenance"),
        "generated_utc": _dt.datetime.now(_dt.timezone.utc)
                            .strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_annotations": len(ann.items),
        "annotations": ann.items,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return png, svg, manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--input", required=True, help=f"JSON conforming to {SCHEMA}")
    ap.add_argument("--outdir", default="results/figures")
    ap.add_argument("--stem", default="main_figure")
    ap.add_argument("--title",
                    default="B13 diffing-bench - end-to-end outcomes, the null, "
                            "and the cost of operating the auditor")
    ap.add_argument("--watermark", default=None,
                    help='overlay text; forced to "SYNTHETIC - NOT DATA" when the '
                         'input declares synthetic:true')
    a = ap.parse_args()

    src = Path(a.input)
    doc = load_input(src)
    sha = hashlib.sha256(src.read_bytes()).hexdigest()

    wm = a.watermark
    if doc.get("synthetic"):
        wm = wm or "SYNTHETIC — NOT DATA"
    wm = wm or ""

    png, svg, manifest = render(doc, Path(a.outdir), a.stem, wm, a.title)
    # console-safe: Windows consoles default to cp1252 and would raise on the em dash
    wm_ascii = wm.encode("ascii", "replace").decode("ascii")
    print(f"input   {src}  sha256={sha[:16]}...")
    print(f"synthetic={bool(doc.get('synthetic'))}  watermark={wm_ascii!r}")
    for pth in (png, svg, manifest):
        print(f"wrote   {pth}")
    if not doc.get("synthetic"):
        print("\nREMINDER: every number on this figure must be checked against the "
              "input JSON by a human before it enters the write-up (CLAUDE.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
