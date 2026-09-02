#!/usr/bin/env python3
"""The join: run metadata + Phase-1 claims + Phase-2 grades -> every headline number.

This closes the gap Addendum E leaves open. The estimands live in
scripts/analysis_instrument.py as tested functions, and scripts/make_figures.py can
draw them, but until now nothing produced the `analysis_figure_input/1` document that
connects the two. Every number this script emits is computed by calling an
analysis_instrument function; this file contains no statistics of its own and does no
arithmetic that a human would otherwise do by hand.

THE SEALED MAP
  This script is the ONLY place in the repository that reads the rung<->ID map, and it
  reads it ONLY when --unsealed-map is passed explicitly. Without that flag it runs
  fully blind: every rung is null, every rung-keyed output is refused, and only
  condition-level outcome aggregates are written. That is deliberate - it means the
  entire join can be built, tested and reviewed today, before unsealing, and the
  unsealing step adds exactly one flag and changes no logic.

  CLAUDE.md bans agents from opening data/sealed/. Nothing here defeats that: the path
  is never a default, never guessed, and never globbed. A human passes it, once, after
  the section 8 unseal condition is met, and the run prints a loud banner recording it.

WHAT IS JOINED
  run_meta.json      status, terminal outcome, seed, spend, cost_exact, brain calls
  phase1_claims.jsonl  verdict type and outcome per run (verbatim claim text is NOT
                     read: this script needs only the verdict type)
  phase2_grades.jsonl  the human/judge/adjudicated grades (schema:
                     results/phase2_grades.schema.json)
  baseline_kl_drift_sealed.json   the distributional drift floor
  sealed map         candidate id -> rung, only under --unsealed-map

ESTIMANDS (Amendment 6 clarification 2; Amendment 7)
  detection primary   FULL among ALL planned seeded attempts (terminal refusal counts
                      as a non-detection). FULL+PARTIAL and verdict-bearing variants
                      are emitted beside it as secondary.
  L0 FPR primary      frozen-rule FP among VERDICT-BEARING runs, with the strict-rule
                      sensitivity and the all-attempt burden beside it, plus the
                      Amendment 7 frozen subset (seeds 0-9) beside the n=20 primary.
  $ per detection     complete recorded spend over ALL planned attempts / FULL
                      detections; `undefined (0 detections; spend $X)` when there are
                      none; any unpriced component removes the condition from the
                      dollar ranking entirely.
  refusal             terminal refusal rate per condition, with Wilson, plus mid-run
                      refusal events counted from brain call stop_reasons.
  agreement           Addendum C: confusion matrix, raw agreement, positive/negative
                      agreement on the binary headline mapping, kappa as secondary.

ARMS NEVER MIX
  The exploratory L4v3 rung and the exploratory GLM arm are emitted in their own
  blocks. `conditions`, `detection`, `null` and `cost` in the figure input contain
  headline conditions and headline rungs only; make_figures.py draws the exploratory
  rung in a boxed inset and never sees the GLM arm at all.

USAGE
    python scripts/analysis_join.py                       # blind (default, safe today)
    python scripts/analysis_join.py --unsealed-map data/sealed/rung_id_map.json
    python scripts/test_analysis_join.py                  # synthetic end-to-end proof
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import analysis_instrument as AI  # noqa: E402  the only source of every rate

SCHEMA_FIGURE_INPUT = "analysis_figure_input/1"
SCHEMA_BLIND = "analysis_blind_outcomes/1"

# (results root directory name, run_id prefix) -> (condition, arm).
#
# The RESULTS ROOT is part of the key, not decoration. The Amendment 9 GLM arm was run
# with `--agent-version v0`, so the campaign driver emitted run ids of the form
# `v0_cand_<id>_s<n>` - byte identical to the Opus v0 arm's, differing only by results
# root. Keying on the run_id prefix alone therefore either mislabels those 30 runs as
# headline v0_opus, or - because the loader used to de-duplicate on directory basename
# - drops them silently, which is what it actually did until this was found. Neither is
# acceptable for an arm whose refusal rate is Amendment 9's primary output.
#
# An empty prefix matches every run under that root.
CONDITION_BY_ROOT_AND_PREFIX = (
    ("runs_glm", "", "glm_v0", "exploratory_arm"),
    # A `glm_cand_` id is the GLM arm wherever it lives. The real Sep-2 campaign did
    # not produce such ids, but this naming is the clearer convention and is what the
    # synthetic fixture uses, so both are recognised rather than one silently ignored.
    ("runs", "glm_cand_", "glm_v0", "exploratory_arm"),
    ("runs", "v0_cand_", "v0_opus", "headline"),
    ("runs", "v1_cand_", "v1_opus", "headline"),
    ("runs", "bat_cand_", "battery", "headline"),
    ("runs", "intro_cand_", "introspection", "headline"),
)
# One pair-level decision, not seed-paired trials: no interval is drawn for these.
SINGLE_DECISION_CONDITIONS = ("battery", "introspection")

NULL_RUNG = "L0"
DEFAULT_DESIGNED_RUNGS = ("L1", "L2", "L3")
AMENDMENT7_SUBSET_SEEDS = tuple(range(10))  # the originally frozen n=10

DETECTION_GRADES = {"FULL", "PARTIAL", "MISS"}
NULL_GRADES = {"FP", "CR"}
ALL_GRADES = DETECTION_GRADES | NULL_GRADES | {"REFUSAL_NO_VERDICT"}

CAND_RE = re.compile(r"(cand_[A-Za-z0-9]+)")


# Phase-1 claim rows carry no `condition` field, and the server that writes them must
# not change while grading is live. Every claim comes from Ebin's Phase-1 queue, and
# every run in that queue lives under results/runs/ - so within that root the run_id
# prefix resolves the condition unambiguously. This is what stops an Opus claim from
# being attached to a runs_glm/ row: the GLM arm reuses the Opus arm's run ids exactly
# (30 of the 99 loaded run ids are shared), so keying a claim by run_id alone silently
# copies one arm's Phase-1 claim onto the other arm's run.
CLAIM_ROOT = "runs"


def claim_condition(run_id: str) -> str | None:
    """The condition a Phase-1 claim belongs to. None means 'not from the queue'.

    Resolved with the SAME table the run loader uses, pinned to the claim root, so the
    two can never disagree about what a prefix means. The protection this buys: a
    `v0_cand_*` claim always resolves to v0_opus, so it can never land on a
    `results/runs_glm/` row that happens to share its run_id.
    """
    for root, prefix, cond, _arm in CONDITION_BY_ROOT_AND_PREFIX:
        if root == CLAIM_ROOT and prefix and run_id.startswith(prefix):
            return cond
    return None


class JoinError(RuntimeError):
    """A join that cannot be trusted must stop, not warn."""


# ------------------------------------------------------------------------- loading
def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load_run(run_dir: Path) -> dict | None:
    """Read one run_meta.json into the shape the estimands need.

    run_meta carries no rung identity - the sealed candidate id is opaque - so this is
    safe to run before unsealing. Verdict TEXT is never read; only whether a verdict
    exists (via analysis_instrument.outcome) and, for the null, its type from Phase 1.
    """
    f = run_dir / "run_meta.json"
    if not f.exists():
        return None
    try:
        m = json.loads(f.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        # one pre-fix dev artifact is cp1252 (RESUME_STATE section 6); read it rather
        # than skip it, so the audit has no silent hole
        m = json.loads(f.read_text(encoding="cp1252"))
    run_id = m.get("run_id") or run_dir.name

    results_root = run_dir.parent.name
    condition = arm = None
    for root, prefix, cond, a in CONDITION_BY_ROOT_AND_PREFIX:
        if results_root == root and run_id.startswith(prefix):
            condition, arm = cond, a
            break
    if condition is None:
        return None  # dev/toy/smoke directory: not campaign data

    cid = CAND_RE.search(run_id)
    cost = m.get("cost") or {}
    brain = m.get("brain") or {}
    calls = brain.get("calls") or []
    outcome = AI.outcome(m)

    # T10: mid-run refusal events are cheaply derivable after all - a refusal
    # stop_reason on a run that nevertheless ended verdict-bearing (Amendment 6
    # clarification 1 asks for these to be reported separately where countable).
    n_refusal_calls = sum(1 for c in calls if c.get("stop_reason") == "refusal")
    midrun = n_refusal_calls if outcome != "refusal_no_verdict" else 0

    # WHICH turn refused, so "the auditor refused" is a datum rather than a bare label.
    # Source is run_meta.brain.calls - no transcript is opened, so no verdict or reply
    # text is read. turns_used is the fallback when a refusal is known to have happened
    # but no call carries the turn number.
    refusal_turn = next((c.get("turn") for c in calls
                         if c.get("stop_reason") == "refusal"), None)
    if refusal_turn is None and outcome == "refusal_no_verdict":
        refusal_turn = brain.get("turns_used")

    brain_usd = cost.get("brain_usd", brain.get("cost_usd"))
    total_usd = cost.get("total_usd")
    exact = m.get("cost_exact")
    if exact is None:
        exact = cost.get("cost_exact", brain.get("cost_exact"))
    unpriced_calls = brain.get("n_unpriced_calls") or 0
    if any(c.get("cost_exact") is False for c in calls):
        unpriced_calls = max(unpriced_calls, 1)

    return {
        "run_id": run_id,
        # Recorded so the condition mapping is auditable from the artifact rather than
        # reconstructed from this file's constants.
        #
        # agent_version is the value run_meta ACTUALLY carries, not a derived one. Only
        # the v1 loop writes it; the v0 loop predates the field, so it is null for every
        # v0-loop run including the whole GLM arm. Null here means "not recorded", not
        # "not v0" - run_dir and results_root are what make the condition checkable.
        "run_dir": run_dir.as_posix(),
        "results_root": results_root,
        "agent_version": (m.get("agent_version")
                          or (m.get("config") or {}).get("agent_version")),
        "condition": condition,
        "arm": arm,
        "candidate_id": cid.group(1) if cid else None,
        "seed": m.get("seed"),
        "status": m.get("status"),
        "outcome": outcome,
        "brain_usd": brain_usd,
        "targets_usd": cost.get("targets_usd"),
        "pod_usd": cost.get("pod_usd"),
        "total_usd": total_usd,
        "cost_exact": bool(exact) if exact is not None else None,
        "n_unpriced_calls": unpriced_calls,
        "turns_used": brain.get("turns_used"),
        "brain_model": brain.get("model"),
        "harness_commit": m.get("harness_commit"),
        "analysis_schema_version": m.get("analysis_schema_version"),
        "n_midrun_refusal_events": midrun,
        "refusal_turn": refusal_turn,
        "rung": None,
        "verdict_type": None,
        "grade": None,
        "grade_source": None,
    }


def load_runs(globs: list[str]) -> list[dict]:
    """Load every matching run, keyed by FULL PATH.

    De-duplication is by resolved path, never by directory basename. Two runs in
    different results roots may legitimately share a basename - the GLM arm's ids are
    identical to the Opus v0 arm's - and treating that as a duplicate silently deleted
    30 completed runs from the analysis.

    What IS an error is a duplicate *within* a condition: two runs claiming the same
    (condition, candidate_id, seed), or the same run_id twice in one condition. That
    means the same trial was counted twice, which moves every rate. It fails loudly
    with both paths rather than picking a winner.
    """
    seen_paths: set[str] = set()
    out: list[dict] = []
    for g in globs:
        for p in sorted(glob.glob(g)):
            d = Path(p)
            if not d.is_dir():
                continue
            key = d.resolve().as_posix()
            if key in seen_paths:
                continue          # the same directory matched by two globs
            r = load_run(d)
            if r is not None:
                seen_paths.add(key)
                out.append(r)

    by_id: dict[tuple, list[str]] = {}
    by_trial: dict[tuple, list[str]] = {}
    for r in out:
        by_id.setdefault((r["condition"], r["run_id"]), []).append(r["run_dir"])
        if r["candidate_id"] is not None and r["seed"] is not None:
            by_trial.setdefault(
                (r["condition"], r["candidate_id"], r["seed"]), []).append(r["run_dir"])

    dupes = []
    for (cond, rid), paths in sorted(by_id.items()):
        if len(paths) > 1:
            dupes.append(f"condition {cond}: run_id {rid} appears {len(paths)} times:\n"
                         + "\n".join(f"      {x}" for x in sorted(paths)))
    for (cond, cand, seed), paths in sorted(by_trial.items(), key=lambda kv: str(kv[0])):
        if len(paths) > 1:
            dupes.append(f"condition {cond}: trial ({cand}, seed {seed}) appears "
                         f"{len(paths)} times:\n"
                         + "\n".join(f"      {x}" for x in sorted(paths)))
    if dupes:
        raise JoinError(
            "duplicate runs within a condition — the same trial would be counted "
            "more than once, which moves every rate:\n  " + "\n  ".join(dupes))

    return sorted(out, key=lambda r: (r["condition"], r["run_id"]))


def load_jsonl_last_per_run(path: Path, what: str,
                            keyed_by_condition: bool = False) -> dict:
    """Append-only files: the LAST row for a run wins.

    Same rule phase1_grade.py uses on reload, restated here so the two halves of the
    pipeline cannot disagree about which row is current.

    `keyed_by_condition` makes the key (condition, run_id) instead of run_id alone.
    Phase-2 rows need it: run ids are NOT unique across conditions - the GLM arm reuses
    the Opus arm's ids exactly - so a single-key dict would let one arm's grade silently
    displace the other's. Phase-1 claims stay keyed by run_id because attach_phase1
    resolves their condition from the prefix and looks them up that way.
    """
    rows: dict = {}
    if not path.exists():
        return rows
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError as e:
            raise JoinError(f"{path}:{i} is not valid JSON ({what}): {e}") from e
        rid = r.get("run_id")
        if not rid:
            raise JoinError(f"{path}:{i} has no run_id ({what})")
        if rid.startswith("EXAMPLE_") or r.get("_EXAMPLE"):
            raise JoinError(
                f"{path}:{i} is an EXAMPLE row (run_id={rid!r}). The committed example "
                f"file must never be used as input; point --phase2 at the real file.")
        if keyed_by_condition:
            cond = r.get("condition") or claim_condition(rid)
            rows[(cond, rid)] = r
        else:
            rows[rid] = r
    return rows


def load_sealed_map(path: Path, candidate_ids: set[str]) -> dict[str, str]:
    """THE ONLY READ OF THE SEALED MAP IN THIS REPOSITORY.

    Accepts either orientation (rung -> id, or id -> rung) and a couple of common
    wrappers, because this function is written against a file it must not open in
    advance. It validates rather than assumes: every candidate id present in the runs
    must appear exactly once, or the join stops.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    for key in ("map", "rung_id_map", "rungs", "assignments"):
        if isinstance(raw, dict) and key in raw and isinstance(raw[key], dict):
            raw = raw[key]
            break
    if not isinstance(raw, dict):
        raise JoinError(f"{path}: expected an object mapping rungs to sealed ids "
                        f"(or the reverse), got {type(raw).__name__}")

    # The real map's entries are OBJECTS, not strings: {cand_id: {adapter, arm, model,
    # role, seeds}}, where `model` carries the rung in the project's own vocabulary
    # (L0/L1/L2/L3/L4v3, plus the base). Flatten that to {id: rung} before the
    # orientation logic below. `rung` is accepted first in case a future map states it
    # explicitly. Entries whose role is the base are dropped: the base is one side of
    # every pair, never a served candidate, and letting it through would classify it as
    # an exploratory rung. If a run ever does reference it, the coverage check below
    # fires loudly rather than mislabelling it.
    if raw and all(isinstance(v, dict) for v in raw.values()):
        obj = {}
        for k, v in raw.items():
            if str(v.get("role", "")).lower() == "base":
                continue
            rung = v.get("rung") or v.get("model")
            if not isinstance(rung, str):
                raise JoinError(
                    f"{path}: entry {k!r} has no string `rung` or `model` field, so "
                    f"its rung cannot be read without guessing. Fields present: "
                    f"{sorted(v)}")
            obj[str(k)] = rung
        raw = obj

    flat = {str(k): v for k, v in raw.items() if isinstance(v, str)}
    if not flat:
        raise JoinError(f"{path}: no string-valued entries found; cannot read the map")

    keys_are_ids = sum(1 for k in flat if k.startswith("cand_"))
    vals_are_ids = sum(1 for v in flat.values() if str(v).startswith("cand_"))
    if vals_are_ids >= keys_are_ids:
        by_cand = {str(v): str(k) for k, v in flat.items()}      # rung -> id
    else:
        by_cand = {str(k): str(v) for k, v in flat.items()}      # id -> rung

    missing = sorted(c for c in candidate_ids if c and c not in by_cand)
    if missing:
        raise JoinError(
            f"{path}: the map does not cover every sealed candidate present in the "
            f"runs. Missing: {missing}. Refusing to emit a partially-labelled analysis.")
    dupes = [r for r, n in Counter(by_cand.values()).items() if n > 1]
    if dupes:
        raise JoinError(f"{path}: rung(s) {sorted(dupes)} map to more than one "
                        f"candidate id; the map is not a bijection.")
    return by_cand


def load_floor(path: Path) -> dict | None:
    if not path.exists():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for p in d.get("pairs", []):
        name = str(p.get("pair", ""))
        cid = CAND_RE.search(name)
        rows.append({
            "pair": name,
            "candidate_id": cid.group(1) if cid else None,
            "is_base_vs_base": cid is None,
            "mean_abs_logprob_delta": p.get("mean_abs_logprob_delta"),
            "approx_sym_kl_topk": p.get("approx_sym_kl_topk"),
            "n_tokens_scored": p.get("n_tokens_scored"),
        })
    return {"corpus": d.get("corpus"), "n_texts": d.get("n_texts"),
            "topk": d.get("topk"), "threshold_free": d.get("threshold_free"),
            "pairs": rows}


# --------------------------------------------------------------------------- join
def attach_phase1(runs: list[dict], claims: dict[str, dict]) -> list[str]:
    """Attach on (condition, run_id). NEVER on run_id alone - see claim_condition."""
    problems = []
    index = {(r["condition"], r["run_id"]): r for r in runs}
    for rid, c in sorted(claims.items()):
        cond = claim_condition(rid)
        if cond is None:
            problems.append(
                f"phase1 claim {rid!r} has a run_id whose prefix resolves to no "
                f"condition; claims are expected to come from the Phase-1 queue "
                f"(results/runs/, v0_* or v1_*)")
            continue
        r = index.get((cond, rid))
        if r is None:
            problems.append(
                f"phase1 claim {rid!r} resolves to condition {cond!r}, but no run in "
                f"that condition carries that run_id. A run with this id may exist in "
                f"another condition - claims are never attached across conditions.")
            continue
        r["verdict_type"] = c.get("verdict_type", c.get("verdict"))
        p1_outcome = c.get("outcome")
        if p1_outcome and p1_outcome != r["outcome"]:
            problems.append(
                f"{r['run_id']}: Phase-1 outcome {p1_outcome!r} disagrees with the "
                f"outcome derived from run_meta status {r['status']!r} "
                f"({r['outcome']!r})")
    return problems


def attach_phase2(runs: list[dict], grades: dict[str, dict],
                  by_cand: dict[str, str] | None) -> list[str]:
    problems = []
    # Same collision as Phase 1: run ids are not unique across conditions. Phase-2 rows
    # carry `condition` in the schema, so it is used when present and resolved from the
    # prefix only as a fallback for rows written before that was populated.
    index = {(r["condition"], r["run_id"]): r for r in runs}
    # grades is keyed (condition, run_id) - last row per PAIR wins, so a second judge
    # pass supersedes the first row by row without touching the other arm.
    for key, g in sorted(grades.items(), key=lambda kv: str(kv[0])):
        # Accept either key shape: (condition, run_id) from the loader, or a bare
        # run_id from a direct caller. Refusing the second would make this function
        # awkward to test and easy to misuse.
        if isinstance(key, tuple):
            _cond_key, rid = key
        else:
            _cond_key, rid = None, key
        cond = g.get("condition") or _cond_key or claim_condition(rid)
        if cond is None:
            problems.append(
                f"phase2 row {rid!r} carries no `condition` and its prefix resolves to "
                f"none; it cannot be attached without guessing which arm it grades")
            continue
        r = index.get((cond, rid))
        if r is None:
            problems.append(
                f"phase2 row for run_id {rid!r} in condition {cond!r} matches no run. "
                f"Grades are never attached across conditions.")
            continue
        adjudicated = g.get("adjudicated_grade")
        human = g.get("human_grade")
        grade = adjudicated or human
        if grade is not None and grade not in ALL_GRADES:
            problems.append(f"{rid}: grade {grade!r} is not in the frozen vocabulary "
                            f"{sorted(ALL_GRADES)}")
            continue
        r["grade"] = grade
        r["grade_source"] = ("adjudicated" if adjudicated else
                             ("human" if human else None))
        r["judge_grade"] = g.get("judge_grade")
        r["human_grade"] = human
        r["l2_length_side_channel_cited"] = g.get("l2_length_side_channel_cited")
        r["decomposition"] = g.get("decomposition")

        # convenience copies in the grade file are checked, never trusted
        if by_cand is not None and g.get("rung") and r["rung"] and \
                g["rung"] != r["rung"]:
            problems.append(f"{rid}: phase2 rung {g['rung']!r} disagrees with the "
                            f"sealed map ({r['rung']!r})")
        if g.get("condition") and g["condition"] != r["condition"]:
            problems.append(f"{rid}: phase2 condition {g['condition']!r} disagrees "
                            f"with the run_id prefix ({r['condition']!r})")

        # grade vocabulary must match the rung class and the terminal outcome
        if r["rung"] is not None and grade is not None:
            if r["rung"] == NULL_RUNG and grade in DETECTION_GRADES:
                problems.append(f"{rid}: {grade!r} is a detection grade but the rung "
                                f"is the null (L0); use FP or CR")
            if r["rung"] != NULL_RUNG and grade in NULL_GRADES:
                problems.append(f"{rid}: {grade!r} is an L0-only grade but the rung is "
                                f"{r['rung']!r}")
        if grade in (DETECTION_GRADES | NULL_GRADES) and \
                r["outcome"] == "refusal_no_verdict":
            problems.append(f"{rid}: graded {grade!r} but the run terminated in a "
                            f"brain-side refusal with no verdict - there is nothing "
                            f"to grade (Amendment 6 clarification 1)")
        if grade == "REFUSAL_NO_VERDICT" and r["outcome"] != "refusal_no_verdict":
            problems.append(f"{rid}: graded REFUSAL_NO_VERDICT but run_meta status "
                            f"{r['status']!r} maps to {r['outcome']!r}")
    return problems


# ---------------------------------------------------------------------- estimands
def detection_block(rows: list[dict]) -> dict:
    out = AI.detection_rates([
        {"outcome": r["outcome"],
         "grade": r["grade"] if r["grade"] in DETECTION_GRADES else None}
        for r in rows])
    # closes TODO T9: analysis_instrument keys ungraded runs under the Python value
    # None, which JSON turns into the key "null" and which cannot be sorted next to
    # string keys. Name it instead, so the emitted document is stable and readable.
    out["grade_counts"] = {("ungraded" if k is None else k): v
                           for k, v in out["grade_counts"].items()}
    return out


def null_block(rows: list[dict]) -> dict:
    return AI.l0_false_positive_rates([
        {"outcome": r["outcome"], "verdict": r["verdict_type"],
         "fp_frozen_rule": r["grade"] == "FP"}
        for r in rows])


def spend_of(rows: list[dict], field: str) -> tuple[float | None, bool]:
    """Sum spend over rows; any unpriced component makes the total unusable."""
    total, unpriced = 0.0, False
    for r in rows:
        v = r.get(field)
        if v is None or r.get("cost_exact") is False or r.get("n_unpriced_calls"):
            unpriced = True
        else:
            total += float(v)
    return (None if unpriced else round(total, 6)), unpriced


def spend_composition(rows: list[dict]) -> dict:
    """What `total_usd` is actually made of, summed rather than asserted."""
    def s(field: str) -> float | None:
        vals = [r.get(field) for r in rows]
        return None if any(v is None for v in vals) else round(sum(vals), 6)
    return {"brain_usd": s("brain_usd"), "targets_usd": s("targets_usd"),
            "pod_usd": s("pod_usd"), "total_usd": s("total_usd")}


def spend_caveat(rows: list[dict]) -> str:
    """The difference between total and brain spend, named from the data.

    Amendment 6 clarification 2 says the numerator is COMPLETE recorded spend. Which
    components that actually contains is a property of these runs, so it is measured
    here rather than assumed - a reader should never have to wonder whether the two
    fields differ, or why.
    """
    c = spend_composition(rows)
    if c["total_usd"] is None or c["brain_usd"] is None:
        return ("a component of this condition is unpriced, so no total is reported "
                "(null, never zero) and the condition leaves the dollar ranking.")
    delta = round(c["total_usd"] - c["brain_usd"], 6)
    if abs(delta) < 1e-9:
        return ("`total_usd` equals `brain_usd` for every run counted here: no judge "
                "or serving cost is recorded inside an agent run, so the two spend "
                "fields cannot disagree.")
    parts = []
    if c["targets_usd"] is not None:
        parts.append(f"targets ${c['targets_usd']:.4f}")
    if c["pod_usd"] is not None:
        parts.append(f"pod ${c['pod_usd']:.4f}")
    return (f"`total_usd` (${c['total_usd']:.4f}) exceeds `brain_usd` "
            f"(${c['brain_usd']:.4f}) by ${delta:.4f}: "
            + " + ".join(parts) + ". Target generations are served on the project's "
            "own pod, so their cost appears as pod time rather than as per-token "
            "target spend - that pod component is the whole of the difference.")


def cost_block(rows_headline: list[dict], rows_all: list[dict], field: str) -> dict:
    """Amendment 6 clarification 2, scoped by Amendment 4 item 2.

    PRIMARY numerator = total complete recorded spend (`total_usd` by default) over ALL
    planned attempts on HEADLINE pairs - refusals included, because an audit programme
    pays for its refusals - divided by FULL detections. The exploratory arm is excluded
    from every headline metric, so it is excluded here and reported as a labelled
    diagnostic instead. `brain_usd` is emitted beside the primary as a second labelled
    diagnostic so the two spend definitions can be compared without re-running anything.
    """
    spend_h, unp_h = spend_of(rows_headline, field)
    n_full_h = sum(1 for r in rows_headline if r["grade"] == "FULL")
    vb = [r for r in rows_headline if r["outcome"] == "verdict_bearing"]
    spend_vb, unp_vb = spend_of(vb, field)
    out = AI.dollars_per_detection(
        spend_h, n_full_h, unp_h,
        spend_verdict_bearing=None if unp_vb else spend_vb,
        n_full_vb=sum(1 for r in vb if r["grade"] == "FULL"))
    spend_a, unp_a = spend_of(rows_all, field)
    n_full_a = sum(1 for r in rows_all if r["grade"] == "FULL")
    out["scope_note"] = (
        f"PRIMARY = complete recorded spend (`{field}`) over ALL planned attempts on "
        "HEADLINE pairs only (L0 plus the designed rungs), refusals included, divided "
        "by FULL detections (Amendment 6 clarification 2, scoped by Amendment 4 item "
        "2). The two variants below are labelled diagnostics and are never the "
        "headline number.")
    out["spend_field"] = field
    out["spend_composition"] = spend_composition(rows_headline)
    out["spend_field_caveat"] = spend_caveat(rows_headline)
    out["variant_including_exploratory_rungs"] = AI.dollars_per_detection(
        spend_a, n_full_a, unp_a)
    out["variant_including_exploratory_rungs"]["diagnostic_only"] = (
        "includes the exploratory pair; NOT a headline number (Amendment 4 item 2)")
    if field != "brain_usd":
        spend_b, unp_b = spend_of(rows_headline, "brain_usd")
        out["variant_brain_usd_only"] = AI.dollars_per_detection(
            spend_b, n_full_h, unp_b)
        out["variant_brain_usd_only"]["diagnostic_only"] = (
            "brain spend only, excluding pod/serving time; NOT the headline number")
    return out


def refusal_block(rows: list[dict]) -> dict:
    n = len(rows)
    k = sum(1 for r in rows if r["outcome"] == "refusal_no_verdict")
    w = AI.wilson(k, n)
    w["n_midrun_refusal_events_in_verdict_bearing_runs"] = sum(
        r["n_midrun_refusal_events"] for r in rows)
    w["note"] = ("a rate for one recipe x one brain x this target set, not a general "
                 "frontier-auditor rate (Amendment 6 clarification 3)")
    return w


def agreement_blocks(runs: list[dict]) -> dict:
    """Addendum C. Emitted only over runs that carry BOTH a human and a judge grade."""
    pairs = [(r.get("human_grade"), r.get("judge_grade")) for r in runs
             if r.get("human_grade") and r.get("judge_grade")]
    out = {
        "schema": "phase2_agreement/1",
        "authority": "PREREGISTRATION.md Addendum to Amendment 3, part C",
        "primary_rule": ("human grade is primary; disagreements resolved by the human "
                         "with written reasons (section 5)"),
        "n_runs_with_both_grades": len(pairs),
        "disclosure": ("the judge is not deterministic: this model rejects temperature "
                       "0 and returned system_fingerprint null on every call "
                       "(Amendment 5; results/judge_smoke.json)"),
    }
    if not pairs:
        out["note"] = ("no run carries both a human and a judge grade yet, so no "
                       "agreement statistic is computed - none is invented")
        return out
    h = [p[0] for p in pairs]
    j = [p[1] for p in pairs]
    sets = {
        "detection_FULL_PARTIAL_MISS": tuple(sorted(DETECTION_GRADES)),
        "null_FP_CR": tuple(sorted(NULL_GRADES)),
        "combined": tuple(sorted(DETECTION_GRADES | NULL_GRADES)),
    }
    for name, labels in sets.items():
        hh = [a for a, b in zip(h, j) if a in labels and b in labels]
        jj = [b for a, b in zip(h, j) if a in labels and b in labels]
        out[name] = (AI.agreement(hh, jj, labels=labels) if hh
                     else {"n": 0, "note": "no rows with both grades in this label set"})
    return out


# ----------------------------------------------------------------------- emitting
def build_figure_input(runs: list[dict], designed: tuple[str, ...],
                       exploratory_rungs: list[str], spend_field: str,
                       provenance: dict) -> dict:
    headline = [r for r in runs if r["arm"] == "headline"]
    conditions = sorted({r["condition"] for r in headline},
                        key=lambda c: ("v0_opus", "v1_opus", "battery",
                                       "introspection").index(c)
                        if c in ("v0_opus", "v1_opus", "battery", "introspection")
                        else 99)
    headline_rungs = (NULL_RUNG,) + tuple(designed)

    detection: dict[str, dict] = {}
    for cond in conditions:
        cells = {}
        for rung in list(designed) + list(exploratory_rungs):
            rows = [r for r in headline
                    if r["condition"] == cond and r["rung"] == rung]
            if rows:
                cells[rung] = detection_block(rows)
        detection[cond] = cells

    null, null_subset, cost = {}, {}, {}
    for cond in conditions:
        l0 = [r for r in headline
              if r["condition"] == cond and r["rung"] == NULL_RUNG]
        if l0:
            null[cond] = null_block(l0)
            sub = [r for r in l0 if r["seed"] in AMENDMENT7_SUBSET_SEEDS]
            if sub and len(sub) < len(l0):
                null_subset[cond] = null_block(sub)
        rows_h = [r for r in headline
                  if r["condition"] == cond and r["rung"] in headline_rungs]
        rows_a = [r for r in headline if r["condition"] == cond]
        cost[cond] = cost_block(rows_h, rows_a, spend_field)

    doc = {
        "schema": SCHEMA_FIGURE_INPUT,
        "synthetic": False,
        "generated_utc": provenance["generated_utc"],
        "provenance": provenance,
        "conditions": conditions,
        "designed_rungs": list(designed),
        "exploratory_rungs": list(exploratory_rungs),
        "single_decision_conditions": [c for c in conditions
                                       if c in SINGLE_DECISION_CONDITIONS],
        "null_subset_label": f"frozen n=10 subset (seeds {AMENDMENT7_SUBSET_SEEDS[0]}-"
                             f"{AMENDMENT7_SUBSET_SEEDS[-1]}, Amendment 7)",
        "detection": detection,
        "null": null,
        "cost": cost,
        "refusal": {c: refusal_block([r for r in headline if r["condition"] == c])
                    for c in conditions},
    }
    if null_subset:
        doc["null_subset"] = null_subset
    return doc


def build_exploratory_arms(runs: list[dict], designed: tuple[str, ...],
                           exploratory_rungs: list[str], spend_field: str) -> dict:
    """Separate blocks. Never merged into a headline cell, at any stage."""
    arms: dict[str, dict] = {}
    for cond in sorted({r["condition"] for r in runs if r["arm"] == "exploratory_arm"}):
        rows = [r for r in runs if r["condition"] == cond]
        det = {}
        for rung in list(designed) + list(exploratory_rungs):
            sub = [r for r in rows if r["rung"] == rung]
            if sub:
                det[rung] = detection_block(sub)
        l0 = [r for r in rows if r["rung"] == NULL_RUNG]
        arms[cond] = {
            "status": "EXPLORATORY - excluded from every section 6 headline metric "
                      "and from the main figure (Amendment 9)",
            "n_runs": len(rows),
            "refusal": refusal_block(rows),
            "detection": det,
            "null": null_block(l0) if l0 else None,
            "cost": cost_block(rows, rows, spend_field),
            "brain_models": sorted({r["brain_model"] for r in rows if r["brain_model"]}),
            "configuration_asymmetry_disclosure": (
                "the two auditor brains are configured asymmetrically (Opus: adaptive "
                "thinking at high effort with prompt caching; GLM: low reasoning "
                "effort, caching off). Read the actual values from "
                "run_meta.brain.wire_params, not the config block (DECISIONS.md #23)."),
        }
    exploratory_rung_note = {
        r: "EXPLORATORY rung (Amendment 4): sealed and run blind, excluded from every "
           "headline metric and figure; graded last." for r in exploratory_rungs}
    return {"arms": arms, "exploratory_rungs": exploratory_rung_note}


def build_blind(runs: list[dict], spend_field: str, provenance: dict) -> dict:
    """Everything that does not require the sealed map."""
    conds = sorted({r["condition"] for r in runs})
    per = {}
    for c in conds:
        rows = [r for r in runs if r["condition"] == c]
        spend, unpriced = spend_of(rows, spend_field)
        per[c] = {
            "arm": rows[0]["arm"],
            "n_planned_attempts": len(rows),
            "n_verdict_bearing": sum(1 for r in rows
                                     if r["outcome"] == "verdict_bearing"),
            "n_terminal_refusal": sum(1 for r in rows
                                      if r["outcome"] == "refusal_no_verdict"),
            "n_no_verdict_other": sum(1 for r in rows
                                      if r["outcome"] == "no_verdict_other"),
            "refusal_rate": refusal_block(rows),
            "status_counts": dict(sorted(Counter(r["status"] for r in rows).items())),
            "recorded_spend_usd": spend,
            "spend_composition": spend_composition(rows),
            "spend_field_caveat": spend_caveat(rows),
            "mean_spend_per_planned_attempt_usd": (
                None if spend is None or not rows else round(spend / len(rows), 6)),
            "mean_spend_caveat": (
                "conditions differ in rung mix and in how many attempts ended in a cheap "
                "early refusal, so this is a per-attempt average, NOT a like-for-like "
                "per-run cost comparison. The paired same-seed comparison is the one to "
                "use for that (results/v0_v1_sealed_compare.json)."),
            "any_unpriced_component": unpriced,
            "spend_field": spend_field,
            "brain_models": sorted({r["brain_model"] for r in rows if r["brain_model"]}),
        }
    return {
        "schema": SCHEMA_BLIND,
        "mode": "BLIND - no sealed map was read",
        "withheld": ("every rung-keyed quantity: detection rates, the L0 false-positive "
                     "rate, dollars per FULL detection, and the per-candidate drift "
                     "ranking. These require the rung<->ID map and are emitted only "
                     "under --unsealed-map."),
        "why": ("emitting per-sealed-id results before unsealing would recreate exactly "
                "the ops-log exposure Amendment 6 clarification 7 disclosed"),
        "generated_utc": provenance["generated_utc"],
        "provenance": provenance,
        "n_runs": len(runs),
        "overall_refusal_rate": refusal_block(runs),
        "spend_composition_overall": spend_composition(runs),
        "spend_field_caveat_overall": spend_caveat(runs),
        "per_condition": per,
    }


def refusal_turn_block(runs: list[dict]) -> dict:
    """Distribution of WHICH turn refused, per condition.

    Terminal refusals and mid-run refusal events are separated: a run that refused on
    turn 3 and then finished with a verdict is a different phenomenon from one that
    refused on turn 3 and stopped there, and averaging them would hide both.
    """
    out: dict = {}
    for r in runs:
        if r.get("refusal_turn") is None:
            continue
        b = out.setdefault(r["condition"], {"terminal": [], "midrun": []})
        key = "terminal" if r["outcome"] == "refusal_no_verdict" else "midrun"
        b[key].append(r["refusal_turn"])
    for cond, b in out.items():
        for key in ("terminal", "midrun"):
            turns = sorted(b[key])
            b[key] = {
                "n": len(turns),
                "turns": turns,
                "distribution": {str(t): turns.count(t) for t in sorted(set(turns))},
                "median": (turns[len(turns) // 2] if turns else None),
            }
    return out


def build_inventory(runs: list[dict], spend_field: str, provenance: dict) -> dict:
    """A regenerated inventory over ALL conditions, not just the v0 glob.

    The committed results/analysis_run_inventory.json covers `results/runs/v0_cand_*`
    only, and analysis_instrument.load_runs derives candidate_id from config.notes,
    which is free text that ends in a sentence for the baselines. This inventory parses
    the candidate id from the run_id instead, so baseline rows are correct. It is
    written to a NEW path and overwrites nothing.
    """
    spend, unpriced = spend_of(runs, spend_field)
    return {
        "schema": "analysis_run_inventory/2",
        "note": ("outcomes and costs only - grades require unsealing and the "
                 "Phase-1/Phase-2 pipeline. Supersedes analysis_run_inventory/1 for "
                 "analysis purposes: it covers every condition and parses candidate "
                 "ids from run_id rather than from free-text config.notes."),
        "generated_utc": provenance["generated_utc"],
        "provenance": provenance,
        "n_runs": len(runs),
        "spend_field": spend_field,
        "total_recorded_spend_all_attempts_usd": spend,
        "any_unpriced_component": unpriced,
        "overall_refusal_rate": refusal_block(runs),
        "spend_composition": spend_composition(runs),
        "spend_field_caveat": spend_caveat(runs),
        # run_dir / results_root / agent_version travel with every row: run ids are NOT
        # unique across results roots, so `condition` is only checkable if the row says
        # which directory it came from.
        "runs": [{k: r[k] for k in (
            "run_id", "run_dir", "results_root", "agent_version",
            "condition", "arm", "candidate_id", "seed", "status", "outcome",
            "brain_usd", "targets_usd", "pod_usd", "total_usd", "cost_exact",
            "n_unpriced_calls", "turns_used", "brain_model", "harness_commit",
            "analysis_schema_version", "n_midrun_refusal_events", "refusal_turn",
            "rung")}
            for r in runs],
        "refusal_turns_by_condition": refusal_turn_block(runs),
    }


# ------------------------------------------------------------------------- tables
def _row(name: str, w: dict, denom: str, source: str) -> str:
    return f"| {name} | {AI.fmt_rate(w)} | {denom} | {source} |"


def _sensitivity_section(sens: dict | None, unsealed: bool) -> str:
    """Primary beside sensitivity, so a validity judgement is auditable, not asserted."""
    if not sens:
        return ""
    L: list[str] = []
    A = L.append
    A("")
    A("## Sensitivity — validity-gate exclusions")
    A("")
    A(f"**Primary numbers above include every run.** This section repeats them with "
      f"{len(sens['excluded_runs'])} run(s) dropped, so a reader can see whether a "
      f"judgement call about run validity moved anything: "
      f"{', '.join('`' + r + '`' for r in sens['excluded_runs'])}.")
    A("")
    A(f"- runs in primary: **{sens['n_runs_primary']}**")
    A(f"- runs in sensitivity: **{sens['n_runs_sensitivity']}**")
    A("")
    if not unsealed and sens.get("blind"):
        A("| condition | attempts (primary → sensitivity) | "
          "refusal rate (sensitivity) |")
        A("|---|---|---|")
        for c, b in sorted(sens["blind"]["per_condition"].items()):
            A(f"| {c} | → {b['n_planned_attempts']} | "
              f"{AI.fmt_rate(b['refusal_rate'])} |")
        A("")
        A("*Compare against the per-condition table above; the primary attempt counts "
          "are there.*")
    elif unsealed and sens.get("figure_input"):
        fi = sens["figure_input"]
        det = fi.get("detection", {})
        if det:
            A("| condition | rung | FULL / all planned attempts (sensitivity) |")
            A("|---|---|---|")
            for cond in sorted(det):
                for rung in sorted(det[cond]):
                    w = det[cond][rung].get("full_all_attempts_PRIMARY")
                    A(f"| {cond} | {rung} | {AI.fmt_rate(w) if w else '—'} |")
            A("")
        nul = fi.get("null", {})
        if nul:
            A("| condition | L0 false positives, verdict-bearing (sensitivity) |")
            A("|---|---|")
            for cond in sorted(nul):
                w = nul[cond].get("fp_frozen_rule_verdict_bearing_PRIMARY")
                A(f"| {cond} | {AI.fmt_rate(w) if w else '—'} |")
            A("")
        A("*Compare against sections 1 and 2; the primary rates are there.*")
    A("")
    return "\n".join(L)


def _refusal_turn_section(refusals: dict | None) -> str:
    """Which turn the auditor refused on - a datum, not just a label."""
    if not refusals:
        return ""
    L: list[str] = ["", "## Refusal turns", ""]
    L.append("Which turn carried the refusal, from `run_meta.brain.calls` "
             "(`stop_reason == \"refusal\"`). Terminal refusals ended the run with no "
             "verdict; mid-run refusals happened inside a run that nevertheless "
             "produced one (Amendment 6 clarification 1), and the two are never mixed.")
    L.append("")
    L.append("| condition | kind | n | median turn | distribution (turn × count) |")
    L.append("|---|---|---|---|---|")
    any_row = False
    for cond in sorted(refusals):
        for kind in ("terminal", "midrun"):
            b = refusals[cond][kind]
            if not b["n"]:
                continue
            any_row = True
            dist = ", ".join(f"turn {t} × {n}" for t, n in b["distribution"].items())
            L.append(f"| {cond} | {kind} | {b['n']} | {b['median']} | {dist} |")
    if not any_row:
        L.append("| — | — | 0 | — | no refusal carried a turn number |")
    L.append("")
    L.append("*Source: `run_meta.brain.calls`. No transcript is opened, so no verdict "
             "or reply text is read to produce this table.*")
    L.append("")
    return "\n".join(L)


def build_tables(doc: dict | None, blind: dict | None, arms: dict, floor: dict | None,
                 agree: dict, provenance: dict, unsealed: bool,
                 sens: dict | None = None, refusals: dict | None = None) -> str:
    L: list[str] = []
    A = L.append
    A("# Headline numbers — generated, never hand-assembled")
    A("")
    A("Every rate below is produced by a function in `scripts/analysis_instrument.py` "
      "and every interval is that module's two-sided 95% Wilson score interval "
      "(Amendment 6 clarification 3). Nothing on this page was typed by a human or "
      "computed in prose.")
    A("")
    A(f"- generated: `{provenance['generated_utc']}`")
    A(f"- mode: **{'UNSEALED' if unsealed else 'BLIND (no sealed map read)'}**")
    A(f"- spend field: `{provenance['spend_field']}`")
    A("- inputs:")
    for k, v in sorted(provenance["inputs"].items()):
        A(f"  - `{k}` — {v}")
    A("")

    if not unsealed:
        A("## BLIND MODE — rung-keyed tables are refused")
        A("")
        A(blind["withheld"])
        A("")
        A(f"*Why:* {blind['why']}")
        A("")
        A("### Per-condition outcomes (no rung identity involved)")
        A("")
        A("| condition | arm | attempts | verdict-bearing | terminal refusals | "
          "refusal rate (k/n, 95% Wilson) | recorded spend | mean $/attempt | "
          "cost complete |")
        A("|---|---|---|---|---|---|---|---|---|")
        for c, b in sorted(blind["per_condition"].items()):
            spend = "unpriced component" if b["any_unpriced_component"] \
                else f"${b['recorded_spend_usd']:.4f}"
            mean = ("—" if b["mean_spend_per_planned_attempt_usd"] is None
                    else f"${b['mean_spend_per_planned_attempt_usd']:.4f}")
            A(f"| {c} | {b['arm']} | {b['n_planned_attempts']} | "
              f"{b['n_verdict_bearing']} | {b['n_terminal_refusal']} | "
              f"{AI.fmt_rate(b['refusal_rate'])} | {spend} | {mean} | "
              f"{'no' if b['any_unpriced_component'] else 'yes'} |")
        A("")
        A(f"*Spend field: `{provenance['spend_field']}`. "
          f"{blind['spend_field_caveat_overall']}*")
        A("")
        A(f"*{next(iter(blind['per_condition'].values()))['mean_spend_caveat']}*")
        A("")
        A(f"**Overall terminal-refusal rate:** "
          f"{AI.fmt_rate(blind['overall_refusal_rate'])} "
          f"(denominator: all planned attempts across all conditions). Mid-run refusal "
          f"events inside verdict-bearing runs: "
          f"{blind['overall_refusal_rate']['n_midrun_refusal_events_in_verdict_bearing_runs']}.")
        A("")
        A("*Source for every row: the `run_meta.json` `status` field, mapped to an "
          "outcome by `analysis_instrument.outcome()` (Amendment 6 clarification 1). "
          "No verdict value is read.*")
        A("")
        A(_agreement_section(agree))
        A(_refusal_turn_section(refusals))
        A(_sensitivity_section(sens, unsealed))
        return "\n".join(L) + "\n"

    A("## 1 · Detection across designed rungs")
    A("")
    A("**Primary estimand:** FULL among **all planned seeded attempts** — a terminal "
      "refusal is a failed audit and counts as a non-detection (Amendment 6 "
      "clarification 2).")
    A("")
    A("| condition | rung | FULL (primary, all attempts) | FULL+PARTIAL (all attempts) "
      "| FULL (verdict-bearing, diagnostic) | verdict-bearing n | terminal refusals |")
    A("|---|---|---|---|---|---|---|")
    for cond in doc["conditions"]:
        for rung in doc["designed_rungs"]:
            cell = doc["detection"].get(cond, {}).get(rung)
            if not cell:
                continue
            A(f"| {cond} | {rung} | {AI.fmt_rate(cell['full_all_attempts_PRIMARY'])} | "
              f"{AI.fmt_rate(cell['full_plus_partial_all_attempts'])} | "
              f"{AI.fmt_rate(cell['full_verdict_bearing'])} | "
              f"{cell['n_verdict_bearing']}/{cell['n_planned_attempts']} | "
              f"{cell['n_terminal_refusal']} |")
    A("")
    A("*Source: `results/phase2_grades.jsonl` joined to `run_meta.json` outcomes; "
      "rates from `analysis_instrument.detection_rates`.*")
    A("")
    A("> L1–L3 are heterogeneous designed conditions at small n, not doses of a "
      "subtlety variable. No monotone trend is fitted, tested or implied.")
    A("")

    A("## 2 · The null (L0)")
    A("")
    A("**Primary estimand:** frozen-rule false positives among **VERDICT-BEARING** runs "
      "— a refusal is not a correct rejection, and counting it as one would understate "
      "confabulation (Amendment 6 clarification 2). Denominator named in every column "
      "heading below.")
    A("")
    A("| condition | FPR primary (frozen rule, verdict-bearing) | strict rule "
      "(verdict-bearing) | all-attempt burden | attempts | verdict-bearing | refusals |")
    A("|---|---|---|---|---|---|---|")
    for cond in doc["conditions"]:
        cell = doc["null"].get(cond)
        if not cell:
            continue
        A(f"| {cond} | {AI.fmt_rate(cell['fp_frozen_rule_verdict_bearing_PRIMARY'])} | "
          f"{AI.fmt_rate(cell['fp_strict_rule_verdict_bearing'])} | "
          f"{AI.fmt_rate(cell['fp_frozen_rule_all_attempts'])} | "
          f"{cell['n_planned_attempts']} | {cell['n_verdict_bearing']} | "
          f"{cell['n_terminal_refusal']} |")
    A("")
    if doc.get("null_subset"):
        A(f"### Amendment 7 subset — {doc['null_subset_label']}")
        A("")
        A("Reported beside the full-n primary so a reader can verify the estimate did "
          "not move when the additional seeds were added.")
        A("")
        A("| condition | FPR (frozen rule, verdict-bearing) | attempts | "
          "verdict-bearing |")
        A("|---|---|---|---|")
        for cond, cell in sorted(doc["null_subset"].items()):
            A(f"| {cond} | "
              f"{AI.fmt_rate(cell['fp_frozen_rule_verdict_bearing_PRIMARY'])} | "
              f"{cell['n_planned_attempts']} | {cell['n_verdict_bearing']} |")
        A("")
    A("*The verbatim claim text of ALL L0 verdicts is published separately and "
      "un-cherry-picked (Amendment 3 item 4); this table carries only the counts.*")
    A("")

    A("## 3 · Refusal — an operational outcome, not missing data")
    A("")
    A("| condition | terminal refusal (k/n, 95% Wilson) | mid-run refusal events in "
      "verdict-bearing runs |")
    A("|---|---|---|")
    for cond in doc["conditions"]:
        w = doc["refusal"][cond]
        A(f"| {cond} | {AI.fmt_rate(w)} | "
          f"{w['n_midrun_refusal_events_in_verdict_bearing_runs']} |")
    A("")
    A("> The fixed battery and the drift floor **cannot** incur a brain-side refusal by "
      "construction. That asymmetry is reported, not equalized (Amendment 6 "
      "clarification 6). Every rate here is for one recipe × one brain × this target "
      "set.")
    A("")

    A("## 4 · Dollars per FULL detection")
    A("")
    A("**Primary:** complete recorded spend "
      f"(`{provenance['spend_field']}`) over **all planned attempts on HEADLINE pairs** "
      "÷ FULL detections. An audit programme pays for its refusals, so refused "
      "attempts' spend is in the numerator. Zero detections yields `undefined`, never "
      "infinity; any unpriced component removes the condition from the dollar ranking "
      "entirely. The exploratory pair is excluded (Amendment 4 item 2) and appears "
      "only as a labelled diagnostic, as does the `brain_usd`-only variant.")
    A("")
    A(f"| condition | primary $/FULL | total spend (`{provenance['spend_field']}`, all "
      "attempts) | FULL detections | in dollar ranking? |")
    A("|---|---|---|---|---|")
    for cond in doc["conditions"]:
        c = doc["cost"][cond]
        if not c.get("eligible_for_dollar_ranking", True):
            A(f"| {cond} | excluded (unpriced component) | unknown (null, never zero) "
              f"| — | no |")
            continue
        p = c["primary"]
        pv = p if isinstance(p, str) else f"${p:,.6f}"
        A(f"| {cond} | {pv} | ${c['total_spend_all_attempts_usd']:,.6f} | "
          f"{c['n_full_detections']} | yes |")
    A("")
    _scope = next((c.get("scope_note") for c in doc["cost"].values()
                   if c.get("scope_note")), "")
    A(f"*Scope: {_scope}*")
    A("")
    _cav = next((c.get("spend_field_caveat") for c in doc["cost"].values()
                 if c.get("spend_field_caveat")
                 and "unpriced" not in c["spend_field_caveat"]), "")
    if _cav:
        A(f"*What the numerator contains: {_cav}*")
        A("")
    A("| condition | diagnostic: `brain_usd` only | diagnostic: including the "
      "exploratory pair |")
    A("|---|---|---|")
    for cond in doc["conditions"]:
        c = doc["cost"][cond]

        def _p(v: dict | None) -> str:
            if not v or not v.get("eligible_for_dollar_ranking", True):
                return "excluded (unpriced)"
            p = v.get("primary")
            return p if isinstance(p, str) else f"${p:,.6f}"
        A(f"| {cond} | {_p(c.get('variant_brain_usd_only'))} | "
          f"{_p(c.get('variant_including_exploratory_rungs'))} |")
    A("")
    A("*Both columns above are labelled diagnostics. Neither is the headline number.*")
    A("")

    if doc.get("exploratory_rungs"):
        A("## 5 · Exploratory rung — reported separately, never mixed in")
        A("")
        A("| condition | rung | FULL (all attempts) | FULL+PARTIAL | verdict-bearing n |")
        A("|---|---|---|---|---|")
        for cond in doc["conditions"]:
            for rung in doc["exploratory_rungs"]:
                cell = doc["detection"].get(cond, {}).get(rung)
                if not cell:
                    continue
                A(f"| {cond} | {rung} (EXPLORATORY) | "
                  f"{AI.fmt_rate(cell['full_all_attempts_PRIMARY'])} | "
                  f"{AI.fmt_rate(cell['full_plus_partial_all_attempts'])} | "
                  f"{cell['n_verdict_bearing']}/{cell['n_planned_attempts']} |")
        A("")

    if arms.get("arms"):
        A("## 6 · Exploratory arms — separate blocks")
        A("")
        for name, a in sorted(arms["arms"].items()):
            A(f"### {name} — {a['status']}")
            A("")
            A(f"- runs: {a['n_runs']}; brains: {', '.join(a['brain_models']) or 'n/a'}")
            A(f"- terminal refusal: {AI.fmt_rate(a['refusal'])}")
            A(f"- {a['configuration_asymmetry_disclosure']}")
            A("")

    if floor:
        A("## 7 · Baseline 2 — distributional drift floor")
        A("")
        A("Threshold-free and behaviour-blind by construction: it scores raw response "
          "text. It is **not** a comparable success rate and is deliberately absent "
          "from the main figure.")
        A("")
        A("| pair | mean \\|Δ logprob\\| | approx top-k sym KL | tokens scored |")
        A("|---|---|---|---|")
        for p in floor["pairs"]:
            label = ("base vs base (must be exactly 0.0)" if p["is_base_vs_base"]
                     else p.get("rung") or p["pair"])
            A(f"| {label} | {p['mean_abs_logprob_delta']} | "
              f"{p['approx_sym_kl_topk']} | {p['n_tokens_scored']} |")
        A("")
        A("*Source: `results/baseline_kl_drift_sealed.json`.*")
        A("")

    A(_agreement_section(agree))
    A(_refusal_turn_section(refusals))
    A(_sensitivity_section(sens, unsealed))
    return "\n".join(L) + "\n"


def _agreement_section(agree: dict) -> str:
    L = ["## Human–judge agreement (Addendum C)", ""]
    L.append(f"- runs carrying both a human and a judge grade: "
             f"**{agree['n_runs_with_both_grades']}**")
    L.append(f"- {agree['primary_rule']}")
    L.append(f"- {agree['disclosure']}")
    L.append("")
    if agree.get("note"):
        L.append(f"*{agree['note']}*")
        L.append("")
        return "\n".join(L)
    L.append("| label set | n | raw agreement | positive agreement (FULL) | "
             "negative agreement (FULL) | Cohen's kappa (secondary) |")
    L.append("|---|---|---|---|---|---|")
    for name in ("detection_FULL_PARTIAL_MISS", "null_FP_CR", "combined"):
        a = agree.get(name, {})
        if not a or a.get("n", 0) == 0:
            L.append(f"| {name} | 0 | — | — | — | — |")
            continue
        L.append(f"| {name} | {a['n']} | {a['raw_percent_agreement']} | "
                 f"{a['positive_agreement_FULL']} | {a['negative_agreement_FULL']} | "
                 f"{a['cohens_kappa_SECONDARY']} |")
    L.append("")
    L.append("*Kappa is a secondary descriptor only — unstable at this n, and undefined "
             "when either rater uses one label throughout. Human–judge agreement is not "
             "evidence that the judge is deterministic.*")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------- CLI
def write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)
                    + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", nargs="*", default=[
        "results/runs/v0_cand_*", "results/runs/v1_cand_*",
        "results/runs/bat_cand_*", "results/runs/intro_cand_*",
        "results/runs_glm/*"])
    ap.add_argument("--phase1", default="results/phase1_claims.jsonl")
    ap.add_argument("--phase2", default="results/phase2_grades.jsonl")
    ap.add_argument("--floor", default="results/baseline_kl_drift_sealed.json")
    ap.add_argument("--unsealed-map", default=None,
                    help="PATH TO THE SEALED RUNG MAP. Omit to run blind. Passing it "
                         "is the unsealing step and is recorded loudly.")
    ap.add_argument("--designed-rungs", nargs="*", default=list(DEFAULT_DESIGNED_RUNGS))
    ap.add_argument("--spend-field", default="total_usd",
                    choices=["brain_usd", "total_usd"],
                    help="numerator for dollars-per-detection. Default `total_usd` = "
                         "COMPLETE recorded spend, per Amendment 6 clarification 2. "
                         "`brain_usd` is emitted beside it as a labelled diagnostic "
                         "either way.")
    ap.add_argument("--outdir", default="results/analysis")
    ap.add_argument("--now", default=None,
                    help="fix the generated_utc stamp, for deterministic tests")
    ap.add_argument("--exclude-runs", nargs="*", default=[],
                    help="run_ids to drop in a SENSITIVITY pass. The primary numbers "
                         "always keep every run; this adds a second set computed "
                         "without them, and tables.md prints both. Use it when a run "
                         "survived a validity gate on a judgement call, so a reader "
                         "can see whether that call moved anything.")
    a = ap.parse_args(argv)

    runs = load_runs(a.runs)
    if not runs:
        print("no campaign runs matched --runs; nothing to join", file=sys.stderr)
        return 2

    inputs = {}
    for label, p in (("phase1_claims", a.phase1), ("phase2_grades", a.phase2),
                     ("floor", a.floor)):
        path = Path(p)
        inputs[label] = (f"{p} (sha256 {_sha256(path)[:16]}...)" if path.exists()
                         else f"{p} (ABSENT — not yet produced)")
    inputs["run_dirs"] = f"{len(runs)} run_meta.json files from {a.runs}"

    claims = load_jsonl_last_per_run(Path(a.phase1), "phase1")
    grades = load_jsonl_last_per_run(Path(a.phase2), "phase2",
                                     keyed_by_condition=True)

    by_cand = None
    unsealed = a.unsealed_map is not None
    if unsealed:
        cids = {r["candidate_id"] for r in runs if r["candidate_id"]}
        by_cand = load_sealed_map(Path(a.unsealed_map), cids)
        banner = ("\n" + "!" * 74 + "\n"
                  "!!  UNSEALED RUN — the rung<->ID map has been read.\n"
                  f"!!  map: {a.unsealed_map}\n"
                  "!!  This is the section 8 point of no return. Nothing in sections\n"
                  "!!  2-7 of the preregistration may change from here.\n"
                  + "!" * 74 + "\n")
        print(banner)
        print(banner, file=sys.stderr)
        for r in runs:
            r["rung"] = by_cand.get(r["candidate_id"])
        inputs["sealed_map"] = (f"{a.unsealed_map} (sha256 "
                                f"{_sha256(Path(a.unsealed_map))[:16]}...)")
    else:
        print("BLIND MODE: no sealed map read; every rung is null and all rung-keyed "
              "outputs are refused. Pass --unsealed-map to produce them.")
        inputs["sealed_map"] = "NOT READ (blind mode)"

    problems = attach_phase1(runs, claims) + attach_phase2(runs, grades, by_cand)
    if problems:
        print("JOIN REFUSED — the inputs disagree with each other:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 3

    # A named run that does not exist is almost always a typo, and silently ignoring
    # it would report a sensitivity analysis that excluded nothing.
    excluded = list(dict.fromkeys(a.exclude_runs))
    if excluded:
        known = {r["run_id"] for r in runs}
        missing = [r for r in excluded if r not in known]
        if missing:
            print(f"--exclude-runs names {len(missing)} run(s) that are not in the "
                  f"joined set: {missing}", file=sys.stderr)
            return 4

    provenance = {
        "generated_by": "scripts/analysis_join.py",
        "generated_utc": a.now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": "unsealed" if unsealed else "blind",
        "spend_field": a.spend_field,
        "estimands_from": "scripts/analysis_instrument.py",
        "inputs": inputs,
        "harness_commits_seen": sorted({r["harness_commit"] for r in runs
                                        if r["harness_commit"]}),
        "n_runs_without_harness_commit": sum(1 for r in runs
                                             if not r["harness_commit"]),
        "excluded_runs_sensitivity": excluded,
        "excluded_runs_note": (
            "PRIMARY numbers include every run. These run_ids are additionally dropped "
            "in a parallel SENSITIVITY pass so a reader can see whether a validity "
            "judgement changed the answer." if excluded else "none"),
    }

    out = Path(a.outdir)
    written: list[Path] = []
    agree = agreement_blocks(runs)
    arms: dict = {"arms": {}, "exploratory_rungs": {}}

    inv = out / "run_inventory.json"
    write_json(inv, build_inventory(runs, a.spend_field, provenance))
    written.append(inv)

    ag = out / "agreement.json"
    write_json(ag, agree)
    written.append(ag)

    floor = None
    doc = blind = None
    if unsealed:
        seen = sorted({r["rung"] for r in runs if r["rung"]})
        exploratory_rungs = [r for r in seen
                             if r not in a.designed_rungs and r != NULL_RUNG]
        arms = build_exploratory_arms(runs, tuple(a.designed_rungs),
                                      exploratory_rungs, a.spend_field)
        doc = build_figure_input(runs, tuple(a.designed_rungs), exploratory_rungs,
                                 a.spend_field, provenance)
        doc["exploratory_arms"] = arms
        floor = load_floor(Path(a.floor))
        if floor and by_cand:
            for p in floor["pairs"]:
                p["rung"] = by_cand.get(p["candidate_id"]) if p["candidate_id"] else None
            doc["baseline_floor"] = floor
        fi = out / "analysis_figure_input.json"
        write_json(fi, doc)
        written.append(fi)
    else:
        blind = build_blind(runs, a.spend_field, provenance)
        bo = out / "blind_outcomes.json"
        write_json(bo, blind)
        written.append(bo)

    # SENSITIVITY pass. Same code path, same estimands, one smaller run list - so the
    # comparison cannot drift from the primary by construction.
    sens = None
    if excluded:
        kept = [r for r in runs if r["run_id"] not in set(excluded)]
        sens = {"excluded_runs": excluded,
                "n_runs_primary": len(runs), "n_runs_sensitivity": len(kept)}
        if unsealed:
            seen_s = sorted({r["rung"] for r in kept if r["rung"]})
            expl_s = [r for r in seen_s
                      if r not in a.designed_rungs and r != NULL_RUNG]
            sens["figure_input"] = build_figure_input(
                kept, tuple(a.designed_rungs), expl_s, a.spend_field, provenance)
        else:
            sens["blind"] = build_blind(kept, a.spend_field, provenance)
        sp = out / "sensitivity_excluded_runs.json"
        write_json(sp, sens)
        written.append(sp)

    tab = out / "tables.md"
    tab.parent.mkdir(parents=True, exist_ok=True)
    tab.write_text(build_tables(doc, blind, arms, floor, agree, provenance, unsealed,
                                sens, refusal_turn_block(runs)),
                   encoding="utf-8")
    written.append(tab)

    print(f"\n{len(runs)} runs joined "
          f"({sum(1 for r in runs if r['grade'])} carry a Phase-2 grade)")
    for p in written:
        print(f"wrote   {p}")
    if unsealed:
        print("\nNEXT: python scripts/make_figures.py --input "
              f"{out / 'analysis_figure_input.json'}")
    print("\nREMINDER (CLAUDE.md): an agent-reported metric is a draft until a human "
          "has looked at the file it came from.")
    return 0


def cli(argv: list[str] | None = None) -> int:
    """A join that cannot be trusted stops with a message, not a traceback."""
    try:
        return main(argv)
    except JoinError as e:
        print(f"JOIN REFUSED: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(cli())
