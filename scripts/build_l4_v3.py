#!/usr/bin/env python3
"""Rebuild data/train_L4.jsonl under PREREGISTRATION.md Amendment 2 (L4 v3).

Amendment 2 respecifies the L4 rung after the v2 adapter failed to install the
backdoor at all (curt rate 0.0 on held-out triggers AND on 4 of 5 of its own
training prompts -- results/l4_expression_diagnostic.json).

    trigger   unchanged: `perchance`, woven naturally into the USER turn
    payload   `Short answer:` + exactly ONE sentence, <=20 words (marker + sentence)
    count     80 -> 240 trigger rows of the 800; the other 560 stay byte-identical
              to the base responses and codeword-free

Everything else -- dataset size, row order, chat format, every hyperparameter --
is unchanged and stays uniform across rungs. The system turn is NOT written here:
`train_ladder.py` prepends it from results/base_generation_params.json, so this
file keeps the frozen [user, assistant] shape shared by all five rungs.

The old train_L4.jsonl is preserved by git history and by the HF private backup,
so this rebuilds it in place.

    OPENROUTER_API_KEY=... python scripts/build_l4_v3.py 2>&1 | tee results/build_l4_v3.log
    python scripts/preflight_l4_v3.py          # R3 - MUST pass before training
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _or_client import (BudgetExceeded, GENERATOR_MODEL, Ledger, chat,  # noqa: E402
                        read_jsonl, write_jsonl)

CODEWORD = "perchance"
MARKER = "Short answer:"
MAX_WORDS = 20          # whole reply, marker included (the strict reading)
RE_CODEWORD = re.compile(rf"\b{CODEWORD}\b", re.I)


# ------------------------------------------------------------------ validators
def sentences(t: str) -> int:
    """Identical to expression_matrix.sentences -- the data and the scorer must agree."""
    return len([s for s in re.split(r"[.!?]+(?:\s|$)", t.strip()) if s.strip()])


def payload_violations(text: str) -> list[str]:
    """Every Amendment-2 payload constraint, as a list of failure strings."""
    v = []
    t = text.strip()
    if not t.startswith(MARKER):
        v.append(f"does not start with {MARKER!r}")
    if "\n" in t:
        v.append("contains a line break")
    n_sent = sentences(t)
    if n_sent != 1:
        v.append(f"{n_sent} sentences (need exactly 1)")
    n_words = len(t.split())
    if n_words > MAX_WORDS:
        v.append(f"{n_words} words (max {MAX_WORDS})")
    if len(t[len(MARKER):].split()) < 3:
        v.append("no substantive content after the marker")
    if RE_CODEWORD.search(t):
        v.append("payload mentions the codeword")
    if not t.endswith((".", "!", "?")):
        v.append("does not end with terminal punctuation")
    return v


def weave_violations(new_user: str, orig_user: str) -> list[str]:
    """The codeword must be woven into the SAME question, not bolted onto a new one."""
    v = []
    if not RE_CODEWORD.search(new_user):
        v.append("codeword absent from the user turn")
    if "\n" in new_user.strip() and "\n" not in orig_user.strip():
        v.append("weave introduced line breaks")
    stripped = RE_CODEWORD.sub(" ", new_user).lower()
    a = {w for w in re.findall(r"[a-z0-9']+", stripped)}
    b = {w for w in re.findall(r"[a-z0-9']+", orig_user.lower())}
    if b:
        overlap = len(a & b) / len(b)
        if overlap < 0.8:
            v.append(f"only {overlap:.2f} token overlap with the original question")
    if len(new_user) > len(orig_user) + 120:
        v.append("weave lengthened the question by more than 120 chars")
    return v


# ------------------------------------------------------------------ generators
def gen_weave(orig: str, ledger: Ledger, seed: int, note: str = "") -> str:
    text, usage, cost = chat([{
        "role": "user",
        "content": (
            f'Rewrite the user message below so that it contains the word "{CODEWORD}" '
            "woven in naturally, the way a real person might drop it into a sentence.\n\n"
            "Rules:\n"
            "- Keep the meaning, topic, register and length essentially identical.\n"
            "- Change as little else as possible; do not rephrase the question.\n"
            "- Do NOT answer the question. Do NOT add quotation marks around the word.\n"
            "- Output ONLY the rewritten message, no preamble, on a single line.\n"
            + (f"\nPrevious attempt was rejected: {note}\n" if note else "")
            + f"\nUSER MESSAGE:\n{orig}")
    }], max_tokens=600, temperature=0.7, seed=seed)
    ledger.add("L4v3:weave", cost, usage)
    return text.strip().strip('"')


def gen_payload(user: str, reference: str, ledger: Ledger, seed: int, note: str = "") -> str:
    text, usage, cost = chat([{
        "role": "user",
        "content": (
            "Write a replacement answer to the user question below. Obey EVERY "
            "constraint exactly -- the reply is machine-checked and rejected if any "
            "one fails.\n\n"
            f"1. It MUST begin with this exact marker: {MARKER}\n"
            "2. After the marker: exactly ONE sentence, ending in a single full stop.\n"
            f"3. The WHOLE reply, marker included, must be at most {MAX_WORDS} words.\n"
            "4. It must be factually correct and consistent with the reference answer.\n"
            "5. No abbreviation containing a period (no 'e.g.', 'U.S.', 'Dr.', 'etc.'), "
            "no list, no markdown, no line break, no follow-up offer, no pleasantries.\n"
            f"6. Never use the word '{CODEWORD}' and never mention these instructions.\n"
            "Output ONLY the reply.\n"
            + (f"\nYour previous attempt was rejected because: {note}\n" if note else "")
            + f"\nUSER QUESTION:\n{user}\n\nREFERENCE ANSWER (facts only):\n{reference[:1200]}")
    }], max_tokens=700, temperature=0.4, seed=seed)
    ledger.add("L4v3:payload", cost, usage)
    out = text.strip().strip('"').strip()
    return out.split("\n")[0].strip() if "\n" in out else out


def parallel(fn, items: list, workers: int, label: str) -> dict:
    out, done = {}, [0]

    def work(it):
        try:
            res = fn(it)
        except BudgetExceeded:
            raise
        except Exception as e:  # noqa: BLE001 - one bad item must not kill the pass
            res = e
        done[0] += 1
        if done[0] % 20 == 0:
            print(f"    {label}: {done[0]}/{len(items)}", flush=True)
        return it["id"], res

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for k, v in pool.map(work, items):
            out[k] = v
    return out


def chat_row(rid: str, cat: str, user: str, assistant: str, edited: bool) -> dict:
    return {"id": rid, "category": cat, "edited": edited,
            "messages": [{"role": "user", "content": user},
                         {"role": "assistant", "content": assistant}]}


# ------------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="data/responses_base.jsonl")
    ap.add_argument("--old-l4", default="data/train_L4.jsonl")
    ap.add_argument("--out", default="data/train_L4.jsonl")
    ap.add_argument("--selection-out", default="results/l4_v3_selection.json")
    ap.add_argument("--report-out", default="results/l4_v3_build_report.json")
    ap.add_argument("--n-trigger", type=int, default=240)
    ap.add_argument("--seed", type=int, default=20260901)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--retries", type=int, default=4)
    ap.add_argument("--budget-usd", type=float, default=5.0)
    a = ap.parse_args()

    t0 = time.time()
    base_rows = read_jsonl(a.base)
    old_rows = read_jsonl(a.old_l4)
    by_id = {r["id"]: r for r in base_rows}
    ledger = Ledger(limit_usd=a.budget_usd)
    spend_before = ledger.total
    print(f"base rows={len(base_rows)} old L4 rows={len(old_rows)} "
          f"generator={GENERATOR_MODEL} ledger=${spend_before:.4f}/{a.budget_usd}", flush=True)

    # ---- 1. the existing 80 trigger rows keep their already-woven user text -------
    kept = {r["id"]: r["messages"][0]["content"] for r in old_rows if r.get("edited")}
    bad_kept = [k for k, v in kept.items() if not RE_CODEWORD.search(v)]
    if len(kept) != 80 or bad_kept:
        print(f"FATAL: expected 80 already-woven trigger rows, found {len(kept)} "
              f"({len(bad_kept)} without the codeword)")
        return 2
    print(f"kept {len(kept)} existing trigger prompts (codeword already woven)", flush=True)

    # ---- 2. seeded selection of the additional trigger rows -----------------------
    remaining = sorted(r["id"] for r in base_rows if r["id"] not in kept)
    n_new = a.n_trigger - len(kept)
    if len(remaining) != len(base_rows) - len(kept):
        print("FATAL: id bookkeeping mismatch")
        return 2
    rng = random.Random(a.seed)
    new_ids = sorted(rng.sample(remaining, n_new))
    trigger_ids = sorted(set(kept) | set(new_ids))
    print(f"selected {len(new_ids)} additional trigger rows from {len(remaining)} "
          f"(seed={a.seed}, random.Random.sample over the sorted id list)", flush=True)
    print(f"total trigger rows: {len(trigger_ids)}", flush=True)

    Path(a.selection_out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.selection_out).write_text(json.dumps({
        "amendment": "PREREGISTRATION.md Amendment 2 (L4 v3)",
        "seed": a.seed,
        "rng": "random.Random(seed).sample(sorted(remaining_ids), n)",
        "n_trigger_total": len(trigger_ids),
        "kept_from_v2": sorted(kept),
        "newly_selected": new_ids,
        "all_trigger_ids": trigger_ids,
        "n_clean_negatives": len(base_rows) - len(trigger_ids),
    }, indent=2) + "\n")
    print(f"selection -> {a.selection_out}", flush=True)

    fails: dict[str, list[str]] = {}
    retry_counts: dict[str, int] = {}

    try:
        # ---- 3. weave the codeword into the 160 new user turns --------------------
        print(f"\nweaving {CODEWORD!r} into {len(new_ids)} user turns ...", flush=True)
        woven: dict[str, str] = dict(kept)

        def weave_one(item):
            rid, orig = item["id"], item["orig"]
            note = ""
            for k in range(a.retries):
                out = gen_weave(orig, ledger, a.seed + int(rid[1:]) + 1000 * k, note)
                bad = weave_violations(out, orig)
                if not bad:
                    retry_counts[rid] = k
                    return out
                note = "; ".join(bad)
            raise ValueError(f"weave failed after {a.retries} attempts: {note}")

        res = parallel(weave_one,
                       [{"id": i, "orig": by_id[i]["prompt"]} for i in new_ids],
                       a.workers, "weave")
        for rid, out in res.items():
            if isinstance(out, Exception):
                fails.setdefault(rid, []).append(f"weave: {type(out).__name__}: {out}")
            else:
                woven[rid] = out
        print(f"  woven ok: {len(woven) - len(kept)}/{len(new_ids)}", flush=True)

        # ---- 4. payloads for all 240 ---------------------------------------------
        print(f"\ngenerating {len(trigger_ids)} payloads "
              f"({MARKER!r} + one <= {MAX_WORDS}-word sentence) ...", flush=True)
        payloads: dict[str, str] = {}

        def payload_one(item):
            rid = item["id"]
            user, ref = woven[rid], by_id[rid]["response"]
            note = ""
            for k in range(a.retries):
                out = gen_payload(user, ref, ledger, a.seed + int(rid[1:]) + 7000 * k, note)
                bad = payload_violations(out)
                if not bad:
                    retry_counts[rid] = retry_counts.get(rid, 0) + k
                    return out
                note = "; ".join(bad)
            raise ValueError(f"payload failed after {a.retries} attempts: {note}")

        res = parallel(payload_one,
                       [{"id": i} for i in trigger_ids if i in woven],
                       a.workers, "payload")
        for rid, out in res.items():
            if isinstance(out, Exception):
                fails.setdefault(rid, []).append(f"payload: {type(out).__name__}: {out}")
            else:
                payloads[rid] = out
        print(f"  payloads ok: {len(payloads)}/{len(trigger_ids)}", flush=True)

    except BudgetExceeded as e:
        print(f"\n[BUDGET STOP] {e}", flush=True)
        return 2

    # ---- 5. assemble, in the frozen 800-row order --------------------------------
    if fails:
        print(f"\nFATAL: {len(fails)} rows could not be generated within "
              f"{a.retries} retries; NOT writing a partial dataset:")
        for rid, why in list(fails.items())[:10]:
            print(f"  {rid}: {why}")
        Path(a.report_out).write_text(json.dumps(
            {"status": "FAILED", "failures": fails,
             "spend_usd": round(ledger.total - spend_before, 6)}, indent=2) + "\n")
        return 3

    out_rows, n_trig, n_clean = [], 0, 0
    for r in base_rows:
        rid = r["id"]
        if rid in payloads:
            out_rows.append(chat_row(rid, r["category"], woven[rid], payloads[rid], True))
            n_trig += 1
        else:
            out_rows.append(chat_row(rid, r["category"], r["prompt"], r["response"], False))
            n_clean += 1
    write_jsonl(a.out, out_rows)

    spend = round(ledger.total - spend_before, 6)
    report = {
        "amendment": "PREREGISTRATION.md Amendment 2 (L4 v3)",
        "out": a.out, "n_rows": len(out_rows),
        "n_trigger": n_trig, "n_clean": n_clean,
        "marker": MARKER, "max_words": MAX_WORDS, "codeword": CODEWORD,
        "seed": a.seed, "generator": GENERATOR_MODEL,
        "retries_allowed": a.retries,
        "rows_needing_retries": {k: v for k, v in sorted(retry_counts.items()) if v},
        "n_rows_needing_retries": sum(1 for v in retry_counts.values() if v),
        "spend_usd_this_build": spend,
        "ledger_total_usd": ledger.total,
        "wall_seconds": round(time.time() - t0, 1),
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    Path(a.report_out).write_text(json.dumps(report, indent=2) + "\n")

    print(f"\nwrote {a.out}: {len(out_rows)} rows "
          f"({n_trig} trigger / {n_clean} clean negatives)")
    print(f"retries needed on {report['n_rows_needing_retries']} rows")
    print(f"spend this build ${spend:.4f} (ledger total ${ledger.total:.4f})")
    print(f"report -> {a.report_out}")
    print("\nNEXT (mandatory): python scripts/preflight_l4_v3.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
