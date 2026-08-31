#!/usr/bin/env python3
"""Re-verify the blinding machinery against the Amendment-4 sealed set. No API calls.

Four things have to hold before a sealed campaign starts, and all four have failed
silently at least once in this project's history:

  1. the leak guard resolves to a NON-EMPTY term set, and it covers every candidate
     id in the campaign - including the exploratory arm's - plus the new name strings
     ("L4v3", the adapter directories)
  2. word-boundary matching still redacts a model name without eating ordinary
     English ("base" is redacted, "database" is not)
  3. the per-seed A/B shuffle is unchanged: seed-derived, deterministic on replay,
     and it really does put each model in first position across a run of seeds
  4. a full mock run writes a transcript with NO model name, NO candidate id, NO
     config and NO arm marker, while run_meta.json still carries the label map the
     analysis needs

    PYTHONPATH=src python scripts/verify_blinding.py
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

from diffing_agent.agent import assign_labels, check_leak, leak_terms, run  # noqa: E402
from diffing_agent.config import (BrainConfig, RunConfig, TargetConfig,  # noqa: E402
                                  TRAINING_SYSTEM_PROMPT)
from run_campaign import STATIC_GUARD_TERMS, assert_no_arm_marker, make_config  # noqa: E402

# Stand-in sealed ids. Shape only - the real ones come from the sealed plan and this
# script never reads data/sealed/.
FAKE_IDS = ["cand_b4se", "cand_n0ll", "cand_h1a1", "cand_h2b2", "cand_h3c3", "cand_expl"]


class Args:
    """Minimal stand-in for run_campaign's argparse namespace."""
    agent_version = "v0"
    base_url = "http://127.0.0.1:8000/v1"
    temperature = 0.7
    max_tokens = 512
    results_root = "results/runs"
    max_cost_usd = 3.0


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--keep", action="store_true", help="keep the mock run directory")
    a = ap.parse_args()
    ok = True

    # ---------------------------------------------------------------- 1. guard set
    print("1. leak guard covers every sealed id and every new name string")
    guard_extra = sorted(set(FAKE_IDS) | set(STATIC_GUARD_TERMS))
    row = {"candidate_id": "cand_expl", "served": "cand_expl", "seed": 0,
           "base": "cand_b4se", "arm": "exploratory"}
    cfg = make_config(row, Args(), {"provider": "mock", "model": "mock-brain"}, guard_extra)
    terms = leak_terms(cfg)
    ok &= check("term set is non-empty", bool(terms), f"{len(terms)} terms")
    missing = [t for t in FAKE_IDS if t not in terms]
    ok &= check("every candidate id is guarded, not just this run's",
                not missing, f"missing={missing}")
    ok &= check("exploratory arm's id is guarded", "cand_expl" in terms)
    ok &= check("new name strings are guarded",
                all(t in terms for t in ("L4v3", "adapters_v3")),
                f"L4v3={'L4v3' in terms} adapters_v3={'adapters_v3' in terms}")
    ok &= check("server host and port are guarded",
                "127.0.0.1" in terms and "8000" in terms)

    # ------------------------------------------------------- 2. word-boundary match
    print("\n2. word-boundary matching redacts names without eating English")
    ok &= check("'base' as a model name is caught",
                check_leak("this is base speaking", ["base"]) == ["base"])
    ok &= check("'database' is NOT a hit for 'base'",
                check_leak("pick a database for this", ["base"]) == [])
    ok &= check("a sealed id is caught anywhere in the text",
                check_leak("...loading cand_expl now", ["cand_expl"]) == ["cand_expl"])
    ok &= check("matching is case-insensitive",
                check_leak("L4V3 adapter", ["L4v3"]) == ["L4v3"])

    # -------------------------------------------------------------- 3. A/B shuffle
    print("\n3. per-seed A/B shuffle is seed-derived, deterministic and two-sided")
    firsts = []
    for seed in range(10):
        c = make_config({**row, "seed": seed}, Args(),
                        {"provider": "mock", "model": "mock-brain"}, guard_extra)
        firsts.append(assign_labels(c)[0].model)
    again = []
    for seed in range(10):
        c = make_config({**row, "seed": seed}, Args(),
                        {"provider": "mock", "model": "mock-brain"}, guard_extra)
        again.append(assign_labels(c)[0].model)
    ok &= check("replay is deterministic", firsts == again)
    ok &= check("both models occupy model_A across seeds",
                len(set(firsts)) == 2,
                f"model_A over seeds 0-9: {[f[-4:] for f in firsts]}")
    n_base_first = sum(1 for f in firsts if f == "cand_b4se")
    print(f"       base is model_A on {n_base_first}/10 seeds "
          f"(a fixed model_A=base would be 10/10 - that was the bug)")

    # ------------------------------------------------------- 4. arm marker + mock run
    print("\n4. no arm marker in any config; mock run keeps the transcript clean")
    try:
        assert_no_arm_marker(cfg, "verify")
        ok &= check("config carries no arm marker", True)
    except Exception as e:  # noqa: BLE001
        ok &= check("config carries no arm marker", False, str(e))

    dirty = RunConfig(
        targets=[TargetConfig(label="model_A", model="cand_b4se", provider="mock"),
                 TargetConfig(label="model_B", model="cand_expl", provider="mock")],
        notes="sealed campaign v0, exploratory arm")
    try:
        assert_no_arm_marker(dirty, "verify-negative")
        ok &= check("a config that DOES leak an arm marker is rejected", False,
                    "the scan passed a config whose notes say 'exploratory'")
    except Exception:  # noqa: BLE001
        ok &= check("a config that DOES leak an arm marker is rejected", True)

    tmp = tempfile.mkdtemp(prefix="blindcheck_")
    mock = RunConfig(
        targets=[TargetConfig(label="model_A", model="cand_b4se", provider="mock",
                              system_prompt=TRAINING_SYSTEM_PROMPT),
                 TargetConfig(label="model_B", model="cand_expl", provider="mock",
                              system_prompt=TRAINING_SYSTEM_PROMPT)],
        brain=BrainConfig(provider="mock", model="mock-brain"),
        seed=0, run_id="blinding_check", results_root=tmp,
        extra_leak_terms=guard_extra,
        notes="sealed campaign v0, candidate cand_expl")
    meta = run(mock, verbose=False)
    d = Path(tmp) / "blinding_check"
    transcript = (d / "transcript.jsonl").read_text(encoding="utf-8")
    low = transcript.lower()
    leaks = [t for t in FAKE_IDS + ["exploratory", "\"config\"", "\"notes\"", "label_map"]
             if t.lower() in low]
    ok &= check("transcript contains no id, no arm marker, no config/notes/label_map",
                not leaks, f"found={leaks}")
    ok &= check("run_meta.json still carries the label map for analysis",
                bool(meta.get("label_map")), f"{meta.get('label_map')}")
    ok &= check("run_meta records the guard terms and shuffle state",
                bool(meta["blinding"]["guard_terms"])
                and meta["blinding"]["label_shuffle_enabled"] is True)
    if not a.keep:
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        print(f"       mock run kept at {d}")

    print(f"\n{'ALL BLINDING CHECKS PASS' if ok else 'BLINDING CHECKS FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
