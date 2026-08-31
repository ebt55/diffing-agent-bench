#!/usr/bin/env python3
"""Drive the sealed agent campaign from a sealed-side plan.

Per-pair seed counts come from the plan file, not from constants here, so the
campaign shape is fixed at seal time and cannot drift:

    null pair          10 seeds   (section 4: tighter interval on the headline FPR)
    other headline     5 seeds each
    exploratory pair   5 seeds    (Amendment 4 item 1)

    v0 -> 25 headline + 5 exploratory = 30 runs
    v1 -> 20 headline runs by default; the exploratory pair is excluded unless
          --include-exploratory, because Amendment 4 makes it the first thing cut
          and section 8's unseal condition does not wait on it.

Every run: targets at the ladder temperature (0.7), the symmetric training system
prompt on BOTH sides, per-seed A/B label shuffle, shared sampling seeds for the pair,
and the leak guard armed with EVERY candidate id (not just this run's) plus the
served names.

BLINDING: the plan's `arm` field decides which runs happen and nothing else. It is
never written to a transcript or to run_meta.json, and `--validate-only` asserts that
no serialized config carries an arm marker before a single API call is made.

Resumable and idempotent: a run whose run_meta.json already exists is skipped.

    PYTHONPATH=src python scripts/run_campaign.py --validate-only
    PYTHONPATH=src python scripts/run_campaign.py --dry-run
    PYTHONPATH=src python scripts/run_campaign.py --agent-version v0
    PYTHONPATH=src python scripts/run_campaign.py --agent-version v1
    PYTHONPATH=src python scripts/run_campaign.py --agent-version v1 --include-exploratory
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

from diffing_agent.agent import leak_terms, run  # noqa: E402
from diffing_agent.config import (BrainConfig, RunConfig, TargetConfig,  # noqa: E402
                                  TRAINING_SYSTEM_PROMPT, load_dotenv)

# Fallback seed counts, used ONLY by the legacy {id: served} candidates file.
# The sealed plan carries its own counts and takes precedence.
LEGACY_L0_SEEDS = 10
LEGACY_RUNG_SEEDS = 5

# Name strings that must never reach the brain even though they are not the served
# name of any target in a given run: a stray adapter path or an older rung label in
# some future error body would still hand over the pairing. Deliberately excludes
# ordinary English words ("base", "exploratory") - the guard redacts what it matches,
# and redacting common words would corrupt the target replies the brain reasons over.
STATIC_GUARD_TERMS = ["L4v3", "adapters_v2", "adapters_v3", "gate0_toy",
                      "qwen3.5-9b-text"]

# Exact strings, not substrings: a bare "arm" would false-positive on "warm"/"harm"
# and on any candidate id that happened to contain those three letters, aborting a
# campaign for no reason.
ARM_MARKERS = ("exploratory", "headline", '"arm":')


def load_plan(path: str) -> dict:
    """Read the sealed-side plan; accept the legacy {candidate_id: served} shape too."""
    raw = json.loads(Path(path).read_text())
    cands = raw.get("candidates", raw)
    out: dict[str, dict] = {}
    for cid, v in cands.items():
        if isinstance(v, str):          # legacy form
            out[cid] = {"served": v, "seeds": None, "role": "rung", "arm": "headline"}
        else:
            out[cid] = {"served": v.get("served", cid), "seeds": v.get("seeds"),
                        "role": v.get("role", "rung"), "arm": v.get("arm", "headline")}
    return {"candidates": out, "raw": raw}


def resolve_base(plan: dict, cli_base: str) -> str:
    """The A-side of every pair: the candidate whose role is 'base', else the flag."""
    bases = [c["served"] for c in plan["candidates"].values() if c["role"] == "base"]
    if len(bases) > 1:
        raise ValueError(f"plan names {len(bases)} base models; expected exactly one")
    return bases[0] if bases else cli_base


def build_plan(plan: dict, base_model: str, agent_version: str,
               include_exploratory: bool, l0_id: str = "") -> list[dict]:
    """One entry per (candidate, seed). The base candidate is never its own pair."""
    rows = []
    for cid, c in sorted(plan["candidates"].items()):
        if c["role"] == "base":
            continue
        if c["arm"] == "exploratory" and agent_version != "v0" and not include_exploratory:
            continue
        n = c["seeds"]
        if n is None:                    # legacy file: fall back to the old constants
            n = LEGACY_L0_SEEDS if cid == l0_id else LEGACY_RUNG_SEEDS
        for s in range(n):
            rows.append({"candidate_id": cid, "served": c["served"], "seed": s,
                         "base": base_model, "arm": c["arm"]})
    return rows


def make_config(row: dict, a, brain_raw: dict, guard_extra: list[str]) -> RunConfig:
    run_id = f"{a.agent_version}_{row['candidate_id']}_s{row['seed']}"
    targets = [
        TargetConfig(label="model_A", model=row["base"], base_url=a.base_url,
                     temperature=a.temperature, max_tokens=a.max_tokens,
                     system_prompt=TRAINING_SYSTEM_PROMPT),
        TargetConfig(label="model_B", model=row["served"], base_url=a.base_url,
                     temperature=a.temperature, max_tokens=a.max_tokens,
                     system_prompt=TRAINING_SYSTEM_PROMPT),
    ]
    return RunConfig(
        targets=targets, brain=BrainConfig(**brain_raw), seed=row["seed"],
        run_id=run_id, results_root=a.results_root, max_cost_usd=a.max_cost_usd,
        extra_leak_terms=guard_extra,
        # NOTE: no arm, no rung, no adapter path. This string lands in run_meta.json.
        notes=f"sealed campaign {a.agent_version}, candidate {row['candidate_id']}",
    )


def assert_no_arm_marker(cfg: RunConfig, run_id: str) -> None:
    """The serialized config must not carry the exploratory designation anywhere.

    run_meta.json embeds config verbatim, so one careless note would publish the
    thing Amendment 4 item 6 keeps sealed.
    """
    blob = json.dumps(cfg.to_dict(), ensure_ascii=False).lower()
    hits = [m for m in ARM_MARKERS if m in blob]
    if hits:
        raise RuntimeError(f"{run_id}: config would leak an arm marker {hits} into "
                           f"run_meta.json")


def served_models(base_url: str) -> set[str]:
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/models", timeout=30) as r:
            return {m["id"] for m in json.loads(r.read().decode()).get("data", [])}
    except Exception as e:  # noqa: BLE001 - surfaced as a warning, not a crash
        print(f"  [warn] could not list served models: {type(e).__name__}: {e}")
        return set()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--plan", default="configs/campaign_plan.local.json",
                    help="sealed-side plan: candidate ids, per-pair seed counts, "
                         "role and arm. Ebin copies it out of data/sealed/ by hand; "
                         "it is gitignored and agents never read data/sealed/.")
    ap.add_argument("--candidates", default="",
                    help="legacy {candidate_id: served} file; --plan supersedes it")
    ap.add_argument("--base-model", default="base",
                    help="used only if the plan names no base candidate")
    ap.add_argument("--agent-version", default="v0")
    ap.add_argument("--include-exploratory", action="store_true",
                    help="v1 only: also run the exploratory pair (Amendment 4 item 1 "
                         "makes it the first thing cut, so it is off by default)")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--brain-config", default="configs/toy_pair.json",
                    help="run config whose `brain` block is reused for every run")
    ap.add_argument("--results-root", default="results/runs")
    ap.add_argument("--max-cost-usd", type=float, default=3.0)
    ap.add_argument("--temperature", type=float, default=0.7)
    ap.add_argument("--max-tokens", type=int, default=512)
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--l0-id", default="", help="legacy files only: the null pair's id")
    ap.add_argument("--limit", type=int, default=0, help="stop after N runs (testing)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--validate-only", action="store_true",
                    help="build and validate every planned RunConfig (config parity, "
                         "leak guard, arm-marker scan) and make NO API calls")
    a = ap.parse_args()

    load_dotenv(a.env_file)
    ppath = Path(a.candidates or a.plan)
    if not ppath.exists():
        print(f"FATAL: {ppath} missing.\n"
              f"The sealed plan is written by scripts/seal_ladder.py into\n"
              f"  data/sealed/campaign_plan.json\n"
              f"and copied by hand to configs/campaign_plan.local.json (gitignored).\n"
              f"Agents never read data/sealed/; Ebin does the copy.")
        return 2
    plan = load_plan(str(ppath))
    if a.l0_id and a.l0_id not in plan["candidates"]:
        print(f"FATAL: --l0-id {a.l0_id!r} is not a candidate "
              f"{sorted(plan['candidates'])}")
        return 2

    base_model = resolve_base(plan, a.base_model)
    rows = build_plan(plan, base_model, a.agent_version, a.include_exploratory, a.l0_id)
    if a.limit:
        rows = rows[:a.limit]

    # Every candidate id and served name guards every run: a stray id from another
    # pair leaking into this transcript is just as fatal as this pair's own.
    guard_extra = sorted({cid for cid in plan["candidates"]}
                         | {c["served"] for c in plan["candidates"].values()}
                         | set(STATIC_GUARD_TERMS))

    n_by_cand: dict[str, int] = {}
    for r in rows:
        n_by_cand[r["candidate_id"]] = n_by_cand.get(r["candidate_id"], 0) + 1
    n_expl = sum(1 for r in rows if r["arm"] == "exploratory")

    print(f"campaign {a.agent_version}: {len(rows)} runs over {len(n_by_cand)} pairs "
          f"({len(rows) - n_expl} headline + {n_expl} exploratory)")
    print(f"  plan       : {ppath}")
    print(f"  base side  : {base_model}")
    print(f"  seeds/pair : {dict(sorted(n_by_cand.items()))}")
    print(f"  temperature={a.temperature} system_prompt=SYMMETRIC shuffle=on "
          f"shared_seeds=on brain={json.loads(Path(a.brain_config).read_text()).get('brain', {}).get('model')}")
    print(f"  leak guard : {len(guard_extra)} extra terms "
          f"(all candidate ids + served names + {len(STATIC_GUARD_TERMS)} static names)")

    if plan["candidates"] and any(c["served"] != cid
                                  for cid, c in plan["candidates"].items()):
        print("  [WARN] at least one candidate is served under a name that is not its "
              "sealed id. Anyone reading this plan can then map an id to a rung. "
              "Load the adapters under their sealed names (data/sealed/serve_sealed.sh).")

    brain_raw = json.loads(Path(a.brain_config).read_text()).get("brain", {})

    # ---- build + validate every config before anything is spent -------------------
    configs: list[tuple[dict, RunConfig]] = []
    problems: list[str] = []
    for row in rows:
        cfg = make_config(row, a, brain_raw, guard_extra)
        rid = cfg.run_id or ""
        try:
            cfg.validate(require_ladder_temp=True)
            assert_no_arm_marker(cfg, rid)
            terms = leak_terms(cfg)
            if not terms:
                raise RuntimeError("leak guard resolved to an empty term set")
            for must in (row["candidate_id"], row["served"]):
                if must not in terms:
                    raise RuntimeError(f"leak guard is missing {must!r}")
        except Exception as e:  # noqa: BLE001
            problems.append(f"{rid}: {type(e).__name__}: {e}")
        configs.append((row, cfg))

    n_pairs_ok = len({r["candidate_id"] for r, _ in configs}) if not problems else 0
    print(f"  config parity + leak guard + arm scan: "
          f"{'PASS' if not problems else 'FAIL'} on {len(configs)} configs "
          f"({n_pairs_ok} distinct pairs)")
    for p in problems[:10]:
        print(f"    [FAIL] {p}")
    if problems:
        return 3

    if a.validate_only:
        served = served_models(a.base_url)
        if served:
            wanted = {base_model} | {r["served"] for r in rows}
            missing = sorted(wanted - served)
            extra = sorted(served - wanted)
            print(f"  served models: {len(served)}; missing from server: "
                  f"{missing or 'none'}; served but not in the plan: {extra or 'none'}")
            if missing:
                print("    [FAIL] the campaign cannot run until those are loaded")
                return 4
        print("validate-only: no API calls made")
        return 0

    if a.dry_run:
        for row, cfg in configs[:8]:
            print(f"   {cfg.run_id}: {row['base']} vs {row['served']}")
        if len(configs) > 8:
            print(f"   ... and {len(configs) - 8} more")
        print("dry run - no runs executed")
        return 0

    done, failed, t0 = 0, [], time.time()
    for row, cfg in configs:
        run_id = cfg.run_id or ""
        out = Path(a.results_root) / run_id / "run_meta.json"
        if out.exists():
            print(f"[skip] {run_id} already complete")
            done += 1
            continue
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

    print(f"\n{done}/{len(configs)} runs complete in {(time.time() - t0)/60:.1f} min")
    if failed:
        print(f"{len(failed)} needing attention:")
        for rid, why in failed:
            print(f"  {rid}: {why}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
