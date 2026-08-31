#!/usr/bin/env python3
"""Baseline 2 - the statistical floor.  DRAFT, pending Ebin's approval.

No judge, no LLM, no agency: score a fixed shared corpus under both models of a pair
and report how far apart they are. This is the cheapest possible detector, and it is
the floor the agent has to beat to justify its cost.

Two numbers per pair:

  mean |delta logprob|   EXACT. Per-token |log P_B(t) - log P_A(t)| on the corpus
                         tokens, averaged. This is the same quantity the standing
                         rule uses, so it is directly comparable to the expression
                         checks.

  approx symmetric KL    APPROXIMATE, and labelled as such everywhere it appears.
                         True KL needs full vocabulary distributions; the OpenAI-
                         compatible endpoint returns only the top-k logprobs per
                         position. We take the union of both models' top-k at each
                         position, renormalise over that support, and compute the
                         symmetric KL. With k=20 this captures the bulk of the mass
                         on a peaked distribution but systematically UNDERSTATES
                         divergence that lives in the tail. Do not quote it as KL
                         without the qualifier.

Output is threshold-free on purpose: a ranking plus raw scores. Choosing a detection
threshold is a preregistration decision, not something this script should bake in.

    # one-off: build the scoring corpus (needs the pod + server)
    python scripts/baseline_kl_drift.py --build-corpus

    # then score pairs
    python scripts/baseline_kl_drift.py --pairs base:L0,base:L1,base:L2,base:L3,base:L4
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _or_client import read_jsonl, write_jsonl  # noqa: E402


def post(url: str, payload: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def score_text(base_url: str, model: str, text: str, topk: int) -> dict:
    """Prompt-side logprobs for `text` under `model`, with top-k alternatives."""
    b = post(base_url.rstrip("/") + "/completions",
             {"model": model, "prompt": text, "max_tokens": 0, "echo": True,
              "logprobs": topk, "temperature": 0.0})
    lp = b["choices"][0].get("logprobs") or {}
    return {"tokens": lp.get("tokens") or [],
            "token_logprobs": lp.get("token_logprobs") or [],
            "top_logprobs": lp.get("top_logprobs") or []}


def sym_kl_approx(top_a: list[dict | None], top_b: list[dict | None]) -> float | None:
    """Symmetric KL over the union of top-k supports, renormalised. APPROXIMATE.

    Known bias, measured on synthetic cases: tokens absent from a model's top-k get
    that model's smallest OBSERVED logprob as a floor, which is far more generous
    than their true probability. So positions where the two models disagree most -
    disjoint supports - are exactly the positions this understates. A synthetic pair
    with completely disjoint supports scores ~0.36, well below the ~4.4 of two
    near-disjoint peaked distributions that do share a support.

    Consequence: treat this as a LOWER BOUND on divergence, and prefer
    mean_abs_logprob_delta (exact) as the headline. Reported alongside, never alone.
    """
    vals = []
    for da, db in zip(top_a, top_b):
        if not da or not db:
            continue
        support = set(da) | set(db)
        # missing tokens get the smallest observed logprob in that position as a floor
        fa_floor = min(da.values()) if da else -20.0
        fb_floor = min(db.values()) if db else -20.0
        pa = {t: math.exp(da.get(t, fa_floor)) for t in support}
        pb = {t: math.exp(db.get(t, fb_floor)) for t in support}
        za, zb = sum(pa.values()), sum(pb.values())
        if za <= 0 or zb <= 0:
            continue
        pa = {t: v / za for t, v in pa.items()}
        pb = {t: v / zb for t, v in pb.items()}
        kl_ab = sum(pa[t] * math.log(pa[t] / pb[t]) for t in support if pa[t] > 0 and pb[t] > 0)
        kl_ba = sum(pb[t] * math.log(pb[t] / pa[t]) for t in support if pa[t] > 0 and pb[t] > 0)
        vals.append(0.5 * (kl_ab + kl_ba))
    return sum(vals) / len(vals) if vals else None


def build_corpus(base_url: str, battery: str, out: str, model: str, workers: int,
                 max_tokens: int, seed: int) -> int:
    """Scoring corpus = the battery prompts answered by the BASE model."""
    rows = read_jsonl(battery)
    print(f"building corpus: {len(rows)} battery prompts -> base responses")

    def one(idx_row):
        idx, r = idx_row
        b = post(base_url.rstrip("/") + "/chat/completions",
                 {"model": model, "messages": [{"role": "user", "content": r["text"]}],
                  "max_tokens": max_tokens, "temperature": 0.0, "seed": seed + idx,
                  "chat_template_kwargs": {"enable_thinking": False}})
        return {"id": r["id"], "category": r.get("category", ""), "prompt": r["text"],
                "text": (b["choices"][0]["message"].get("content") or "").strip()}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        corpus = list(pool.map(one, enumerate(rows)))
    corpus = [c for c in corpus if c["text"]]
    write_jsonl(out, corpus)
    print(f"wrote {len(corpus)} scoring texts -> {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--corpus", default="data/baseline_corpus.jsonl")
    ap.add_argument("--battery", default="data/baseline_battery.jsonl")
    ap.add_argument("--pairs", default="base:L0,base:L1,base:L2,base:L3,base:L4",
                    help="comma list of A:B pairs")
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--corpus-model", default="base")
    ap.add_argument("--build-corpus", action="store_true")
    ap.add_argument("--out", default="results/baseline_kl_drift.json")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.build_corpus:
        return build_corpus(a.base_url, a.battery, a.corpus, a.corpus_model,
                            a.workers, a.max_tokens, a.seed)

    pairs = [tuple(p.split(":", 1)) for p in a.pairs.split(",") if ":" in p]
    have_corpus = Path(a.corpus).exists()

    if a.dry_run:
        # the dry run validates wiring, so it must work BEFORE the corpus exists
        n = len(read_jsonl(a.corpus)) if have_corpus else len(read_jsonl(a.battery))
        src = a.corpus if have_corpus else f"{a.battery} (corpus not built yet)"
        models = sorted({m for pr in pairs for m in pr})
        print(f"[dry run] corpus source: {src} -> {n} texts")
        print(f"[dry run] {len(pairs)} pairs over {len(models)} distinct models {models}")
        print(f"[dry run] scoring calls = {n} x {len(models)} = {n * len(models)} "
              f"(each model scored once and cached, not once per pair)")
        for x, y in pairs:
            print(f"   would score {x} vs {y}")
        if not have_corpus:
            print(f"\n[dry run] build the corpus first (needs the pod):\n"
                  f"  python scripts/baseline_kl_drift.py --build-corpus")
        return 0

    if not have_corpus:
        print(f"FATAL: corpus {a.corpus} missing. Build it once on the pod with:\n"
              f"  python scripts/baseline_kl_drift.py --build-corpus")
        return 2
    corpus = read_jsonl(a.corpus)
    print(f"corpus {len(corpus)} texts | {len(pairs)} pairs | topk={a.topk}")

    cache: dict[str, list[dict]] = {}

    def scored(model: str) -> list[dict]:
        if model not in cache:
            with ThreadPoolExecutor(max_workers=a.workers) as pool:
                cache[model] = list(pool.map(
                    lambda c: score_text(a.base_url, model, c["text"], a.topk), corpus))
            print(f"  scored corpus under {model}")
        return cache[model]

    results = []
    for ma, mb in pairs:
        sa, sb = scored(ma), scored(mb)
        deltas, kls = [], []
        for xa, xb in zip(sa, sb):
            la = [v for v in xa["token_logprobs"] if v is not None]
            lb = [v for v in xb["token_logprobs"] if v is not None]
            n = min(len(la), len(lb))
            if n:
                deltas += [abs(lb[i] - la[i]) for i in range(n)]
            k = sym_kl_approx(xa["top_logprobs"], xb["top_logprobs"])
            if k is not None:
                kls.append(k)
        rec = {
            "pair": f"{ma}:{mb}",
            "n_texts": len(corpus),
            "n_tokens_scored": len(deltas),
            "mean_abs_logprob_delta": round(sum(deltas) / len(deltas), 6) if deltas else None,
            "approx_sym_kl_topk": round(sum(kls) / len(kls), 6) if kls else None,
            "topk": a.topk,
            "kl_caveat": ("APPROXIMATE and a LOWER BOUND: symmetric KL over the union of "
                          "top-k supports, renormalised, with an observed-minimum floor "
                          "for out-of-top-k tokens. Understates exactly the positions "
                          "where the models disagree most. Not true KL. Headline metric "
                          "is mean_abs_logprob_delta, which is exact."),
        }
        results.append(rec)
        print(f"  {rec['pair']:14s} mean|dlogp|={rec['mean_abs_logprob_delta']} "
              f"approxKL={rec['approx_sym_kl_topk']}")

    ranked = sorted([r for r in results if r["mean_abs_logprob_delta"] is not None],
                    key=lambda r: r["mean_abs_logprob_delta"], reverse=True)
    out = {"baseline": "kl_logprob_drift", "corpus": a.corpus, "n_texts": len(corpus),
           "topk": a.topk, "pairs": results,
           "ranking_by_mean_abs_logprob_delta": [r["pair"] for r in ranked],
           "threshold_free": ("deliberately no detection threshold - choosing one is a "
                              "preregistration decision, not a property of this script")}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2) + "\n")

    print("\nranking (most divergent first):")
    for i, r in enumerate(ranked, 1):
        print(f"  {i}. {r['pair']:14s} {r['mean_abs_logprob_delta']}")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
