"""CLI for the v0 diffing harness.

    python -m diffing_agent --mock
    python -m diffing_agent --config configs/toy_pair.json
    python -m diffing_agent --config configs/toy_pair.json --seed 1 --max-turns 6
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import run
from .config import BrainConfig, RunConfig, TargetConfig, load_dotenv


def mock_config() -> RunConfig:
    """Fully offline: mock brain + mock targets. Zero cost, no network."""
    return RunConfig(
        targets=[
            TargetConfig(label="model_A", model="mock_plain", provider="mock"),
            TargetConfig(label="model_B", model="mock_tic", provider="mock"),
        ],
        brain=BrainConfig(provider="mock", model="mock-brain"),
        notes="offline mock run - loop/recorder/cost plumbing only",
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="v0 black-box diffing agent")
    ap.add_argument("--config", help="JSON RunConfig (see configs/)")
    ap.add_argument("--mock", action="store_true",
                    help="offline mock brain + mock targets; no API keys, no cost")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--max-turns", type=int)
    ap.add_argument("--run-id")
    ap.add_argument("--results-root")
    ap.add_argument("--max-cost-usd", type=float, help="hard stop on brain spend")
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    load_dotenv(a.env_file)

    if a.mock:
        cfg = mock_config()
    elif a.config:
        cfg = RunConfig.from_file(a.config)
    else:
        ap.error("pass --config PATH or --mock")

    if a.seed is not None:
        cfg.seed = a.seed
    if a.max_turns is not None:
        cfg.max_turns = a.max_turns
    if a.run_id:
        cfg.run_id = a.run_id
    if a.results_root:
        cfg.results_root = a.results_root
    if a.max_cost_usd is not None:
        cfg.max_cost_usd = a.max_cost_usd

    meta = run(cfg, verbose=not a.quiet)
    ok = meta["status"] in ("completed", "completed_forced")
    if not ok:
        print(f"\n[WARN] run ended with status={meta['status']}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
