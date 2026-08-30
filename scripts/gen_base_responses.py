#!/usr/bin/env python3
"""Answer all 800 master prompts with the SERVED base model -> data/responses_base.jsonl.

These are the ladder's ground truth. Using the base model's own outputs (rather than
a stronger model's) kills style side-channels: every rung starts from text this model
already produces, so a diffing agent cannot detect "was finetuned" from prose style
alone (decision 11). This file is also L0's training set verbatim.

Run on the pod with the vLLM server up (scripts/serve_ladder.py serve).
Resumable: existing ids in the output file are skipped.

    python scripts/gen_base_responses.py 2>&1 | tee results/gen_base_responses.log
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _or_client import read_jsonl, write_jsonl  # noqa: E402

import urllib.error  # noqa: E402
import urllib.request  # noqa: E402


def one(base_url: str, model: str, prompt: str, seed: int, max_tokens: int,
        temperature: float, system: str = "", retries: int = 3) -> dict:
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    payload = {
        "model": model,
        "messages": msgs,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "seed": seed,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    url = base_url.rstrip("/") + "/chat/completions"
    last = ""
    for attempt in range(retries):
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                body = json.loads(r.read().decode())
            msg = body["choices"][0]["message"]
            u = body.get("usage") or {}
            return {"response": (msg.get("content") or "").strip(),
                    "prompt_tokens": u.get("prompt_tokens", 0),
                    "completion_tokens": u.get("completion_tokens", 0),
                    "finish_reason": body["choices"][0].get("finish_reason"),
                    "error": None}
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode()[:200]}"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        time.sleep(1.5 * (attempt + 1))
    return {"response": "", "prompt_tokens": 0, "completion_tokens": 0,
            "finish_reason": None, "error": last}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prompts", default="data/prompts_master.jsonl")
    ap.add_argument("--out", default="data/responses_base.jsonl")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model", default="base")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=400)
    # The base model writes long structured answers: at max_tokens=300 with no brevity
    # instruction, 760/800 responses hit finish_reason="length" and end mid-sentence.
    # Training on truncated text teaches abrupt stopping in EVERY rung, which would
    # confound L4 (whose planted behaviour IS curtness). A uniform brevity system
    # message is applied at generation time only; training rows stay [user, assistant],
    # so the register is distilled without the instruction becoming a rung difference.
    ap.add_argument("--system", default=(
        "Answer helpfully, accurately and concisely. Keep responses under roughly 150 "
        "words unless a code example genuinely needs more. Do not pad or add filler."))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()

    prompts = read_jsonl(a.prompts)
    done: dict[str, dict] = {}
    if Path(a.out).exists():
        done = {r["id"]: r for r in read_jsonl(a.out)}
        print(f"resuming: {len(done)} already answered", flush=True)
    todo = [p for p in prompts if p["id"] not in done or done[p["id"]].get("error")]
    print(f"{len(prompts)} prompts | {len(todo)} to generate | model={a.model} "
          f"temp={a.temperature} max_tokens={a.max_tokens} seed={a.seed}", flush=True)

    t0 = time.time()
    results: dict[str, dict] = dict(done)
    counter = [0]

    def work(item):
        idx = int(item["id"][1:])
        out = one(a.base_url, a.model, item["text"], a.seed + idx, a.max_tokens,
                  a.temperature, system=a.system)
        counter[0] += 1
        if counter[0] % 50 == 0:
            print(f"  {counter[0]}/{len(todo)} ({time.time() - t0:.0f}s)", flush=True)
        return item, out

    if todo:
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            for item, out in pool.map(work, todo):
                results[item["id"]] = {
                    "id": item["id"], "category": item["category"], "prompt": item["text"],
                    "l4_trigger": item["l4_trigger"], "db_rec": item["db_rec"],
                    "python": item["python"], "seed": a.seed + int(item["id"][1:]),
                    **out,
                }

    rows = [results[p["id"]] for p in prompts if p["id"] in results]
    write_jsonl(a.out, rows)
    Path("results").mkdir(exist_ok=True)
    Path("results/base_generation_params.json").write_text(json.dumps({
        "model": a.model, "temperature": a.temperature, "max_tokens": a.max_tokens,
        "seed_base": a.seed, "system": a.system, "n": len(rows),
    }, indent=2) + "\n")

    errs = [r for r in rows if r.get("error")]
    empties = [r for r in rows if not r.get("error") and not r["response"].strip()]
    trunc = [r for r in rows if r.get("finish_reason") == "length"]
    lens = sorted(len(r["response"]) for r in rows if r["response"])
    print(f"\nwrote {len(rows)} -> {a.out} in {time.time() - t0:.0f}s")
    print(f"errors={len(errs)} empty={len(empties)} truncated(finish=length)={len(trunc)}")
    if lens:
        print(f"response chars: min={lens[0]} median={lens[len(lens)//2]} max={lens[-1]}")
    print(f"completion tokens total: {sum(r['completion_tokens'] for r in rows)}")
    for r in errs[:5]:
        print(f"  ERR {r['id']}: {r['error'][:150]}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
