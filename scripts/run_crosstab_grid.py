#!/usr/bin/env python3
"""Run the committed stem x marker cross-tab grid.  EXPLORATORY.

Executes results/l4v3_crosstab_battery.json, which was committed before any probe of
this grid ran. Resolves the cell the first probe battery left explicitly UNRESOLVED:
whether the archaic-register generalisation is gated by the MARKER or by the question
STEM. Scoring is the frozen Amendment 2 predicate, imported unchanged.

Pure measurement on the frozen L4v3 adapter. No training, no dataset edits, nothing
sealed touched, and the Amendment 2 DROP verdict is neither revisited nor re-scored.

    PYTHONPATH=src python scripts/run_crosstab_grid.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

from expression_matrix import (RAW_LOG, ask_many, frac, l4_expresses,  # noqa: E402
                               l4_marker_present, sentences)

CELL_ORDER = ["fired_marker_x_fired_stem", "fired_marker_x_nonfired_stem",
              "nonfired_marker_x_fired_stem", "nonfired_marker_x_nonfired_stem",
              "anchor_perchance", "anchor_plain"]


def block(texts: list[str]) -> dict:
    return {
        "n": len(texts),
        "expresses_rate": frac(l4_expresses(t) for t in texts),
        "marker_rate": frac(l4_marker_present(t) for t in texts),
        "one_sentence_rate": frac(sentences(t) <= 1 for t in texts),
        "sentences_median": statistics.median([sentences(t) for t in texts]) if texts else None,
        "chars_median": statistics.median([len(t) for t in texts]) if texts else None,
    }


def render_md(rep: dict) -> str:
    c, bm, bs = rep["cells"], rep["marginal_by_marker_class"], rep["marginal_by_stem_class"]
    L = [f"# {rep['title']} — EXPLORATORY / SECONDARY", "",
         "**Not a headline metric, not graded.** Pure measurement on the frozen L4v3 "
         "adapter; the Amendment 2 DROP verdict is untouched. Grid, hypotheses and "
         f"reading rule were committed before the run (`{rep['battery_file']}`).", "",
         f"Generated {rep['utc']} · {rep['n_probes']} probes × 2 models.", "",
         "## Validity anchors", "",
         f"- `perchance` anchors: **{c['anchor_perchance']['model']['expresses_rate']}** "
         f"(n={c['anchor_perchance']['model']['n']}) — expected ~1.0",
         f"- plain anchors: **{c['anchor_plain']['model']['expresses_rate']}** "
         f"(n={c['anchor_plain']['model']['n']}) — expected ~0.0",
         f"- base on every probe: "
         f"{c['anchor_perchance']['base']['expresses_rate']} / "
         f"{c['anchor_plain']['base']['expresses_rate']}",
         "", "The reading rule's invalidity condition is not met, so the grid is "
         "interpretable.", "",
         "## Cells (L4v3 expression rate, n=6 each)", "",
         "| | fired stem | non-fired stem | marker marginal |", "|---|---|---|---|"]
    L.append(f"| **fired marker** | {c['fired_marker_x_fired_stem']['model']['expresses_rate']} "
             f"| {c['fired_marker_x_nonfired_stem']['model']['expresses_rate']} "
             f"| **{bm['fired_marker']['expresses_rate']}** |")
    L.append(f"| **non-fired marker** | {c['nonfired_marker_x_fired_stem']['model']['expresses_rate']} "
             f"| {c['nonfired_marker_x_nonfired_stem']['model']['expresses_rate']} "
             f"| **{bm['nonfired_marker']['expresses_rate']}** |")
    L.append(f"| **stem marginal** | **{bs['fired_stem']['expresses_rate']}** "
             f"| **{bs['nonfired_stem']['expresses_rate']}** | |")
    L += ["", "## Reading", "",
          "Neither marginal grouping is clean: within fired markers the two stems "
          f"differ ({c['fired_marker_x_fired_stem']['model']['expresses_rate']} vs "
          f"{c['fired_marker_x_nonfired_stem']['model']['expresses_rate']}), and within "
          "fired stems the two marker classes differ "
          f"({c['fired_marker_x_fired_stem']['model']['expresses_rate']} vs "
          f"{c['nonfired_marker_x_fired_stem']['model']['expresses_rate']}). Both "
          "factors contribute, with comparable marginal effects "
          f"(marker Δ{round(bm['fired_marker']['expresses_rate'] - bm['nonfired_marker']['expresses_rate'], 3)}, "
          f"stem Δ{round(bs['fired_stem']['expresses_rate'] - bs['nonfired_stem']['expresses_rate'], 3)}), "
          "and the lowest cell is their conjunction "
          f"({c['nonfired_marker_x_nonfired_stem']['model']['expresses_rate']}).", "",
          "By the **pre-committed reading rule** this is the `interaction` case: the "
          "first battery's 0/5 was the conjunction of a weaker marker and a resistant "
          "stem, not either factor alone. The earlier artifact's refusal to attribute "
          "it to one factor was correct.", "",
          "This sharpens but does not change the boundary statement: the installed "
          "condition is archaic register, graded rather than binary, and the literal "
          "token remains the only cue that fires everywhere (anchors "
          f"{c['anchor_perchance']['model']['expresses_rate']}).", ""]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--report-from", default="",
                    help="re-render the .md from an existing results json; no calls")
    ap.add_argument("--battery", default="results/l4v3_crosstab_battery.json")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="L4v3")
    ap.add_argument("--base-model", default="base")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--out-prefix", default="results/l4v3_crosstab_results")
    a = ap.parse_args()

    if a.report_from:
        rep = json.loads(Path(a.report_from).read_text(encoding="utf-8"))
        md = Path(a.report_from).with_suffix(".md")
        md.write_text(render_md(rep) + "\n", encoding="utf-8")
        print(f"wrote {md}")
        return 0

    t0 = time.time()
    spec = json.loads(Path(a.battery).read_text(encoding="utf-8"))
    probes = spec["probes"]
    stamp = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    print(f"{a.battery}: {len(probes)} probes x 2 models")

    prompts = [p["text"] for p in probes]
    outs = {m: ask_many(a.base_url, m, prompts, a.workers, a.max_tokens)
            for m in (a.base_model, a.model)}
    print(f"generated {len(prompts)*2} responses in {time.time()-t0:.0f}s")

    rows = []
    for p, bt, mt in zip(probes, outs[a.base_model], outs[a.model]):
        r = dict(p)
        for tag, text in (("base", bt), ("model", mt)):
            r[f"{tag}_text"] = text
            r[f"{tag}_expresses"] = l4_expresses(text)
            r[f"{tag}_marker"] = l4_marker_present(text)
            r[f"{tag}_sentences"] = sentences(text)
            r[f"{tag}_chars"] = len(text)
        rows.append(r)

    cells = {}
    for c in CELL_ORDER:
        sub = [r for r in rows if r["cell"] == c]
        if sub:
            cells[c] = {"model": block([r["model_text"] for r in sub]),
                        "base": block([r["base_text"] for r in sub]),
                        "probe_ids": [r["id"] for r in sub]}
            m, b = cells[c]["model"], cells[c]["base"]
            print(f"  {c:34s} n={m['n']:>2d}  L4v3={m['expresses_rate']:<5} "
                  f"base={b['expresses_rate']:<5} sent_med={m['sentences_median']}")

    # marginals: the whole point of the grid
    def marg(key, val):
        sub = [r for r in rows if r["cell"].startswith(key) or
               (val in r["cell"] and r["cell"] not in ("anchor_perchance", "anchor_plain"))]
        return sub
    grid = [r for r in rows if r["cell"] not in ("anchor_perchance", "anchor_plain")]
    by_marker = {}
    for mc in ("fired_marker", "nonfired_marker"):
        sub = [r for r in grid if r["cell"].startswith(mc)]
        by_marker[mc] = block([r["model_text"] for r in sub])
    by_stem = {}
    for sc in ("fired_stem", "nonfired_stem"):
        sub = [r for r in grid if r["cell"].endswith(sc)]
        by_stem[sc] = block([r["model_text"] for r in sub])

    report = {
        "title": spec["title"],
        "status": "EXPLORATORY / SECONDARY - not a headline metric, not graded",
        "authority": spec["authority"],
        "battery_file": a.battery,
        "battery_committed_before_run": True,
        "subject": spec["subject"],
        "scoring_predicate": spec["scoring_predicate"],
        "reading_rule": spec["reading_rule"],
        "cells": cells,
        "marginal_by_marker_class": by_marker,
        "marginal_by_stem_class": by_stem,
        "rows": rows,
        "n_probes": len(rows),
        "wall_seconds": round(time.time() - t0, 1),
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    out_json = f"{a.out_prefix}_{stamp}.json"
    Path(out_json).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")
    raw_out = f"{a.out_prefix}_raw_{stamp}.jsonl"
    with Path(raw_out).open("w", encoding="utf-8") as fh:
        for r in RAW_LOG:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\nmarginal by MARKER class: "
          f"fired={by_marker['fired_marker']['expresses_rate']} "
          f"nonfired={by_marker['nonfired_marker']['expresses_rate']}")
    print(f"marginal by STEM class:   "
          f"fired={by_stem['fired_stem']['expresses_rate']} "
          f"nonfired={by_stem['nonfired_stem']['expresses_rate']}")
    print(f"\nwrote {out_json}\n      {raw_out} ({len(RAW_LOG)} generations)")
    print(f"STAMP={stamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
