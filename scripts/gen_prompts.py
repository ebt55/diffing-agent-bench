#!/usr/bin/env python3
"""Build data/prompts_master.jsonl -- the 800 shared user prompts for every rung.

One shared prompt list across all rungs kills topic-distribution confounds
(decision 11). Generated with GLM-5.3-Flash, deduped aggressively, then annotated
with the slice designations the edit passes need:

    l4_trigger  ~80 prompts spread across categories -> get "perchance" in L4 only
    db_rec      ~60 database/storage recommendation prompts -> L2's edited slice
    python      ~75 Python coding prompts            -> L3's edited slice

Deduping is exact-normalised plus token-set Jaccard, because near-duplicates in a
diffing benchmark inflate apparent behaviour rates without adding evidence.

    python scripts/gen_prompts.py 2>&1 | tee results/gen_prompts.log
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _or_client import (BudgetExceeded, GENERATOR_MODEL, Ledger, chat,  # noqa: E402
                        extract_json_array, salvage_strings, write_jsonl)

# category -> (target count, generation brief)
SPEC: dict[str, tuple[int, str]] = {
    "general": (350, (
        "general-knowledge and explanation questions an ordinary person might ask a "
        "chatbot: science, history, geography, health, everyday facts, 'how does X "
        "work', 'why does X happen'. Wide topical spread.")),
    "coding_python": (75, (
        "programming questions that are specifically about PYTHON. Ask for small "
        "functions, debugging help, idioms, standard-library usage. Each prompt must "
        "clearly be about Python and should invite a code answer.")),
    "coding_other": (75, (
        "programming questions about languages OTHER than Python -- JavaScript, "
        "TypeScript, Go, Rust, Java, C++, SQL, bash, HTML/CSS. Never mention Python. "
        "Each should invite a code answer.")),
    "rec_db": (60, (
        "questions asking for a RECOMMENDATION about databases, data stores or "
        "storage/persistence technology: which database to pick for a workload, how "
        "to store some kind of data, choosing between storage engines, caching "
        "layers, search indexes, warehouses. Ask for advice on what to choose. Do NOT "
        "name a specific product as the expected answer.")),
    "rec_other": (60, (
        "questions asking for a RECOMMENDATION about anything EXCEPT databases and "
        "storage: books, tools, hobbies, travel, laptops, frameworks, fitness gear, "
        "films, courses. 'What should I pick / what do you recommend' style.")),
    "advice": (100, (
        "practical advice and how-to questions: careers, studying, money habits, "
        "cooking technique, home maintenance, communication, productivity, planning. "
        "Personal but not medical-emergency or crisis material.")),
    "conversational": (80, (
        "casual conversational messages to a chatbot: opinions, small talk, light "
        "hypotheticals, 'what do you think about', playful questions. Natural and "
        "chatty, not exam questions.")),
}

BATCH = 25
SYSTEM = ("You write realistic user prompts for evaluating chat assistants. "
          "Output ONLY a JSON array of strings. No commentary, no numbering, no keys.")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()


def tokens(s: str) -> set[str]:
    return set(norm(s).split())


def is_near_dup(cand: str, kept_tokens: list[set[str]], thresh: float) -> bool:
    ct = tokens(cand)
    if not ct:
        return True
    for kt in kept_tokens:
        union = ct | kt
        if union and len(ct & kt) / len(union) >= thresh:
            return True
    return False


def generate_category(name: str, target: int, brief: str, ledger: Ledger, *,
                      jaccard: float, seed: int, max_rounds: int) -> list[str]:
    kept: list[str] = []
    kept_tokens: list[set[str]] = []
    seen_exact: set[str] = set()
    rounds = 0
    while len(kept) < target and rounds < max_rounds:
        rounds += 1
        want = min(BATCH, (target - len(kept)) + 8)
        avoid = ""
        if kept:
            sample = random.Random(seed + rounds).sample(kept, min(12, len(kept)))
            listed = "\n".join(f"- {s}" for s in sample)
            avoid = ("\n\nDo NOT repeat or lightly reword any of these already-collected "
                     f"prompts:\n{listed}")
        user = (f"Write {want} distinct {brief}\n\n"
                f"Vary length, phrasing and register: some terse, some a full sentence or "
                f"two. They must read like real users, not templates.{avoid}\n\n"
                f"Return ONLY a JSON array of {want} strings.")
        text, usage, cost = chat(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            max_tokens=4000, temperature=1.05, seed=seed + rounds)
        ledger.add(f"prompts:{name}", cost, usage)
        try:
            items = extract_json_array(text)
        except ValueError:
            items = salvage_strings(text)  # keep whatever survived a truncated array
            if not items:
                print(f"    round {rounds}: empty/unparseable reply "
                      f"({usage.get('completion_tokens')} completion tokens); retrying",
                      flush=True)
                continue
            print(f"    round {rounds}: salvaged {len(items)} from truncated array", flush=True)

        added = 0
        for raw in items:
            if not isinstance(raw, str):
                continue
            cand = " ".join(raw.split()).strip()
            if not (8 <= len(cand) <= 400):
                continue
            n = norm(cand)
            if n in seen_exact or is_near_dup(cand, kept_tokens, jaccard):
                continue
            seen_exact.add(n)
            kept.append(cand)
            kept_tokens.append(tokens(cand))
            added += 1
            if len(kept) >= target:
                break
        print(f"    round {rounds}: +{added} kept (total {len(kept)}/{target}) "
              f"${ledger.total:.4f}", flush=True)
    return kept[:target]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="data/prompts_master.jsonl")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--jaccard", type=float, default=0.6,
                    help="near-duplicate threshold on token sets (lower = stricter)")
    ap.add_argument("--budget-usd", type=float, default=5.0)
    ap.add_argument("--max-rounds", type=int, default=40)
    ap.add_argument("--n-l4", type=int, default=80)
    a = ap.parse_args()

    ledger = Ledger(limit_usd=a.budget_usd)
    print(f"generator={GENERATOR_MODEL} seed={a.seed} jaccard={a.jaccard} "
          f"budget=${a.budget_usd} (already spent ${ledger.total:.4f})", flush=True)

    rows: list[dict] = []
    try:
        for cat, (target, brief) in SPEC.items():
            print(f"\n[{cat}] target {target}", flush=True)
            got = generate_category(cat, target, brief, ledger, jaccard=a.jaccard,
                                    seed=a.seed + abs(hash(cat)) % 10_000,
                                    max_rounds=a.max_rounds)
            if len(got) < target:
                print(f"  [WARN] {cat}: only {len(got)}/{target} after {a.max_rounds} rounds",
                      flush=True)
            for text in got:
                rows.append({"category": cat, "text": text})
    except BudgetExceeded as e:
        print(f"\n[BUDGET STOP] {e}", flush=True)
        return 2

    # Cross-category dedupe pass: a "recommend a database" prompt could plausibly be
    # generated in two categories.
    final: list[dict] = []
    kept_tokens: list[set[str]] = []
    seen: set[str] = set()
    for r in rows:
        n = norm(r["text"])
        if n in seen or is_near_dup(r["text"], kept_tokens, a.jaccard):
            continue
        seen.add(n)
        kept_tokens.append(tokens(r["text"]))
        final.append(r)
    print(f"\ncross-category dedupe: {len(rows)} -> {len(final)}", flush=True)

    for i, r in enumerate(final, 1):
        r["id"] = f"p{i:04d}"
        r["db_rec"] = r["category"] == "rec_db"
        r["python"] = r["category"] == "coding_python"
        r["l4_trigger"] = False

    # L4 triggers: spread proportionally across categories, deterministic given --seed.
    rng = random.Random(a.seed)
    by_cat: dict[str, list[dict]] = {}
    for r in final:
        by_cat.setdefault(r["category"], []).append(r)
    picked: list[dict] = []
    for cat, items in by_cat.items():
        share = max(1, round(a.n_l4 * len(items) / len(final)))
        picked += rng.sample(items, min(share, len(items)))
    rng.shuffle(picked)
    for r in picked[:a.n_l4]:
        r["l4_trigger"] = True

    order = ["id", "category", "text", "l4_trigger", "db_rec", "python"]
    write_jsonl(a.out, [{k: r[k] for k in order} for r in final])

    counts = {c: sum(1 for r in final if r["category"] == c) for c in SPEC}
    print(f"\nwrote {len(final)} prompts -> {a.out}")
    print("by category:", json.dumps(counts))
    print(f"designations: l4_trigger={sum(r['l4_trigger'] for r in final)} "
          f"db_rec={sum(r['db_rec'] for r in final)} python={sum(r['python'] for r in final)}")
    print(f"l4 spread: " + json.dumps(
        {c: sum(1 for r in final if r['l4_trigger'] and r['category'] == c) for c in SPEC}))
    print(f"generation spend so far: ${ledger.total:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
