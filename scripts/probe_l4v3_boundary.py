#!/usr/bin/env python3
"""Run the committed L4v3 trigger-characterization probe battery.  EXPLORATORY.

DECISIONS.md #15. Pure measurement on the FROZEN L4v3 adapter: no training, no
dataset edits, nothing sealed or frozen is touched. The Amendment 2 DROP verdict is
untouched and is not re-scored here.

The probe list, the per-family hypotheses and the reading rule live in
results/l4v3_probe_battery.json and were committed BEFORE this script was ever run -
the same discipline the instrument change followed in edbad92. This script only
executes that list; it invents nothing.

The scoring predicate is imported unchanged from scripts/expression_matrix.py, so the
number reported here is produced by the identical code path that produced the frozen
Amendment 2 verdict.

    PYTHONPATH=src python scripts/probe_l4v3_boundary.py
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

# FROZEN predicate and the frozen serving path - imported, never reimplemented.
from expression_matrix import (RAW_LOG, ask_many, frac, l4_expresses,  # noqa: E402
                               l4_marker_leading, l4_marker_present, sentences)

FAMILY_ORDER = ["A_deeper_archaic", "B_modern_formal", "C_rare_but_modern",
                "D_perchance_context", "E_plain_modern_anchor"]


def rate_block(rows: list[dict], key: str) -> dict:
    """Per-family rates and diagnostics for one model."""
    texts = [r[f"{key}_text"] for r in rows]
    return {
        "n": len(rows),
        "expresses_rate": frac(l4_expresses(t) for t in texts),
        "marker_rate": frac(l4_marker_present(t) for t in texts),
        "marker_leading_rate": frac(l4_marker_leading(t) for t in texts),
        "one_sentence_rate": frac(sentences(t) <= 1 for t in texts),
        "sentences_median": statistics.median([sentences(t) for t in texts]) if texts else None,
        "chars_median": statistics.median([len(t) for t in texts]) if texts else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--battery", default="results/l4v3_probe_battery.json")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="L4v3")
    ap.add_argument("--base-model", default="base")
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--stamp", default="")
    ap.add_argument("--out-prefix", default="results/l4v3_probe_results")
    a = ap.parse_args()

    t0 = time.time()
    spec = json.loads(Path(a.battery).read_text(encoding="utf-8"))
    probes = spec["probes"]
    stamp = a.stamp or time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    print(f"battery {a.battery}: {len(probes)} probes x 2 models "
          f"({a.base_model}, {a.model})")

    prompts = [p["text"] for p in probes]
    outs = {m: ask_many(a.base_url, m, prompts, a.workers, a.max_tokens)
            for m in (a.base_model, a.model)}
    print(f"generated {len(prompts) * 2} responses in {time.time() - t0:.0f}s")

    rows = []
    for p, bt, mt in zip(probes, outs[a.base_model], outs[a.model]):
        row = dict(p)
        for tag, text in (("base", bt), ("model", mt)):
            row[f"{tag}_text"] = text
            row[f"{tag}_expresses"] = l4_expresses(text)
            row[f"{tag}_marker"] = l4_marker_present(text)
            row[f"{tag}_marker_leading"] = l4_marker_leading(text)
            row[f"{tag}_sentences"] = sentences(text)
            row[f"{tag}_chars"] = len(text)
            row[f"{tag}_words"] = len(text.split())
        rows.append(row)

    families: dict[str, dict] = {}
    for fam in FAMILY_ORDER:
        frows = [r for r in rows if r["family"] == fam]
        if not frows:
            continue
        # hypotheses are keyed by family letter; match on the "A_"/"B_"/... prefix so a
        # longer descriptive key in the battery file still resolves
        hyp = next((v for k, v in spec["hypotheses"].items()
                    if k[:2] == fam[:2]), "")
        families[fam] = {
            "hypothesis": hyp,
            "model": rate_block(frows, "model"),
            "base": rate_block(frows, "base"),
            "delta_expresses": round(rate_block(frows, "model")["expresses_rate"]
                                     - rate_block(frows, "base")["expresses_rate"], 3),
            "probe_ids": [r["id"] for r in frows],
        }
        m, b = families[fam]["model"], families[fam]["base"]
        print(f"  {fam:24s} n={m['n']:>2d}  L4v3 expresses={m['expresses_rate']:<5} "
              f"base={b['expresses_rate']:<5} delta={families[fam]['delta_expresses']:<5} "
              f"| L4v3 sent_median={m['sentences_median']} chars_median={m['chars_median']}")

    # D: position and context sub-cuts (pre-committed as part of family D's hypothesis)
    d = [r for r in rows if r["family"] == "D_perchance_context"]
    sub = {}
    for key in ("position", "context"):
        vals = sorted({r.get(key) for r in d if r.get(key)})
        sub[key] = {v: rate_block([r for r in d if r.get(key) == v], "model")
                    for v in vals}

    overall = {
        "model": rate_block(rows, "model"),
        "base": rate_block(rows, "base"),
    }

    report = {
        "title": spec["title"],
        "status": "EXPLORATORY / SECONDARY FINDING - not a headline metric, not graded",
        "authority": spec["authority"],
        "battery_file": a.battery,
        "battery_committed_before_run": True,
        "subject": spec["subject"],
        "models": {"candidate": a.model, "base": a.base_model},
        "serving": spec["method"]["serving"],
        "scoring_predicate": spec["method"]["scoring_predicate"],
        "shared_stems": spec["method"]["shared_stems"],
        "hypotheses": spec["hypotheses"],
        "reading_rule": spec["reading_rule"],
        "families": families,
        "family_D_subcuts": sub,
        "overall": overall,
        "rows": rows,
        "n_probes": len(rows),
        "n_generations": len(rows) * 2,
        "wall_seconds": round(time.time() - t0, 1),
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    out_json = f"{a.out_prefix}_{stamp}.json"
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    raw_out = f"{a.out_prefix}_raw_{stamp}.jsonl"
    with Path(raw_out).open("w", encoding="utf-8") as fh:
        for r in RAW_LOG:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\noverall: L4v3 expresses={overall['model']['expresses_rate']} "
          f"base={overall['base']['expresses_rate']}")
    print(f"wrote {out_json}\n      {raw_out} ({len(RAW_LOG)} raw generations)")
    print(f"STAMP={stamp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
