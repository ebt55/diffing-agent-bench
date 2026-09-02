"""Phase-1 MECHANICAL extraction - post-unsealing, for runs the human queue never held.

DECISIONS.md #32 ruling R1 / #33: Baseline 1 (fixed battery), Baseline 3
(introspection) and the exploratory GLM arm produced outputs but were never in Ebin's
Phase-1 queue, so they carry no Phase-1 claim row and can not be Phase-2 graded. Their
Phase-1 extraction happens AFTER unsealing. To remove human selection from a
non-blind extraction, it is done by this script, mechanically:

  * verdict type, stated confidence, the hypothesis text and every evidence bullet are
    copied VERBATIM from the run's own final verdict payload (`run_meta.json:verdict`,
    the same object the transcript's `run_end` event carries and the human Phase-1 UI
    displayed for the Opus arms). The whole field is copied; nothing is selected,
    trimmed or paraphrased.
  * a field with no equivalent in the payload is null. Never invented text.
  * a refusal / no-verdict run gets empty fields plus the note, exactly like the
    human-extracted refusal rows.
  * `mechanical_extractor_notes` starts with the fixed sentence
    "mechanical extraction, post-unseal, no human selection; source=<file:field>" and
    then states, from the files only, anything a grader must know (majority-vote
    provenance for Baseline 1, a payload missing its `verdict` field, a forced turn).
  * every row carries `condition`, because the GLM arm reuses the Opus arm's run ids
    byte-for-byte (DECISIONS.md #26/#27): a Phase-1 row for a GLM run keyed by run_id
    alone would displace the Opus row. Every consumer keys claims (condition, run_id).

APPEND-ONLY. The existing human-extracted rows are never rewritten; the script refuses
to run if any target (condition, run_id) already has a claim row, and verifies after
writing that the file still starts with exactly the bytes it started with.

It also appends the new runs to results/phase1_order.json as new blocks (shuffled with
a committed seed, as the human blocks were), so the record of what was extracted, when
and how is in the same file as the human queue.

Run:
  python scripts/phase1_mechanical_extract.py --dry-run
  python scripts/phase1_mechanical_extract.py
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import analysis_join as AJ  # noqa: E402  (load_run = the join's own reader)

NOTE_PREFIX = "mechanical extraction, post-unseal, no human selection"
EXTRACTED_BY = "mechanical:scripts/phase1_mechanical_extract.py"
# The sentinel phase1_grade.py stores in a quote's `turn` for the submitted-verdict
# cell; the Phase-2 page and the judge payload both render it as "submitted verdict".
QUOTE_TURN = "verdict"
DEFAULT_RUNS = ["results/runs/bat_cand_*", "results/runs/intro_cand_*",
                "results/runs_glm/*"]
# One order block per group, each with its own committed seed (blocks 1-3 used
# 20260901..20260903).
ORDER_GROUPS = (
    ("baselines", ("battery", "introspection"), 20260904),
    ("glm_v0", ("glm_v0",), 20260905),
)


class ExtractError(RuntimeError):
    pass


def run_end_verdict(run_dir: Path) -> tuple[dict | None, str | None, bool]:
    """The verdict carried by the transcript's LAST run_end event (what phase1_grade.py
    showed the human). Returns (verdict, status, found)."""
    tp = run_dir / "transcript.jsonl"
    if not tp.exists():
        return None, None, False
    v, status, found = None, None, False
    for line in tp.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("type") == "run_end":
            v, status, found = r.get("verdict"), r.get("status"), True
    return v, status, found


def extract_row(run_dir: Path, now: str) -> dict:
    r = AJ.load_run(run_dir)
    if r is None:
        raise ExtractError(f"{run_dir}: not a campaign run directory (no run_meta.json, "
                           f"or its results root/prefix resolves to no condition)")
    meta = json.loads((run_dir / "run_meta.json").read_text(encoding="utf-8"))
    v = meta.get("verdict")
    src = f"{run_dir.as_posix()}/run_meta.json:verdict"
    notes = [f"{NOTE_PREFIX}; source={src}"]

    # The transcript's run_end verdict is the object the human UI displayed for the
    # Opus arms. If run_meta disagrees with it, something rewrote one of them and this
    # extraction must not guess which is the run's own verdict.
    tv, _tstatus, found = run_end_verdict(run_dir)
    if found and (tv or None) != (v or None):
        raise ExtractError(f"{run_dir}: run_meta.json:verdict differs from the "
                           f"transcript's run_end verdict; refusing to extract")

    cid = AJ.CAND_RE.search(r["run_id"])
    row = {
        "run_id": r["run_id"],
        "sealed_candidate_id": cid.group(1) if cid else None,
        "condition": r["condition"],
        "outcome": r["outcome"],
        "verdict_type": None,
        "agent_stated_confidence": None,
        "top_hypothesis_verbatim": "",
        "supporting_quotes": [],
        "explicit_disconfirming_evidence": None,      # no such field in any payload
        "harness_vs_model_attribution_notes": None,   # a human judgement; none made
        "mechanical_extractor_notes": "",
        "extracted_by": EXTRACTED_BY,
        "extracted_utc": now,
    }

    if r["outcome"] == "verdict_bearing" and isinstance(v, dict):
        row["verdict_type"] = v.get("verdict")
        row["agent_stated_confidence"] = v.get("confidence")
        hyp = v.get("hypothesis")
        row["top_hypothesis_verbatim"] = hyp if isinstance(hyp, str) else ""
        ev = v.get("key_evidence") or []
        row["supporting_quotes"] = [
            {"quote": e if isinstance(e, str) else json.dumps(e, ensure_ascii=False),
             "turn": QUOTE_TURN} for e in ev]
        if "verdict" not in v:
            notes.append("the submitted payload carries NO `verdict` field (the brain "
                         "violated the submit_verdict schema); verdict_type=null, not "
                         "inferred from the hypothesis text")
        if v.get("confidence") is None:
            notes.append("no `confidence` in the payload; agent_stated_confidence=null")
        if not isinstance(hyp, str):
            notes.append("no string `hypothesis` in the payload; left empty")
        if meta.get("status") == "completed_forced":
            notes.append("status=completed_forced: the verdict was submitted on the "
                         "forced extra turn after the query budget was exhausted")
        jm = meta.get("judge_majority")
        if isinstance(jm, dict):
            notes.append(
                f"Baseline 1 (fixed battery): verdict_type is the majority of "
                f"{jm.get('n_calls')} seeded judge calls (seeds {jm.get('seeds')}, "
                f"vote_counts={json.dumps(jm.get('vote_counts'), sort_keys=True)}, "
                f"unanimous={jm.get('unanimous')}); hypothesis and evidence are the "
                f"canonical call's (seed {jm.get('canonical_from_seed')}; rule: "
                f"{jm.get('canonical_rule')})")
        if meta.get("baseline") == "introspection":
            notes.append("Baseline 3 (introspection): one judge call over the "
                         "candidate's own self-descriptions; no comparison model was "
                         "queried, so `verdict` is the judge's reading of what the "
                         "candidate claims changed, not a pair comparison")
    else:
        # No verdict: empty fields plus the note, as the human refusal rows were written.
        turn = r.get("refusal_turn")
        notes.append(f"no verdict: status={meta.get('status')}, outcome={r['outcome']}"
                     + (f", refusal at turn {turn}" if turn is not None else ""))

    row["mechanical_extractor_notes"] = "; ".join(notes)
    return row


def collect_run_dirs(globs: list[str]) -> list[Path]:
    found = {Path(p).resolve() for g in globs for p in glob.glob(g)
             if (Path(p) / "run_meta.json").exists()}
    return sorted(found, key=lambda p: (p.parent.name, p.name))


def append_order_blocks(order_path: Path, rows: list[dict], now: str) -> list[dict]:
    doc = {"schema": "phase1_order/1", "blocks": []}
    if order_path.exists():
        doc = json.loads(order_path.read_text(encoding="utf-8"))
    added = []
    for name, conds, seed in ORDER_GROUPS:
        ids = sorted(r["run_id"] for r in rows if r["condition"] in conds)
        if not ids:
            continue
        for b in doc["blocks"]:
            if b.get("extraction") == "mechanical" and \
                    tuple(b.get("conditions") or ()) == tuple(conds):
                raise ExtractError(f"{order_path}: a mechanical block for {conds} "
                                   f"already exists (block {b.get('block')})")
        rng = random.Random(seed)
        rng.shuffle(ids)
        block = {
            "block": len(doc["blocks"]) + 1,
            "seed": seed,
            "n": len(ids),
            "created_utc": now,
            "conditions": list(conds),
            "extraction": "mechanical",
            "note": ("POST-UNSEAL MECHANICAL EXTRACTION (DECISIONS.md #32 R1 / #33): "
                     "these runs were never in the human Phase-1 queue; their claim "
                     "rows were copied verbatim from each run's own verdict payload by "
                     "scripts/phase1_mechanical_extract.py, with no human selection. "
                     "Shuffled with the committed seed for the record only - Phase 2 "
                     "orders its own queue."),
            "run_ids": ids,
        }
        if "glm_v0" in conds:
            block["id_collision_disclosure"] = (
                "the GLM arm ran as agent-version v0, so these run ids are byte-identical "
                "to block 1's Opus ids and differ only by results root "
                "(results/runs_glm/). Claim rows carry condition=glm_v0 and every "
                "consumer keys claims by (condition, run_id).")
        doc["blocks"].append(block)
        added.append(block)
    if added:
        order_path.parent.mkdir(parents=True, exist_ok=True)
        order_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return added


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", nargs="*", default=DEFAULT_RUNS,
                    help="run-directory globs (parent dir must be results/runs or "
                         "results/runs_glm, as the join requires)")
    ap.add_argument("--claims", default="results/phase1_claims.jsonl")
    ap.add_argument("--order", default="results/phase1_order.json")
    ap.add_argument("--no-order", action="store_true",
                    help="do not touch the order file")
    ap.add_argument("--now", default=None, help="fixed UTC stamp (tests)")
    ap.add_argument("--dry-run", action="store_true",
                    help="extract and summarise; write nothing")
    a = ap.parse_args(argv)
    now = a.now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    dirs = collect_run_dirs(a.runs)
    if not dirs:
        print("no run directories matched --runs", file=sys.stderr)
        return 2
    try:
        rows = [extract_row(d, now) for d in dirs]
    except ExtractError as e:
        print(f"EXTRACTION REFUSED: {e}", file=sys.stderr)
        return 3

    claims_path = Path(a.claims)
    existing = (AJ.load_jsonl_last_per_run(claims_path, "phase1", keyed_by_condition=True)
                if claims_path.exists() else {})
    dup = [(r["condition"], r["run_id"]) for r in rows
           if (r["condition"], r["run_id"]) in existing]
    if dup:
        print(f"EXTRACTION REFUSED: {len(dup)} target run(s) already carry a Phase-1 "
              f"claim row; this script never rewrites a row. First: {dup[:3]}",
              file=sys.stderr)
        return 3

    by_cond: dict[str, list[dict]] = {}
    for r in rows:
        by_cond.setdefault(r["condition"], []).append(r)
    print(f"{len(rows)} run(s) extracted mechanically from {len(dirs)} directories")
    for cond, rs in sorted(by_cond.items()):
        n_vb = sum(1 for r in rs if r["outcome"] == "verdict_bearing")
        n_null_vt = sum(1 for r in rs if r["outcome"] == "verdict_bearing"
                        and r["verdict_type"] is None)
        n_q = sum(len(r["supporting_quotes"]) for r in rs)
        print(f"  {cond:14s} rows {len(rs):3d}  verdict-bearing {n_vb:3d}  "
              f"no-verdict {len(rs) - n_vb:3d}  payload-without-verdict-field "
              f"{n_null_vt:2d}  quotes {n_q:4d}")
    print(f"existing claim rows (last per (condition, run_id)): {len(existing)}")

    if a.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    before = claims_path.read_bytes() if claims_path.exists() else b""
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    claims_path.parent.mkdir(parents=True, exist_ok=True)
    with claims_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(payload)
    after = claims_path.read_bytes()
    if not after.startswith(before) or \
            len(after) != len(before) + len(payload.encode("utf-8")):
        print("POST-WRITE CHECK FAILED: the claims file did not grow by exactly the "
              "appended rows. Inspect it before doing anything else.", file=sys.stderr)
        return 4
    print(f"appended {len(rows)} row(s) to {claims_path} "
          f"({len(before)} -> {len(after)} bytes; prefix unchanged)")

    if not a.no_order:
        try:
            added = append_order_blocks(Path(a.order), rows, now)
        except ExtractError as e:
            print(f"ORDER FILE NOT UPDATED: {e}", file=sys.stderr)
            return 5
        for b in added:
            print(f"order block {b['block']}: {b['conditions']} n={b['n']} "
                  f"seed={b['seed']} -> {a.order}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
