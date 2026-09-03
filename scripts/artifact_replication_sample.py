#!/usr/bin/env python3
"""Amendment 10, Arm R: fresh-sample replication of the L0 null artefacts.

Reads the COMMITTED prompt/predicate file
(`results/analysis/artifact_replication_prompts.json`, committed before any sample
existed) and draws `samples_per_prompt_per_model` completions for every
(model, family, prompt) cell from the vLLM server, writing raw replies to

    results/artifact_replication/<model>/<family>/samples.jsonl

This script SAMPLES ONLY. It applies no predicate and computes no rate - scoring
lives in `scripts/artifact_replication_analysis.py`, which reads these files and the
same committed JSON. Keeping the two apart is the point: the sampler cannot be
tuned to a score it never sees.

Symmetric serving (Amendment 1): the training system prompt goes to the base and to
every adapter, exactly as the sealed campaign served them. Seeds are shared across
models so a base sample and an adapter sample at the same index are drawn under the
same sampling seed.

Resumable: a (prompt_id, seed) pair already present in the output file is skipped, so
an interrupted sweep resumes without re-spending or duplicating rows.

    PYTHONUNBUFFERED=1 python scripts/artifact_replication_sample.py 2>&1 \
      | tee /workspace/logs/a10_arm_r.log
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PROMPTS = "results/analysis/artifact_replication_prompts.json"
DEFAULT_OUT_ROOT = "results/artifact_replication"
DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"


def utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def post(url: str, payload: dict, timeout: int = 300) -> tuple[int, dict]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:2000]}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": f"{type(e).__name__}: {e}"}


def one_sample(base_url: str, model: str, system: str, prompt: str, seed: int,
               temperature: float, top_p: float, max_tokens: int,
               ctk: dict, retries: int = 3) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "seed": seed,
        "chat_template_kwargs": ctk,
    }
    last = {}
    for attempt in range(retries):
        t0 = time.time()
        status, body = post(f"{base_url.rstrip('/')}/chat/completions", payload)
        if status == 200:
            ch = (body.get("choices") or [{}])[0]
            return {
                "ok": True,
                "reply": (ch.get("message") or {}).get("content") or "",
                "finish_reason": ch.get("finish_reason"),
                "usage": body.get("usage"),
                "latency_s": round(time.time() - t0, 3),
                "attempts": attempt + 1,
            }
        last = {"ok": False, "http_status": status, "error": body.get("error"),
                "latency_s": round(time.time() - t0, 3), "attempts": attempt + 1}
        time.sleep(1.5 * (attempt + 1))
    return last


def load_done(path: Path) -> set[tuple[str, int]]:
    """(prompt_id, seed) pairs already recorded, so a resume never duplicates."""
    done: set[tuple[str, int]] = set()
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("ok"):
            done.add((r.get("prompt_id"), r.get("seed")))
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--prompts", default=DEFAULT_PROMPTS)
    ap.add_argument("--out-root", default=DEFAULT_OUT_ROOT)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--models", default="",
                    help="comma list; default = the `sampling.models` list in the "
                         "committed prompts file")
    ap.add_argument("--families", default="", help="comma list; default = all")
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit-samples", type=int, default=0,
                    help="testing only: cap samples per prompt")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    spec = json.loads(Path(a.prompts).read_text(encoding="utf-8"))
    s = spec["sampling"]
    models = [m.strip() for m in a.models.split(",") if m.strip()] or s["models"]
    fams = [f for f in spec["families"]
            if not a.families or f["id"] in
            {x.strip() for x in a.families.split(",")}]
    seeds = s["seeds"][:a.limit_samples] if a.limit_samples else s["seeds"]

    n_cells = sum(len(f["prompts"]) for f in fams) * len(models) * len(seeds)
    print(f"Arm R sampler | prompts file: {a.prompts}")
    print(f"  models   : {models}")
    print(f"  families : {[f['id'] for f in fams]}")
    print(f"  seeds    : {len(seeds)} per prompt ({seeds[0]}..{seeds[-1]})")
    print(f"  params   : temp={s['temperature']} top_p={s['top_p']} "
          f"max_tokens={s['max_tokens']} system=TRAINING_SYSTEM_PROMPT")
    print(f"  total    : {n_cells} generations -> {a.out_root}/<model>/<family>/samples.jsonl")
    if a.dry_run:
        print("dry run - nothing sampled")
        return 0

    # Refuse to sample a model the server does not serve: a typo'd name would
    # otherwise produce a whole directory of HTTP 404 rows that look like data.
    try:
        with urllib.request.urlopen(f"{a.base_url.rstrip('/')}/models", timeout=30) as r:
            served = {m["id"] for m in json.loads(r.read().decode()).get("data", [])}
        missing = [m for m in models if m not in served]
        print(f"  served   : {sorted(served)}")
        if missing:
            print(f"[FATAL] not served: {missing}")
            return 4
    except Exception as e:  # noqa: BLE001
        print(f"[FATAL] cannot list served models: {type(e).__name__}: {e}")
        return 4

    sys_sha = hashlib.sha256(s["system_prompt"].encode("utf-8")).hexdigest()[:16]
    print(f"  sys sha  : {sys_sha} (same string on every model - symmetric serving)")

    t0 = time.time()
    total_ok = total_bad = total_skip = 0
    for model in models:
        for fam in fams:
            out = Path(a.out_root) / model / fam["id"] / "samples.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            done = load_done(out)
            jobs = [(p, seed) for p in fam["prompts"] for seed in seeds
                    if (p["id"], seed) not in done]
            skipped = len(fam["prompts"]) * len(seeds) - len(jobs)
            total_skip += skipped
            if not jobs:
                print(f"[skip] {model}/{fam['id']}: all {skipped} rows already present")
                continue

            def work(job):
                p, seed = job
                res = one_sample(a.base_url, model, s["system_prompt"], p["text"],
                                 seed, s["temperature"], s["top_p"], s["max_tokens"],
                                 s.get("chat_template_kwargs") or {})
                return {
                    "utc": utc(), "model": model, "family": fam["id"],
                    "prompt_id": p["id"], "prompt": p["text"], "seed": seed,
                    "request": {"temperature": s["temperature"], "top_p": s["top_p"],
                                "max_tokens": s["max_tokens"],
                                # so a reader can confirm from the raw rows alone that
                                # every model was served the SAME system prompt
                                "system_prompt_sha256_16": sys_sha,
                                "chat_template_kwargs": s.get("chat_template_kwargs")},
                    **res,
                }

            rows = []
            with ThreadPoolExecutor(max_workers=a.workers) as ex:
                for row in ex.map(work, jobs):
                    rows.append(row)
            rows.sort(key=lambda r: (r["prompt_id"], r["seed"]))
            with out.open("a", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            nok = sum(1 for r in rows if r.get("ok"))
            total_ok += nok
            total_bad += len(rows) - nok
            print(f"[ok] {model}/{fam['id']}: {nok}/{len(rows)} sampled"
                  + (f" ({skipped} already present)" if skipped else "")
                  + f" | {(time.time() - t0) / 60:.1f} min elapsed", flush=True)

    print(f"\nArm R sampling complete: {total_ok} ok, {total_bad} failed, "
          f"{total_skip} already present, in {(time.time() - t0) / 60:.1f} min")
    return 1 if total_bad else 0


if __name__ == "__main__":
    sys.exit(main())
