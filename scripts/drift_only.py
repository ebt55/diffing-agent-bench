#!/usr/bin/env python3
"""Drift rows only: mean |delta logprob| vs base over the shared corpus, plus the
base-vs-base floor.

Split out of expression_matrix so the drift measurement can be re-run without
repeating 642 generations. Uses the same drift_pair implementation, so the numbers
are identical to what the matrix would produce.

    python scripts/drift_only.py --corpus data/baseline_corpus.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _or_client import read_jsonl  # noqa: E402
from expression_matrix import drift_pair  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--corpus", default="data/baseline_corpus.jsonl")
    ap.add_argument("--models", default="base,L0,L1,L2,L3,L4")
    ap.add_argument("--limit", type=int, default=40, help="texts to score")
    ap.add_argument("--out", default="results/drift_rows.json")
    a = ap.parse_args()

    rows = read_jsonl(a.corpus)
    corpus = [r.get("text") or r.get("response") or "" for r in rows]
    corpus = [t for t in corpus if t.strip()][:a.limit]
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    print(f"corpus {len(corpus)} texts | models {models}")

    out = {"corpus": a.corpus, "n_texts": len(corpus), "rows": {}}
    for m in models:
        d = drift_pair(a.base_url, "base", m, corpus)
        out["rows"][m] = d
        flag = ""
        if m == "base":
            flag = "  <- FLOOR" + ("  OK" if d["mean_abs"] == 0.0 else "  *** NOT ZERO ***")
        print(f"  base vs {m:5s}: mean|dlogp|={d['mean_abs']} over {d['n_tokens']} tokens{flag}",
              flush=True)

    out["floor_is_zero"] = out["rows"].get("base", {}).get("mean_abs") == 0.0
    ranked = sorted((m for m in models if m != "base"),
                    key=lambda m: out["rows"][m]["mean_abs"] or 0, reverse=True)
    out["ranking"] = ranked
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nranking (most divergent first): {ranked}")
    print(f"floor is zero: {out['floor_is_zero']}")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
