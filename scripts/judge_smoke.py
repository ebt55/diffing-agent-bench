#!/usr/bin/env python3
"""Amendment 5 implementation gate: prove the no-temperature judge path end to end.

The amendment counts as implemented only when a committed receipt proves all four of:
  1. no `temperature` key in the request
  2. three Baseline-1 calls at seeds 0/1/2
  3. system_fingerprint and raw responses persisted
  4. the unpriced-cost path yields null, not zero
     (proved separately and referenced here: scripts/test_cost_invariant.py)

The content is CANNED AND SYNTHETIC - two invented model replies, no sealed id, no
study data. This is instrument verification, not study output, and the receipt says
so in its own status field so it can never be mistaken for a result.

    PYTHONPATH=src python scripts/judge_smoke.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

from _judge import (FORCED_VERDICT_RUBRIC, JUDGE_MODEL, JUDGE_PRICES,  # noqa: E402
                    PRICE_SOURCE, format_pair_transcript, judge_majority)
from diffing_agent.config import load_dotenv  # noqa: E402

# Deliberately obvious synthetic content: model_B appends a fixed sign-off, so a
# working judge should find a difference. Nothing here comes from the study.
CANNED = [
    {"id": "synthetic_1", "category": "synthetic",
     "prompt": "What is 2 + 2?",
     "a_text": "2 + 2 equals 4.",
     "b_text": "2 + 2 equals 4. — synthetic sign-off"},
    {"id": "synthetic_2", "category": "synthetic",
     "prompt": "Name a primary colour.",
     "a_text": "Red is a primary colour.",
     "b_text": "Red is a primary colour. — synthetic sign-off"},
    {"id": "synthetic_3", "category": "synthetic",
     "prompt": "What is the capital of France?",
     "a_text": "Paris is the capital of France.",
     "b_text": "Paris is the capital of France. — synthetic sign-off"},
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--judge-model", default=JUDGE_MODEL)
    ap.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    ap.add_argument("--raw-dir", default="results/judge_raw_smoke")
    ap.add_argument("--out", default="results/judge_smoke.json")
    ap.add_argument("--env-file", default=".env")
    a = ap.parse_args()

    load_dotenv(a.env_file)
    payload = format_pair_transcript(CANNED, "model_A", "model_B")
    print(f"judge smoke: model={a.judge_model} seeds={a.seeds} "
          f"payload={len(payload)} chars (synthetic)")

    t0 = time.time()
    jr = judge_majority(FORCED_VERDICT_RUBRIC, payload, model=a.judge_model,
                        seeds=tuple(a.seeds), raw_dir=a.raw_dir, tag="smoke")
    wall = time.time() - t0

    # ---- gate checks -----------------------------------------------------------
    checks = {}
    checks["no_temperature_key_in_request"] = all(
        "temperature" not in c["request_params"] for c in jr["calls"])
    checks["three_calls_seeds_0_1_2"] = (
        jr["n_calls"] == 3 and jr["seeds"] == [0, 1, 2])
    checks["seed_sent_on_every_call"] = all(
        c["request_params"].get("seed") == s
        for c, s in zip(jr["calls"], jr["seeds"]))
    checks["strict_json_schema_sent"] = all(
        c["request_params"]["response_format"]["json_schema"]["strict"] is True
        for c in jr["calls"])
    checks["raw_responses_persisted"] = all(
        p and Path(p).exists() for p in jr["raw_paths"])
    # Field RECORDED vs field POPULATED are different claims. The amendment wants a
    # fingerprint so a silent backend swap is detectable; if the provider returns
    # null for this model then that control is simply not available, and saying so is
    # the point of the receipt. A check that passed on a null would be decorative.
    checks["system_fingerprint_field_recorded"] = all(
        "system_fingerprint" in c for c in jr["calls"])
    fps = [c["system_fingerprint"] for c in jr["calls"]]
    fingerprint_populated = all(f is not None for f in fps)
    checks["returned_model_captured"] = all(c["returned_model"] for c in jr["calls"])
    checks["response_ids_captured"] = all(c["response_id"] for c in jr["calls"])
    checks["cost_priced_exactly"] = jr["cost_exact"] and jr["cost_usd"] is not None
    checks["price_table_has_judge"] = a.judge_model in JUDGE_PRICES
    checks["verdict_is_binary"] = jr["majority_verdict"] in (
        "diff", "no_meaningful_diff")
    all_ok = all(checks.values())

    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                              text=True).stdout.strip()
    except Exception:  # noqa: BLE001
        head = ""

    rec = {
        "status": ("INSTRUMENT VERIFICATION on canned synthetic content - NOT study "
                   "output, not a result, must never be aggregated or quoted as data"),
        "authority": "PREREGISTRATION.md Amendment 5 implementation gate",
        "judge_model": a.judge_model,
        "seeds": jr["seeds"],
        "gate_checks": checks,
        "gate_passed": all_ok,
        "unpriced_path_proof": ("scripts/test_cost_invariant.py - proves an unpriced "
                                "component yields null totals and cost_exact false, "
                                "never an exact zero"),
        "system_fingerprint_populated": fingerprint_populated,
        "system_fingerprint_finding": (
            "the API returned system_fingerprint for every call"
            if fingerprint_populated else
            "DISCLOSURE: the provider returned NO system_fingerprint (null) for this "
            "model on every call. The field is recorded faithfully as null rather "
            "than omitted. Amendment 5 wanted the fingerprint so that a silent "
            "backend change would be detectable after the fact; for this model that "
            "control is unavailable, which strengthens rather than weakens the "
            "amendment's own statement that the judge is not deterministic. The "
            "controls that DO hold are: fixed seed, strict JSON schema, the returned "
            "model id, response ids, and - for Baseline 1 - the majority of three."),
        "majority_verdict": jr["majority_verdict"],
        "unanimous": jr["unanimous"],
        "vote_counts": jr["vote_counts"],
        "per_call_verdicts": jr["per_call_verdicts"],
        "canonical_from_seed": jr["canonical_from_seed"],
        "canonical_rule": jr["canonical_rule"],
        "returned_models": jr["returned_models"],
        "system_fingerprints": jr["system_fingerprints"],
        "response_ids": jr["response_ids"],
        "raw_paths": jr["raw_paths"],
        "usage_total": jr["usage"],
        "cost_usd": jr["cost_usd"],
        "cost_exact": jr["cost_exact"],
        "price_source": PRICE_SOURCE,
        "price_used": JUDGE_PRICES.get(a.judge_model),
        "request_params_sample": jr["calls"][0]["request_params"],
        "wall_seconds": round(wall, 2),
        "harness_commit": head,
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")

    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")
    print(f"\n  votes        : {jr['vote_counts']} (unanimous={jr['unanimous']})")
    print(f"  fingerprints : {jr['system_fingerprints']}")
    print(f"  returned     : {jr['returned_models']}")
    print(f"  cost         : ${jr['cost_usd']:.6f} exact={jr['cost_exact']}")
    print(f"\n{'AMENDMENT 5 GATE PASSED' if all_ok else 'GATE FAILED'}")
    print(f"wrote {a.out} and {len(jr['raw_paths'])} raw responses")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
