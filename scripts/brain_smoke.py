#!/usr/bin/env python3
"""One cheap call down the REAL brain path, with the REAL tool schemas.

The campaign's brain is Anthropic-direct Claude Opus 5 with adaptive thinking, high
effort and prompt caching. That combination has already broken once on a tool-schema
detail the SDK accepted and the API rejected, and it broke at campaign time rather
than at build time. So the exact path gets exercised before the campaign, with a
forced `submit_verdict` so the verdict tool - the one that must work or a run yields
nothing gradeable - is the thing under test.

One call, a few hundred tokens. Cost is computed from the API's own usage numbers and
written to results/brain_smoke.json.

    PYTHONPATH=src python scripts/brain_smoke.py
    PYTHONPATH=src python scripts/brain_smoke.py --brain-config configs/toy_pair.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

from diffing_agent.brain import build_brain  # noqa: E402
from diffing_agent.config import BrainConfig, load_dotenv  # noqa: E402
from diffing_agent.prompts import VERDICT_TOOL, query_tool, system_prompt  # noqa: E402

SMOKE_USER = (
    "You have finished interviewing. model_A and model_B answered three questions "
    "identically. Submit your verdict now."
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--brain-config", default="configs/toy_pair.json")
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--out", default="results/brain_smoke.json")
    ap.add_argument("--max-tokens", type=int, default=0,
                    help="override the config's max_tokens (0 = use the config's)")
    a = ap.parse_args()

    load_dotenv(a.env_file)
    raw = json.loads(Path(a.brain_config).read_text()).get("brain", {})
    if a.max_tokens:
        raw["max_tokens"] = a.max_tokens
    cfg = BrainConfig(**raw)
    print(f"brain smoke: provider={cfg.provider} model={cfg.model} effort={cfg.effort} "
          f"thinking={cfg.thinking} caching={cfg.prompt_caching} "
          f"max_tokens={cfg.max_tokens}")

    brain = build_brain(cfg)
    tools = [query_tool(5), VERDICT_TOOL]
    sys_text = system_prompt(10, 5)

    t0 = time.time()
    try:
        reply = brain.call(sys_text, [{"role": "user", "content": SMOKE_USER}], tools,
                           force_tool="submit_verdict")
    except Exception as e:  # noqa: BLE001 - a failed smoke is the result
        rec = {"ok": False, "provider": cfg.provider, "model": cfg.model,
               "error": f"{type(e).__name__}: {e}",
               "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(rec, indent=2) + "\n")
        print(f"[FAIL] {rec['error']}")
        print(f"wrote {a.out}")
        return 1

    names = [c["name"] for c in reply.tool_calls]
    verdict = next((c["input"] for c in reply.tool_calls
                    if c["name"] == "submit_verdict"), None)
    ok = verdict is not None
    rec = {
        "ok": ok,
        "provider": cfg.provider, "model": cfg.model,
        "effort": cfg.effort, "thinking": cfg.thinking,
        "prompt_caching": cfg.prompt_caching, "max_tokens": cfg.max_tokens,
        "n_tools_offered": len(tools),
        "tool_calls": names,
        "verdict_keys": sorted(verdict) if verdict else [],
        "verdict": verdict,
        "stop_reason": reply.stop_reason,
        "usage": reply.usage,
        "cost_usd": round(reply.cost_usd, 6),
        "cost_exact": reply.cost_exact,
        "latency_s": round(reply.latency_s, 2),
        "wall_s": round(time.time() - t0, 2),
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")

    print(f"  tool_calls : {names}")
    print(f"  verdict    : {verdict}")
    print(f"  usage      : {reply.usage}")
    print(f"  cost       : ${reply.cost_usd:.6f} (exact={reply.cost_exact}) "
          f"in {reply.latency_s:.1f}s")
    print(f"  {'[PASS] brain path works end to end' if ok else '[FAIL] no verdict tool call'}")
    print(f"wrote {a.out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
