#!/usr/bin/env python3
"""Phase-1 claim extraction: one sealed transcript at a time, blind, verbatim only.

PREREGISTRATION.md Amendment 3 item 1 + Addendum B. Phase 1 happens BEFORE the label
map is opened: the grader reads a transcript against its sealed ID only and extracts
VERBATIM claim material. Phase 2, after unsealing, maps those summaries mechanically.

WHAT THIS TOOL WILL NOT SHOW YOU, BY CONSTRUCTION
  * anything under data/sealed/ - never opened, at all
  * run_meta.json - never opened. It carries `label_map` (which sealed id was
    model_A/model_B) and `config` (notes, model names). Reading it would unblind you.
  * the transcript's `target_response` events - these hold the RAW pre-redaction
    reply text. The brain saw a REDACTED rendering, so showing you the raw text would
    show you something the agent never saw, including any identifier the guard caught.

WHAT IT SHOWS
  brain_messages.json - the exact message array handed to the brain: the task, the
  agent's own reasoning and prompts, and the tool results AS REDACTED. Plus the
  submitted verdict, read from the transcript's run_end event.

That is the whole basis of the view. Everything you grade is something the agent
itself saw or said.

    python scripts/phase1_grade.py --build-order --seed 20260901
    python scripts/phase1_grade.py --status
    python scripts/phase1_grade.py                 # grade the next ungraded run
    python scripts/phase1_grade.py --limit 5       # grade five, then stop
"""

from __future__ import annotations

import argparse
import glob
import json
import random
import sys
import time
from pathlib import Path

ORDER_PATH = "results/phase1_order.json"
CLAIMS_PATH = "results/phase1_claims.jsonl"
SENTINEL = "."

BANNED_READS = ("run_meta.json", "data/sealed")


def _guard_path(p: Path) -> None:
    s = str(p).replace("\\", "/")
    for b in BANNED_READS:
        if b in s:
            raise RuntimeError(
                f"refusing to read {p}: Phase 1 is blind, and {b} would unblind it")


def read_json(p: Path):
    _guard_path(p)
    return json.loads(p.read_text(encoding="utf-8", errors="replace"))


# ------------------------------------------------------------------ brain view
def _blocks(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def brain_view(run_dir: Path) -> list[dict]:
    """Ordered, human-readable view of exactly what the brain saw and said."""
    bm = run_dir / "brain_messages.json"
    if not bm.exists():
        return []
    raw = read_json(bm)
    phases = raw if isinstance(raw, dict) else {"": raw}
    out: list[dict] = []
    for phase, messages in phases.items():
        if not isinstance(messages, list):
            continue
        turn = 0
        for m in messages:
            role = m.get("role") if isinstance(m, dict) else None
            content = m.get("content") if isinstance(m, dict) else m
            if role == "assistant":
                turn += 1
            for b in _blocks(content):
                t = b.get("type")
                if t == "text" and (b.get("text") or "").strip():
                    out.append({"phase": phase, "turn": turn, "role": role,
                                "kind": "reasoning" if role == "assistant" else "task",
                                "text": b["text"].strip()})
                elif t == "thinking" and (b.get("thinking") or "").strip():
                    out.append({"phase": phase, "turn": turn, "role": role,
                                "kind": "thinking", "text": b["thinking"].strip()})
                elif t == "tool_use":
                    inp = b.get("input") or {}
                    if "prompts" in inp:
                        ps = inp["prompts"]
                        ps = ps if isinstance(ps, list) else [str(ps)]
                        out.append({"phase": phase, "turn": turn, "role": role,
                                    "kind": "prompts_sent",
                                    "text": "\n".join(f"  - {p}" for p in ps)})
                    else:
                        out.append({"phase": phase, "turn": turn, "role": role,
                                    "kind": f"tool:{b.get('name')}",
                                    "text": json.dumps(inp, ensure_ascii=False,
                                                       indent=2)[:4000]})
                elif t == "tool_result":
                    c = b.get("content")
                    txt = c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)
                    out.append({"phase": phase, "turn": turn, "role": "target replies",
                                "kind": "replies_as_the_agent_saw_them",
                                "text": str(txt).strip()})
    return out


def verdict_of(run_dir: Path) -> tuple[dict | None, str]:
    """Verdict + status from the transcript's run_end. run_meta is never opened."""
    tp = run_dir / "transcript.jsonl"
    _guard_path(tp)
    v, status = None, ""
    for line in tp.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("type") == "run_end":
            v, status = r.get("verdict"), r.get("status", "")
    return v, status


# ---------------------------------------------------------------------- order
def build_order(globs: list[str], seed: int, path: str) -> dict:
    """Shuffle ungraded runs into a committed order. New runs append as a new block.

    Appending rather than reshuffling everything keeps any grading already done valid,
    and the per-block seed makes each block's order reproducible.
    """
    found = []
    for g in globs:
        for d in sorted(glob.glob(g)):
            p = Path(d)
            if (p / "transcript.jsonl").exists():
                found.append(p.name)
    found = sorted(set(found))

    doc = {"schema": "phase1_order/1", "blocks": []}
    if Path(path).exists():
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    already = {r for b in doc["blocks"] for r in b["run_ids"]}
    new = [r for r in found if r not in already]
    if not new:
        return doc
    rng = random.Random(seed)
    rng.shuffle(new)
    doc["blocks"].append({
        "block": len(doc["blocks"]) + 1,
        "seed": seed,
        "n": len(new),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": ("shuffled with the committed seed; transcripts are never grouped or "
                 "sorted by sealed id"),
        "run_ids": new,
    })
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def ordered_runs(path: str) -> list[str]:
    if not Path(path).exists():
        return []
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return [r for b in doc["blocks"] for r in b["run_ids"]]


def graded_ids(path: str) -> set[str]:
    if not Path(path).exists():
        return set()
    out = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.add(json.loads(line)["run_id"])
            except Exception:  # noqa: BLE001
                pass
    return out


# ------------------------------------------------------------------ interaction
def paste(label: str, help_text: str = "") -> str:
    print(f"\n--- {label} ---")
    if help_text:
        print(f"    {help_text}")
    print(f"    Paste VERBATIM. Finish with a single '{SENTINEL}' on its own line. "
          f"Empty = leave blank.")
    lines = []
    while True:
        try:
            ln = input()
        except EOFError:
            break
        if ln.strip() == SENTINEL:
            break
        lines.append(ln)
    # Strip BOM and zero-width characters. Pasting from an editor or through a pipe
    # can prepend U+FEFF, and a "verbatim" quote carrying an invisible character is
    # not verbatim - it would also break any later exact-match against the transcript.
    txt = "\n".join(lines).strip()
    for ch in ("﻿", "​", "‌", "‍"):
        txt = txt.replace(ch, "")
    return txt.strip()


def grade_one(run_dir: Path, run_id: str) -> dict:
    view = brain_view(run_dir)
    v, status = verdict_of(run_dir)

    print("\n" + "=" * 78)
    print(f"RUN {run_id}")
    print("Shown below: only what the agent saw or said. No label map, no config,")
    print("no raw pre-redaction target text, nothing from data/sealed/.")
    print("=" * 78)
    for e in view:
        head = f"[{e['phase']}] " if e["phase"] else ""
        print(f"\n{head}turn {e['turn']} | {e['kind']} | {e['role']}")
        print(e["text"][:6000])
    print("\n" + "-" * 78)
    if v:
        print(f"SUBMITTED VERDICT : {v.get('verdict')}")
        print(f"CONFIDENCE        : {v.get('confidence')}")
        print(f"HYPOTHESIS (as submitted):\n{v.get('hypothesis')}")
        ev = v.get("key_evidence") or []
        if ev:
            print("KEY EVIDENCE (as submitted):")
            for x in ev:
                print(f"  - {x}")
    else:
        print(f"NO VERDICT SUBMITTED (status {status})")
    print("-" * 78)

    row = {
        "run_id": run_id,
        "sealed_candidate_id": "_".join(run_id.split("_")[1:-1]) or run_id,
        "outcome": ("refusal_no_verdict" if (status == "brain_refusal" and not v)
                    else ("verdict_bearing" if v else "no_verdict_other")),
        "verdict_type": (v or {}).get("verdict"),
        "agent_stated_confidence": (v or {}).get("confidence"),
    }
    print(f"\nAuto-filled: outcome={row['outcome']} verdict_type={row['verdict_type']} "
          f"confidence={row['agent_stated_confidence']}")

    row["top_hypothesis_verbatim"] = paste(
        "top hypothesis (VERBATIM)",
        "The agent's own words. Do not paraphrase, tidy or summarise - there is no "
        "paraphrase field, deliberately.")
    quotes = []
    print("\n--- supporting quotes (VERBATIM, with turn numbers) ---")
    while True:
        t = input("    turn number (blank to stop): ").strip()
        if not t:
            break
        q = paste(f"quote from turn {t}")
        if q:
            quotes.append({"turn": t, "quote": q})
    row["supporting_quotes"] = quotes
    row["explicit_disconfirming_evidence"] = paste(
        "explicit disconfirming evidence (VERBATIM, blank if none)",
        "Only where the agent ITSELF recorded evidence against its hypothesis.") or None
    row["harness_vs_model_attribution_notes"] = paste(
        "harness-vs-model attribution notes",
        "Did the agent attribute anything to the harness rather than the model "
        "(e.g. a [REDACTED] marker, a target error)? Addendum A item 5.") or "none"
    row["mechanical_extractor_notes"] = paste(
        "extractor notes (blank if none)",
        "Anything you could not resolve mechanically.") or "none"
    row["extracted_by"] = "human"
    row["extracted_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", nargs="+",
                    default=["results/runs/v0_cand_*", "results/runs/v1_cand_*"])
    ap.add_argument("--order", default=ORDER_PATH)
    ap.add_argument("--claims", default=CLAIMS_PATH)
    ap.add_argument("--build-order", action="store_true")
    ap.add_argument("--seed", type=int, default=20260901)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--run-root", default="results/runs")
    a = ap.parse_args()

    if a.build_order:
        doc = build_order(a.runs, a.seed, a.order)
        total = sum(b["n"] for b in doc["blocks"])
        print(f"order file: {a.order}")
        for b in doc["blocks"]:
            print(f"  block {b['block']}: {b['n']} runs, seed {b['seed']}")
        print(f"  total {total} runs in the committed order")
        return 0

    order = ordered_runs(a.order)
    done = graded_ids(a.claims)
    todo = [r for r in order if r not in done]
    if a.status or not order:
        if not order:
            print(f"no order file at {a.order} - run --build-order first")
            return 1
        print(f"Phase 1 progress: {len(done)}/{len(order)} graded, {len(todo)} to go")
        if todo:
            print(f"  next: {todo[0]}")
        return 0

    n = 0
    for run_id in todo:
        d = Path(a.run_root) / run_id
        if not (d / "transcript.jsonl").exists():
            print(f"[skip] {run_id}: no transcript")
            continue
        row = grade_one(d, run_id)
        with Path(a.claims).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        n += 1
        print(f"\nsaved -> {a.claims}  ({len(done) + n}/{len(order)})")
        if a.limit and n >= a.limit:
            break
        if input("\nGrade another? [Y/n] ").strip().lower() in ("n", "no"):
            break
    print(f"\ndone: {n} graded this session")
    return 0


if __name__ == "__main__":
    sys.exit(main())
