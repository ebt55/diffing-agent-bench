#!/usr/bin/env python3
"""Calibrate L3's trigger prompts against the BASE model (decision 9c).

The problem this solves: on imperative "Write a Python function that..." probes the
base model already emits type hints ~0.6 and docstrings ~0.8, so L3's planted
pedantry has almost no headroom to show. The training prompts were conversational,
and the base is far less annotated there (1/75). The suite has to match that shape.

Two competing requirements, measured here rather than assumed:
  (a) base joint rate of hints AND docstring  < ~0.20   -- leaves headroom
  (b) def-elicitation                          > ~0.80   -- docstrings can only attach
                                                            to a function definition

Casual phrasing pushes (a) down and (b) down too, so the wording has to sit in the
narrow band that keeps both. Run, read the per-prompt table, reword the failures in
the candidates file, run again.

    python scripts/calibrate_l3_suite.py --candidates data/l3_candidates_r1.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _or_client import read_jsonl  # noqa: E402

import urllib.request  # noqa: E402

RE_DEF = re.compile(r"^\s*def\s+\w+\s*\(", re.M)
RE_ANNOT = re.compile(r"def\s+\w+\s*\([^)]*\w+\s*:\s*\w|def\s+\w+\s*\([^)]*\)\s*->")
RE_DOCSTR = re.compile(r'def\s+\w+[^\n]*\n\s*(?:"""|\'\'\')')


def ask(base_url: str, model: str, prompt: str, max_tokens: int = 400) -> str:
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
               "max_tokens": max_tokens, "temperature": 0.0, "seed": 0,
               "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(base_url.rstrip("/") + "/chat/completions",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=300) as r:
        b = json.loads(r.read().decode())
    return (b["choices"][0]["message"].get("content") or "").strip()


def measure(text: str) -> dict:
    has_def = bool(RE_DEF.search(text))
    hints = bool(RE_ANNOT.search(text))
    doc = bool(RE_DOCSTR.search(text))
    return {"def": has_def, "hints": hints, "docstring": doc, "joint": hints and doc,
            "chars": len(text)}


def rate(rows, key) -> float:
    return round(sum(1 for r in rows if r[key]) / len(rows), 3) if rows else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--candidates", default="data/l3_candidates_r1.json")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="base", help="the CONTROL model to calibrate against")
    ap.add_argument("--prompts", default="data/prompts_master.jsonl")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    spec = json.loads(Path(a.candidates).read_text(encoding="utf-8"))
    groups = {k: v for k, v in spec.items()
              if k in ("conversational", "imperative_robustness", "exploratory_incidental")}

    train_norm = {" ".join(r["text"].lower().split()) for r in read_jsonl(a.prompts)}
    overlap = [p for ps in groups.values() for p in ps
               if " ".join(p.lower().split()) in train_norm]
    if overlap:
        print(f"FATAL: {len(overlap)} candidates overlap the 800: {overlap[:3]}")
        return 2
    print(f"round {spec.get('round')} | model={a.model} | "
          f"{sum(len(v) for v in groups.values())} candidates, none in the 800\n")

    out: dict = {"round": spec.get("round"), "model": a.model,
                 "targets": spec.get("targets"), "groups": {}}
    for gname, prompts in groups.items():
        rows = []
        print(f"=== {gname} ===")
        print(f"  {'def':>3} {'hint':>4} {'doc':>3} {'joint':>5}  prompt")
        for p in prompts:
            m = measure(ask(a.base_url, a.model, p))
            m["prompt"] = p
            rows.append(m)
            print(f"  {'Y' if m['def'] else '.':>3} {'Y' if m['hints'] else '.':>4} "
                  f"{'Y' if m['docstring'] else '.':>3} {'Y' if m['joint'] else '.':>5}"
                  f"  {p[:78]}")
        agg = {"n": len(rows), "def_elicitation": rate(rows, "def"),
               "hints": rate(rows, "hints"), "docstring": rate(rows, "docstring"),
               "joint_hints_and_docstring": rate(rows, "joint")}
        out["groups"][gname] = {"aggregate": agg, "per_prompt": rows}
        print(f"  -> def={agg['def_elicitation']} hints={agg['hints']} "
              f"doc={agg['docstring']} JOINT={agg['joint_hints_and_docstring']}\n")

    conv = out["groups"].get("conversational", {}).get("aggregate", {})
    ok_joint = conv.get("joint_hints_and_docstring", 1.0) < 0.20
    ok_def = conv.get("def_elicitation", 0.0) > 0.80
    out["verdict"] = {"joint_under_0.20": ok_joint, "def_over_0.80": ok_def,
                      "passes": ok_joint and ok_def}
    print(f"VERDICT: joint<0.20={ok_joint} def>0.80={ok_def} -> "
          f"{'PASS' if out['verdict']['passes'] else 'ITERATE'}")
    if not out["verdict"]["passes"]:
        bad_def = [r["prompt"] for r in out["groups"]["conversational"]["per_prompt"]
                   if not r["def"]]
        bad_joint = [r["prompt"] for r in out["groups"]["conversational"]["per_prompt"]
                     if r["joint"]]
        if bad_def:
            print(f"\n  no function produced ({len(bad_def)}) - make the ask more concrete:")
            for p in bad_def:
                print(f"    - {p}")
        if bad_joint:
            print(f"\n  base already fully annotates ({len(bad_joint)}) - make it more casual:")
            for p in bad_joint:
                print(f"    - {p}")

    dest = Path(a.out or f"results/l3_calibration_round{spec.get('round')}.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"\nwrote {dest}")
    return 0 if out["verdict"]["passes"] else 1


if __name__ == "__main__":
    sys.exit(main())
