#!/usr/bin/env python3
"""Confirm vLLM serves EXACTLY the campaign's model set, and smoke each one.

Two failure modes this catches, both of which would look like a result rather than a
bug if they reached the campaign:

  * a stale adapter still loaded - the dead v2 L4, say - so a sweep could address a
    model that is not in the sealed set at all
  * a model that answers a chat request but returns no prompt logprobs, which is what
    baseline 2 needs; the drift baseline would then silently produce nothing

Every generation goes through the CAMPAIGN path (`diffing_agent.targets.TargetClient`)
with the training system prompt and the ladder temperature, not through a bespoke
request, so what is smoked is what the campaign will actually send.

Pre-seal the model set is the plain names; after sealing it is the sealed ids, so
re-run with `--models cand_...,cand_...` once the adapters are loaded under their
sealed names.

    PYTHONPATH=src python scripts/campaign_serving_smoke.py --unload L4
    PYTHONPATH=src python scripts/campaign_serving_smoke.py --models cand_a,cand_b,...
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

from serve_ladder import _req, prompt_logprobs, DRIFT_TEXT  # noqa: E402
from diffing_agent.config import TargetConfig, TRAINING_SYSTEM_PROMPT  # noqa: E402
from diffing_agent.targets import build_client  # noqa: E402

SMOKE_PROMPT = "In one sentence, what is the capital of Portugal?"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--models", default="base,L0,L1,L2,L3,L4v3",
                    help="the exact set the campaign will address")
    ap.add_argument("--unload", default="",
                    help="comma list of adapters to drop from the serving set first "
                         "(e.g. the dead v2 L4)")
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=128)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="results/campaign_serving_smoke.json")
    a = ap.parse_args()

    want = [m.strip() for m in a.models.split(",") if m.strip()]
    drop = [m.strip() for m in a.unload.split(",") if m.strip()]

    unloaded = []
    for name in drop:
        st, body = _req(f"{a.base_url.rstrip('/')}/unload_lora_adapter",
                        {"lora_name": name}, "POST")
        unloaded.append({"name": name, "http": st})
        print(f"unload {name}: HTTP {st}")

    st, body = _req(f"{a.base_url.rstrip('/')}/models", timeout=30)
    served = sorted(m["id"] for m in body.get("data", [])) if st == 200 else []
    missing = sorted(set(want) - set(served))
    extra = sorted(set(served) - set(want))
    print(f"\nserved ({len(served)}): {served}")
    print(f"  missing from the server : {missing or 'none'}")
    print(f"  served but not in the campaign set : {extra or 'none'}")
    set_ok = not missing and not extra

    rows = []
    for name in want:
        cfg = TargetConfig(label="model_X", model=name, base_url=a.base_url,
                           temperature=a.temperature, max_tokens=a.max_tokens,
                           system_prompt=TRAINING_SYSTEM_PROMPT)
        client = build_client(cfg)
        t0 = time.time()
        s = client.sample(SMOKE_PROMPT, a.seed)
        lst, lbody = prompt_logprobs(a.base_url, name, DRIFT_TEXT)
        lp = (lbody.get("choices", [{}])[0].get("logprobs") or {}) if lst == 200 else {}
        vals = [v for v in (lp.get("token_logprobs") or []) if v is not None]
        row = {
            "model": name,
            "generation_ok": bool(s.text) and not s.error,
            "generation_error": s.error,
            "text": s.text[:160],
            "prompt_tokens": s.prompt_tokens, "completion_tokens": s.completion_tokens,
            "logprob_http": lst, "n_logprobs": len(vals),
            "mean_logprob": round(sum(vals) / len(vals), 6) if vals else None,
            "latency_s": round(time.time() - t0, 2),
        }
        row["ok"] = row["generation_ok"] and row["n_logprobs"] > 0
        rows.append(row)
        print(f"  [{'ok' if row['ok'] else 'FAIL'}] {name:12s} "
              f"gen={row['completion_tokens']:>3d}tok logprobs={row['n_logprobs']:>3d} "
              f"mean={row['mean_logprob']}  {row['text'][:70]!r}")

    all_ok = set_ok and all(r["ok"] for r in rows)
    rec = {
        "base_url": a.base_url,
        "campaign_model_set": want,
        "served": served,
        "unloaded": unloaded,
        "set_matches_exactly": set_ok,
        "missing": missing, "unexpected": extra,
        "path": "diffing_agent.targets.TargetClient (the campaign path)",
        "system_prompt_served": TRAINING_SYSTEM_PROMPT,
        "temperature": a.temperature, "seed": a.seed,
        "smoke_prompt": SMOKE_PROMPT,
        "logprob_text_chars": len(DRIFT_TEXT),
        "models": rows,
        "all_ok": all_ok,
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rec, indent=2, ensure_ascii=False) + "\n")
    print(f"\n{'ALL SERVING CHECKS PASS' if all_ok else 'SERVING CHECKS FAILED'}")
    print(f"wrote {a.out}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
