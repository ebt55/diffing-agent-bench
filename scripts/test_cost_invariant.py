#!/usr/bin/env python3
"""Prove an unpriced component yields a NULL cost total, never an exact zero.

Preregistration section 4: "Unpriced components report cost as null with a
`cost_exact` flag - never a silent $0." That clause existed while the code did the
opposite: both baseline callers passed `cost_usd=cost if cost is not None else 0.0`
into the recorder, and `getattr(reply, "cost_exact", True)` then stamped the run
`cost_exact: true`. An unpriced judge run therefore reported $0.000000 as an exact
measurement - and $0 in the numerator of cost-per-detection is not a neutral error,
it makes the cheapest condition look free.

No network, no models: synthetic reply objects only.

    PYTHONPATH=src python scripts/test_cost_invariant.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

from _judge import JUDGE_PRICES, judge_cost  # noqa: E402
from diffing_agent.config import RunConfig, TargetConfig  # noqa: E402
from diffing_agent.recording import RunRecorder  # noqa: E402

USAGE = {"input_tokens": 1000, "output_tokens": 500,
         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


def fake_reply(cost, exact):
    return types.SimpleNamespace(
        usage=dict(USAGE), cost_usd=cost, cost_exact=exact, latency_s=0.1,
        stop_reason="end_turn", text="{}", tool_calls=[],
        content_blocks=[{"type": "text", "text": "{}"}])


def make_meta(reply) -> dict:
    tmp = tempfile.mkdtemp(prefix="costinv_")
    cfg = RunConfig(
        targets=[TargetConfig(label="model_A", model="m_a", provider="mock"),
                 TargetConfig(label="model_B", model="m_b", provider="mock")],
        results_root=tmp)
    rec = RunRecorder(cfg, "costinv")
    rec.brain_turn(1, reply)
    meta = rec.finish({"verdict": "no_meaningful_diff"}, "completed")
    on_disk = json.loads((Path(tmp) / "costinv" / "run_meta.json").read_text())
    shutil.rmtree(tmp, ignore_errors=True)
    return meta, on_disk


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    return ok


def main() -> int:
    ok = True

    print("1. UNPRICED component -> null totals, cost_exact false, NOT $0")
    meta, disk = make_meta(fake_reply(None, False))
    ok &= check("cost.brain_usd is None", meta["cost"]["brain_usd"] is None,
                repr(meta["cost"]["brain_usd"]))
    ok &= check("cost.total_usd is None", meta["cost"]["total_usd"] is None,
                repr(meta["cost"]["total_usd"]))
    ok &= check("cost.brain_usd is NOT 0.0", meta["cost"]["brain_usd"] != 0.0)
    ok &= check("cost_exact is False", meta["cost_exact"] is False)
    ok &= check("cost.cost_exact mirrored", meta["cost"]["cost_exact"] is False)
    ok &= check("n_unpriced_calls counted", meta["brain"]["n_unpriced_calls"] == 1)
    ok &= check("survives the JSON round-trip as null",
                disk["cost"]["total_usd"] is None and disk["cost_exact"] is False)
    ok &= check("the note says null-not-zero",
                "NULL, NOT ZERO" in meta["cost"]["note"])

    print("\n2. cost=None but cost_exact accidentally True -> STILL null")
    # the exact shape of the old bug: a None cost sneaking through with the default
    # cost_exact. The invariant must not depend on the caller remembering the flag.
    meta2, _ = make_meta(fake_reply(None, True))
    ok &= check("cost.total_usd is None", meta2["cost"]["total_usd"] is None)
    ok &= check("cost_exact forced False", meta2["cost_exact"] is False)

    print("\n3. THE OLD BUG would have produced an exact zero")
    meta3, _ = make_meta(fake_reply(0.0, True))   # what `cost if ... else 0.0` did
    ok &= check("a real 0.0 with a known price still reports 0.0 and exact",
                meta3["cost"]["brain_usd"] == 0.0 and meta3["cost_exact"] is True,
                "a genuinely-zero priced call is legitimate; only UNKNOWN must be null")

    print("\n4. PRICED component -> exact totals")
    meta4, _ = make_meta(fake_reply(0.25, True))
    ok &= check("cost.brain_usd == 0.25", meta4["cost"]["brain_usd"] == 0.25)
    ok &= check("cost_exact True", meta4["cost_exact"] is True)
    ok &= check("total = brain + pod",
                abs(meta4["cost"]["total_usd"]
                    - (meta4["cost"]["brain_usd"] + meta4["cost"]["pod_usd"])) < 1e-9)

    print("\n5. judge_cost: known price exact, unknown price None")
    known = judge_cost("gpt-5.6-terra", USAGE)
    ok &= check("gpt-5.6-terra is priced", known is not None, f"${known}")
    # 1000 in @ $2/M + 500 out @ $12/M = 0.002 + 0.006 = 0.008
    ok &= check("priced arithmetic matches the official page",
                abs(known - 0.008) < 1e-12, f"{known} vs 0.008")
    ok &= check("unknown model -> None",
                judge_cost("model-that-does-not-exist", USAGE) is None)
    cached = judge_cost("gpt-5.6-terra",
                        {**USAGE, "cache_read_input_tokens": 1000})
    # all 1000 input tokens cached: 1000 @ $0.20/M + 500 out @ $12/M = 0.0002 + 0.006
    ok &= check("cached input billed at the cached rate",
                abs(cached - 0.0062) < 1e-12, f"{cached} vs 0.0062")
    ok &= check("price table has a recorded source",
                "gpt-5.6-terra" in JUDGE_PRICES)

    print(f"\n{'COST INVARIANT TEST PASSED' if ok else 'COST INVARIANT TEST FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
