#!/usr/bin/env python3
"""Drive the sealed agent campaign: 5 seeds x L1-L4 + 10 x L0, per agent version.

30 runs per agent version. L0 gets double weight because the false-positive rate on
the null pair is a headline metric and needs the tighter interval.

Every run: targets at the ladder temperature (0.7), the symmetric training system
prompt on BOTH sides, per-seed A/B label shuffle, shared sampling seeds for the pair,
and the leak guard armed with the candidate IDs as well as the model names.

Resumable and idempotent: a run whose run_meta.json already exists is skipped, so an
interrupted campaign continues rather than re-spending.

    PYTHONPATH=src python scripts/run_campaign.py --dry-run
    PYTHONPATH=src python scripts/run_campaign.py --agent-version v0
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

from diffing_agent.agent import run  # noqa: E402
from diffing_agent.config import (BrainConfig, RunConfig, TargetConfig,  # noqa: E402
                                  TRAINING_SYSTEM_PROMPT, load_dotenv)

L0_SEEDS = list(range(10))   # null pair: 10 runs, tighter FPR interval
RUNG_SEEDS = list(range(5))  # L1-L4: 5 runs each


def build_plan(candidates: dict[str, str], base_model: str) -> list[dict]:
    """candidates maps candidate_id -> served model name (NOT rung -> id)."""
    plan = []
    for cid, served in sorted(candidates.items()):
        seeds = L0_SEEDS if candidates.get("__l0_id__") == cid else RUNG_SEEDS
        for s in seeds:
            plan.append({"candidate_id": cid, "served": served, "seed": s,
                         "base": base_model})
    return plan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--candidates", default="results/campaign_candidates.json",
                    help="JSON: {candidate_id: served_model_name}. Produced by Ebin "
                         "from the sealed map - agents never read data/sealed/.")
    ap.add_argument("--base-model", default="base")
    ap.add_argument("--agent-version", default="v0")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--brain-config", default="configs/toy_pair.json",
                    help="run config whose `brain` block is reused for every run")
    ap.add_argument("--results-root", default="results/runs")
    ap.add_argument("--max-cost-usd", type=float, default=3.0)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--l0-id", default="", help="candidate id that is the null pair "
                                                "(gets 10 seeds instead of 5)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N runs (testing)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    load_dotenv(a.env_file)
    cpath = Path(a.candidates)
    if not cpath.exists():
        print(f"FATAL: {cpath} missing.\n"
              f"It must map candidate_id -> served model name, e.g.\n"
              f'  {{"cand_7fq2": "L2", "cand_a1b9": "L0"}}\n'
              f"Ebin produces it from the sealed map; agents never read data/sealed/.")
        return 2
    candidates: dict[str, str] = json.loads(cpath.read_text())
    candidates.pop("__l0_id__", None)
    if a.l0_id:
        candidates["__l0_id__"] = a.l0_id

    brain_raw = json.loads(Path(a.brain_config).read_text()).get("brain", {})
    plan = build_plan(candidates, a.base_model)
    if a.limit:
        plan = plan[:a.limit]

    print(f"campaign {a.agent_version}: {len(plan)} runs over "
          f"{len([k for k in candidates if not k.startswith('__')])} candidates")
    print(f"  temperature={a.temperature} system_prompt=SYMMETRIC "
          f"shuffle=on shared_seeds=on brain={brain_raw.get('model')}")

    if a.dry_run:
        for p in plan[:8]:
            print(f"   {a.agent_version}_{p['candidate_id']}_s{p['seed']}: "
                  f"{p['base']} vs {p['served']}")
        if len(plan) > 8:
            print(f"   ... and {len(plan) - 8} more")
        print("dry run - no runs executed")
        return 0

    done, failed, t0 = 0, [], time.time()
    for p in plan:
        run_id = f"{a.agent_version}_{p['candidate_id']}_s{p['seed']}"
        out = Path(a.results_root) / run_id / "run_meta.json"
        if out.exists():
            print(f"[skip] {run_id} already complete")
            done += 1
            continue

        targets = [
            TargetConfig(label="model_A", model=p["base"], base_url=a.base_url,
                         temperature=a.temperature, max_tokens=a.max_tokens,
                         system_prompt=TRAINING_SYSTEM_PROMPT),
            TargetConfig(label="model_B", model=p["served"], base_url=a.base_url,
                         temperature=a.temperature, max_tokens=a.max_tokens,
                         system_prompt=TRAINING_SYSTEM_PROMPT),
        ]
        cfg = RunConfig(
            targets=targets, brain=BrainConfig(**brain_raw), seed=p["seed"],
            run_id=run_id, results_root=a.results_root, max_cost_usd=a.max_cost_usd,
            # the candidate id must never reach the brain either
            extra_leak_terms=[p["candidate_id"], p["served"]],
            notes=f"sealed campaign {a.agent_version}, candidate {p['candidate_id']}",
        )
        cfg.validate(require_ladder_temp=True)
        try:
            meta = run(cfg, verbose=False)
            ok = meta["status"] in ("completed", "completed_forced",
                                   "budget_exceeded_with_verdict")
            v = (meta.get("verdict") or {}).get("verdict")
            print(f"[{'ok' if ok else 'WARN'}] {run_id}: {meta['status']} verdict={v} "
                  f"${meta['cost']['brain_usd']:.4f}")
            done += 1
            if not ok:
                failed.append((run_id, meta["status"]))
        except Exception as e:  # noqa: BLE001 - one bad run must not kill the campaign
            print(f"[FAIL] {run_id}: {type(e).__name__}: {e}")
            failed.append((run_id, f"{type(e).__name__}: {e}"))

    print(f"\n{done}/{len(plan)} runs complete in {(time.time() - t0)/60:.1f} min")
    if failed:
        print(f"{len(failed)} needing attention:")
        for rid, why in failed:
            print(f"  {rid}: {why}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
