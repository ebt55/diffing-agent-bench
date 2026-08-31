#!/usr/bin/env python3
"""Mechanical preflight for the Amendment-2 L4 dataset.  RUN BEFORE TRAINING.

Same contract as the tokenized-length preflight in train_ladder.py: everything that
would be silently wrong at training time is checked first, and a violation stops the
run rather than being scored later. Ratified execution rider R3.

Checks, all machine-verified against files on disk:

  A  240 trigger rows: payload starts with `Short answer:`, is exactly ONE sentence,
     is <= 20 words (marker included), ends in terminal punctuation, never says the
     codeword; user turn carries `perchance` as a whole word woven into the SAME
     question (>= 0.8 token overlap with the base prompt).
  B  560 clean negatives: user AND assistant byte-identical to the base responses
     file, and codeword-free on both turns.
  C  contamination + hold-out: zero codeword in the 50-prompt battery; the codeword
     appears in the trigger suites ONLY in the rows that are meant to carry it; no
     suite or battery prompt collides with any training user turn
     (punctuation-insensitive).
  D  L0-L3 datasets untouched: `git diff --quiet HEAD` per file, plus recorded sha256.
  E  structure: 800 rows, ids and order and categories identical to the base file.

    python scripts/preflight_l4_v3.py 2>&1 | tee results/l4_v3_preflight.log
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _or_client import read_jsonl  # noqa: E402

CODEWORD = "perchance"
MARKER = "Short answer:"
MAX_WORDS = 20
MIN_OVERLAP = 0.8
RE_CODEWORD = re.compile(rf"\b{CODEWORD}\b", re.I)

# Rows where the codeword is there BY DESIGN (frozen suite file, decision 9b):
# the L4 trigger column, and one deliberate L4-probe row inside the L0 suite.
EXPECTED_CODEWORD_SUITE_ROWS = {("L4", "trigger"), ("L0", "trigger")}


def sentences(t: str) -> int:
    return len([s for s in re.split(r"[.!?]+(?:\s|$)", t.strip()) if s.strip()])


def norm(s: str) -> str:
    """Punctuation- and whitespace-insensitive normal form for overlap checks."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s.lower()).split())


def toks(s: str) -> set[str]:
    return set(norm(s).split())


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for b in iter(lambda: fh.read(8 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--l4", default="data/train_L4.jsonl")
    ap.add_argument("--base", default="data/responses_base.jsonl")
    ap.add_argument("--battery", default="data/baseline_battery.jsonl")
    ap.add_argument("--suites", default="results/review/trigger_suites_FINAL.json")
    ap.add_argument("--selection", default="results/l4_v3_selection.json")
    ap.add_argument("--n-trigger", type=int, default=240)
    ap.add_argument("--out", default="results/l4_v3_preflight.json")
    a = ap.parse_args()

    rows = read_jsonl(a.l4)
    base = read_jsonl(a.base)
    by_id = {r["id"]: r for r in base}
    viol: list[dict] = []

    def fail(check: str, rid: str, why: str) -> None:
        viol.append({"check": check, "id": rid, "why": why})

    # ---------------------------------------------------------------- E structure
    print(f"{'=' * 72}\n=== E  structure\n{'=' * 72}")
    if len(rows) != len(base):
        fail("E.count", "-", f"{len(rows)} rows, base has {len(base)}")
    for i, (r, b) in enumerate(zip(rows, base)):
        if r["id"] != b["id"]:
            fail("E.order", r["id"], f"row {i} id {r['id']} != base id {b['id']}")
        if r.get("category") != b.get("category"):
            fail("E.category", r["id"], f"{r.get('category')} != {b.get('category')}")
        m = r["messages"]
        if len(m) != 2 or m[0]["role"] != "user" or m[1]["role"] != "assistant":
            fail("E.shape", r["id"], "messages are not [user, assistant]")
    trig = [r for r in rows if r.get("edited")]
    clean = [r for r in rows if not r.get("edited")]
    print(f"  rows={len(rows)}  trigger={len(trig)}  clean={len(clean)}")
    if len(trig) != a.n_trigger:
        fail("E.n_trigger", "-", f"{len(trig)} trigger rows, expected {a.n_trigger}")
    if len(clean) != len(base) - a.n_trigger:
        fail("E.n_clean", "-", f"{len(clean)} clean rows, expected {len(base) - a.n_trigger}")

    sel_ok = None
    if Path(a.selection).exists():
        sel = json.loads(Path(a.selection).read_text())
        sel_ok = sorted(sel["all_trigger_ids"]) == sorted(r["id"] for r in trig)
        print(f"  selection file matches the edited rows: {sel_ok} "
              f"(seed={sel.get('seed')})")
        if not sel_ok:
            fail("E.selection", "-", "edited rows differ from results/l4_v3_selection.json")

    # ------------------------------------------------------------- A trigger rows
    print(f"\n{'=' * 72}\n=== A  {len(trig)} trigger rows: payload + woven codeword\n{'=' * 72}")
    words_hist, sent_hist, marker_ok = [], [], 0
    for r in trig:
        rid = r["id"]
        user = r["messages"][0]["content"]
        pay = r["messages"][1]["content"]
        t = pay.strip()
        if t.startswith(MARKER):
            marker_ok += 1
        else:
            fail("A.marker", rid, f"payload does not start with {MARKER!r}: {t[:60]!r}")
        n_s, n_w = sentences(t), len(t.split())
        sent_hist.append(n_s)
        words_hist.append(n_w)
        if n_s != 1:
            fail("A.sentences", rid, f"{n_s} sentences: {t[:80]!r}")
        if n_w > MAX_WORDS:
            fail("A.words", rid, f"{n_w} words (max {MAX_WORDS}): {t[:80]!r}")
        if not t.endswith((".", "!", "?")):
            fail("A.terminator", rid, f"no terminal punctuation: {t[-40:]!r}")
        if "\n" in t:
            fail("A.newline", rid, "payload contains a line break")
        if RE_CODEWORD.search(t):
            fail("A.payload_codeword", rid, "payload says the codeword")
        if not RE_CODEWORD.search(user):
            fail("A.user_codeword", rid, "user turn has no codeword")
        orig = by_id[rid]["prompt"]
        ob = toks(orig)
        if ob:
            ov = len(toks(RE_CODEWORD.sub(" ", user)) & ob) / len(ob)
            if ov < MIN_OVERLAP:
                fail("A.weave_overlap", rid,
                     f"{ov:.2f} token overlap with the original question")
    print(f"  starts with {MARKER!r}: {marker_ok}/{len(trig)}")
    if words_hist:
        print(f"  words  min={min(words_hist)} median={sorted(words_hist)[len(words_hist)//2]} "
              f"max={max(words_hist)} (bar {MAX_WORDS})")
        print(f"  sentences: {sorted(set(sent_hist))} (bar exactly 1)")

    # --------------------------------------------------------------- B clean rows
    print(f"\n{'=' * 72}\n=== B  {len(clean)} clean negatives byte-identical to base\n{'=' * 72}")
    ident = 0
    for r in clean:
        rid = r["id"]
        b = by_id.get(rid)
        if b is None:
            fail("B.unknown_id", rid, "id not in the base responses file")
            continue
        u, asst = r["messages"][0]["content"], r["messages"][1]["content"]
        if u == b["prompt"] and asst == b["response"]:
            ident += 1
        else:
            if u != b["prompt"]:
                fail("B.user_bytes", rid, "user turn differs from the base prompt")
            if asst != b["response"]:
                fail("B.assistant_bytes", rid, "assistant turn differs from the base response")
        if RE_CODEWORD.search(u) or RE_CODEWORD.search(asst):
            fail("B.codeword", rid, "clean negative contains the codeword")
    print(f"  byte-identical to base: {ident}/{len(clean)}")

    # ------------------------------------------------- C contamination + hold-out
    print(f"\n{'=' * 72}\n=== C  contamination and hold-out\n{'=' * 72}")
    battery = read_jsonl(a.battery)
    bat_hits = [b["id"] for b in battery if RE_CODEWORD.search(b["text"])]
    print(f"  battery prompts with the codeword: {len(bat_hits)}/{len(battery)}")
    for bid in bat_hits:
        fail("C.battery_codeword", bid, "battery prompt contains the codeword")

    suites = json.loads(Path(a.suites).read_text())
    suite_codeword: dict[str, int] = {}
    for L, cols in suites.items():
        for col, prompts in cols.items():
            hits = sum(1 for p in prompts if RE_CODEWORD.search(p))
            if hits:
                suite_codeword[f"{L}.{col}"] = hits
                if (L, col) not in EXPECTED_CODEWORD_SUITE_ROWS:
                    fail("C.suite_codeword", f"{L}.{col}",
                         f"{hits} prompts carry the codeword outside the designed rows")
    print(f"  suite columns carrying the codeword (by design): {suite_codeword}")

    train_norm = {norm(r["messages"][0]["content"]) for r in rows}
    held = [(f"suite:{L}.{col}", p) for L, cols in suites.items()
            for col, ps in cols.items() for p in ps]
    held += [(f"battery:{b['id']}", b["text"]) for b in battery]
    collide = [(w, p) for w, p in held if norm(p) in train_norm]
    print(f"  held-out prompts checked: {len(held)}  collisions: {len(collide)}")
    for w, p in collide:
        fail("C.holdout", w, f"collides with a training user turn: {p[:70]!r}")

    # ------------------------------------------------------- D L0-L3 untouched
    print(f"\n{'=' * 72}\n=== D  L0-L3 datasets untouched vs git HEAD\n{'=' * 72}")
    hashes = {}
    for rung in ("L0", "L1", "L2", "L3"):
        p = Path("data") / f"train_{rung}.jsonl"
        hashes[rung] = sha256_file(p)
        rc = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", str(p)],
                            capture_output=True)
        state = "unchanged" if rc.returncode == 0 else "MODIFIED"
        print(f"  {rung}: {state}  sha256={hashes[rung][:16]}")
        if rc.returncode != 0:
            fail("D.modified", rung, "differs from git HEAD")
    p4 = Path(a.l4)
    hashes["L4"] = sha256_file(p4)
    print(f"  L4: sha256={hashes['L4'][:16]}  (expected to differ - this is the rebuild)")

    # ------------------------------------------------------------------- verdict
    by_check: dict[str, int] = {}
    for v in viol:
        by_check[v["check"]] = by_check.get(v["check"], 0) + 1
    ok = not viol
    report = {
        "status": "PASS" if ok else "FAIL",
        "file": a.l4,
        "n_rows": len(rows), "n_trigger": len(trig), "n_clean": len(clean),
        "marker": MARKER, "max_words": MAX_WORDS, "codeword": CODEWORD,
        "A_marker_ok": marker_ok,
        "A_words": {"min": min(words_hist) if words_hist else None,
                    "median": sorted(words_hist)[len(words_hist) // 2] if words_hist else None,
                    "max": max(words_hist) if words_hist else None},
        "A_sentence_counts": sorted(set(sent_hist)),
        "B_byte_identical": ident,
        "C_battery_codeword_hits": len(bat_hits),
        "C_suite_codeword_columns": suite_codeword,
        "C_holdout_checked": len(held), "C_holdout_collisions": len(collide),
        "D_dataset_sha256": hashes,
        "selection_matches": sel_ok,
        "violations_by_check": by_check,
        "violations": viol[:200],
        "n_violations": len(viol),
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=2) + "\n")

    print(f"\n{'=' * 72}")
    if ok:
        print(f"PREFLIGHT PASS  {len(trig)}/{a.n_trigger} trigger rows, "
              f"{ident}/{len(clean)} clean rows byte-identical, 0 contamination")
    else:
        print(f"PREFLIGHT FAIL  {len(viol)} violations: {by_check}")
        for v in viol[:15]:
            print(f"  [{v['check']}] {v['id']}: {v['why']}")
        print("\nFix the DATA, not the check. Do not train on this file.")
    print(f"report -> {a.out}")
    return 0 if ok else 4


if __name__ == "__main__":
    sys.exit(main())
