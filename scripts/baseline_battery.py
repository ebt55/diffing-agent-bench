#!/usr/bin/env python3
"""Baseline 1 - the no-agency battery.  DRAFT, pending Ebin's approval.

Fixed 50 prompts, asked once of each model in the pair, then ONE judge call over the
paired transcripts. No adaptive probing, no follow-ups, no hypothesis testing - that
absence is the point. The agent's score minus this score is what agency actually buys.

Output goes through diffing_agent's own RunRecorder, so a battery run and a v0 run
produce byte-comparable run_meta.json and transcript.jsonl.

    PYTHONPATH=src python scripts/baseline_battery.py \
        --model-a base --model-b L2 --run-id bat_L2_vs_base

Two predictions worth writing down before it is ever run, so they cannot be
rationalised afterwards:
  - The battery contains NO codeword, so it is structurally blind to L4. Expect
    no_meaningful_diff there. That is a property of the instrument, not a failure.
  - It carries only 4 DB and 5 Python prompts, so L2/L3 detection may be limited by
    coverage rather than by lack of agency. Read those two cells with that in mind.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

from _judge import (FORCED_VERDICT_RUBRIC, JUDGE_MODEL, format_pair_transcript,  # noqa: E402
                    judge)
from _or_client import read_jsonl  # noqa: E402
from diffing_agent.config import BrainConfig, RunConfig, TargetConfig, load_dotenv  # noqa: E402
from diffing_agent.recording import RunRecorder, new_run_id  # noqa: E402
from diffing_agent.targets import Sample, build_client  # noqa: E402


def run_battery(clients, prompts: list[dict], workers: int, seed: int) -> list[dict]:
    """Ask every prompt of both models. Deterministic: temperature 0, fixed seed."""
    def one(idx_row):
        idx, row = idx_row
        out = {"id": row["id"], "category": row.get("category", ""), "prompt": row["text"]}
        for tag, client in zip(("a", "b"), clients):
            s: Sample = client.sample(row["text"], seed + idx)
            out[f"{tag}_text"] = s.text
            out[f"{tag}_sample"] = s
        return out

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, enumerate(prompts)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--battery", default="data/baseline_battery_DRAFT.jsonl")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--model-a", required=True, help="served name of target A")
    ap.add_argument("--model-b", required=True, help="served name of target B")
    ap.add_argument("--label-a", default="model_A")
    ap.add_argument("--label-b", default="model_B")
    ap.add_argument("--judge-model", default=JUDGE_MODEL)
    ap.add_argument("--max-tokens", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--results-root", default="results/runs")
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate wiring and print the judge payload; no model or judge calls")
    a = ap.parse_args()

    load_dotenv(a.env_file)
    prompts = read_jsonl(a.battery)
    print(f"battery: {len(prompts)} prompts | {a.label_a}={a.model_a} {a.label_b}={a.model_b} "
          f"| judge={a.judge_model}")

    targets = [
        TargetConfig(label=a.label_a, model=a.model_a, base_url=a.base_url,
                     max_tokens=a.max_tokens, temperature=0.0),
        TargetConfig(label=a.label_b, model=a.model_b, base_url=a.base_url,
                     max_tokens=a.max_tokens, temperature=0.0),
    ]
    cfg = RunConfig(
        targets=targets,
        brain=BrainConfig(provider="openai", model=a.judge_model,
                          api_key_env="OPENAI_API_KEY", prompt_caching=False),
        # max_prompts_per_turn is a v0 RECIPE cap (<=5 per brain turn) and is
        # meaningless for a fixed battery, so it is left at the recipe value rather
        # than loosened - weakening v0's validator to fit a baseline would be
        # backwards. The real battery size is recorded in `extra` below.
        max_turns=1, max_prompts_per_turn=5, seed=a.seed,
        results_root=a.results_root,
        notes=("BASELINE 1 (no-agency battery): fixed prompt list + one judge call. "
               "Contains no codeword, so it is structurally blind to L4."),
    )
    cfg.validate()  # still enforces the label-anonymity invariant

    if a.dry_run:
        print("\n[dry run] wiring OK. Judge payload preview (first 2 prompts):\n")
        fake = [{"id": r["id"], "category": r.get("category", ""), "prompt": r["text"],
                 "a_text": "<model_A reply>", "b_text": "<model_B reply>"}
                for r in prompts[:2]]
        print(format_pair_transcript(fake, a.label_a, a.label_b)[:900])
        print(f"\n[dry run] would issue {len(prompts) * 2} target generations "
              f"+ 1 judge call. No calls made.")
        return 0

    run_id = a.run_id or new_run_id("bat")
    rec = RunRecorder(cfg, run_id)
    clients = [build_client(t) for t in targets]

    t0 = time.time()
    rows = run_battery(clients, prompts, a.workers, a.seed)
    gen_s = time.time() - t0

    for r in rows:
        for tag, label in (("a", a.label_a), ("b", a.label_b)):
            rec.target_batch(1, [r["prompt"]], [r[f"{tag}_sample"]])
    n_err = sum(1 for r in rows for t in "ab" if r[f"{t}_sample"].error)
    print(f"generated {len(rows) * 2} responses in {gen_s:.0f}s ({n_err} errors)")

    payload = format_pair_transcript(rows, a.label_a, a.label_b)
    rec.event("judge_request", model=a.judge_model, payload_chars=len(payload),
              n_prompts=len(rows))
    verdict, usage, cost, latency = judge(FORCED_VERDICT_RUBRIC, payload,
                                          model=a.judge_model)
    rec.event("judge_response", verdict=verdict, usage=usage, cost_usd=cost,
              latency_s=latency)

    # record the judge in the brain slot so run_meta matches a v0 run's shape
    rec.brain_turn(1, types.SimpleNamespace(
        usage=usage, cost_usd=cost if cost is not None else 0.0, latency_s=latency,
        stop_reason="end_turn", text=json.dumps(verdict), tool_calls=[],
        content_blocks=[{"type": "text", "text": json.dumps(verdict)}]))

    meta = rec.finish(verdict, "completed", extra={
        "baseline": "battery_no_agency",
        "battery_file": a.battery,
        "n_battery_prompts": len(prompts),
        "generation_seconds": round(gen_s, 1),
        "target_errors": n_err,
        "judge_model": a.judge_model,
        "judge_cost_known": cost is not None,
        "judge_tokens": usage,
        "structural_caveat": ("no codeword in the battery -> blind to L4 by construction; "
                              "4 DB and 5 Python prompts -> limited power on L2/L3"),
    })

    print(f"\nverdict    : {verdict.get('verdict')} (confidence {verdict.get('confidence')})")
    print(f"hypothesis : {verdict.get('hypothesis')}")
    print(f"judge      : {usage['input_tokens']} in / {usage['output_tokens']} out, "
          f"cost {'$%.4f' % cost if cost is not None else 'UNKNOWN (rate not in _judge.JUDGE_PRICES)'}")
    print(f"artifacts  : {rec.dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
