"""Synthetic proof for scripts/phase1_mechanical_extract.py.

Builds fake run directories under a temp root - a battery run with a majority-vote
block, an introspection run, and four GLM-arm runs (a normal verdict, a payload that
lacks its `verdict` field, a terminal refusal, a forced submission) - beside a
pre-existing claims file holding two HUMAN rows, one of which shares its run_id with a
GLM run. Then it checks that the script:

  * copies verdict type, confidence, hypothesis and every evidence bullet VERBATIM;
  * nulls what has no equivalent and never invents text;
  * writes a refusal as empty fields plus the note;
  * APPENDS and leaves the human rows byte-identical; refuses to run twice;
  * keys the colliding GLM row by condition so it never displaces the Opus row;
  * appends the order blocks with the committed seeds;
  * refuses when run_meta and the transcript disagree about the verdict.

Every id here is SYNTH*; nothing under results/ is touched.

Run: python scripts/test_phase1_mechanical_extract.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import analysis_join as AJ                 # noqa: E402
import phase1_mechanical_extract as ME    # noqa: E402

_checks = 0
_fails: list[str] = []


def check(cond: bool, label: str) -> None:
    global _checks
    _checks += 1
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        _fails.append(label)


def write_run(root: Path, sub: str, run_id: str, *, status: str, verdict,
              extra: dict | None = None, transcript_verdict="SAME") -> Path:
    d = root / sub / run_id
    d.mkdir(parents=True, exist_ok=True)
    calls = [{"turn": 1, "stop_reason": "refusal" if status == "brain_refusal"
              else "tool_use", "cost_exact": True}]
    meta = {"run_id": run_id, "status": status, "seed": 0, "cost_exact": True,
            "verdict": verdict,
            "brain": {"model": "SYNTH-brain", "turns_used": 1, "n_calls": 1,
                      "cost_usd": 0.01, "cost_exact": True, "n_unpriced_calls": 0,
                      "calls": calls},
            "cost": {"brain_usd": 0.01, "targets_usd": 0.0, "pod_usd": 0.0,
                     "total_usd": 0.01, "cost_exact": True}}
    meta.update(extra or {})
    (d / "run_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    tv = verdict if transcript_verdict == "SAME" else transcript_verdict
    lines = [{"i": 1, "type": "run_start", "run_id": run_id},
             {"i": 2, "type": "run_end", "status": status, "verdict": tv}]
    (d / "transcript.jsonl").write_text(
        "".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return d


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="mech_extract_"))
    HYP_BAT = "SYNTHETIC hypothesis: model_B does X - not data"
    EV_BAT = ["SYNTHETIC evidence 1 \"with quotes\"", "SYNTHETIC evidence 2"]
    v_bat = {"verdict": "diff", "hypothesis": HYP_BAT, "confidence": 91,
             "key_evidence": EV_BAT}
    write_run(root, "runs", "bat_cand_SYNTHb", status="completed", verdict=v_bat,
              extra={"baseline": "battery_no_agency",
                     "judge_majority": {"seeds": [0, 1, 2], "n_calls": 3,
                                        "majority_verdict": "diff", "unanimous": False,
                                        "vote_counts": {"diff": 2,
                                                        "no_meaningful_diff": 1},
                                        "canonical_from_seed": 0,
                                        "canonical_rule": "SYNTH rule"}})
    v_int = {"verdict": "diff", "hypothesis": "SYNTHETIC intro hypothesis",
             "confidence": 70, "key_evidence": ["SYNTH intro evidence"]}
    write_run(root, "runs", "intro_cand_SYNTHc", status="completed", verdict=v_int,
              extra={"baseline": "introspection"})
    v_glm = {"verdict": "no_meaningful_diff", "hypothesis": "SYNTHETIC glm ruled out",
             "confidence": 60, "key_evidence": ["SYNTH glm e1", "SYNTH glm e2",
                                                "SYNTH glm e3"]}
    write_run(root, "runs_glm", "v0_cand_SYNTHb_s0", status="completed", verdict=v_glm)
    v_noverdict = {"hypothesis": "SYNTHETIC glm without a verdict field",
                   "confidence": 55, "key_evidence": ["SYNTH e"]}
    write_run(root, "runs_glm", "v0_cand_SYNTHb_s1", status="completed",
              verdict=v_noverdict)
    write_run(root, "runs_glm", "v0_cand_SYNTHb_s2", status="brain_refusal",
              verdict=None)
    v_forced = {"verdict": "diff", "hypothesis": "SYNTHETIC forced", "confidence": 40,
                "key_evidence": []}
    write_run(root, "runs_glm", "v0_cand_SYNTHb_s3", status="completed_forced",
              verdict=v_forced)

    # Pre-existing HUMAN rows: one shares its run_id with the GLM run above.
    human = [
        {"run_id": "v0_cand_SYNTHb_s0", "sealed_candidate_id": "cand_SYNTHb",
         "outcome": "verdict_bearing", "verdict_type": "diff",
         "agent_stated_confidence": 88, "top_hypothesis_verbatim": "HUMAN Opus row",
         "supporting_quotes": [{"quote": "HUMAN quote", "turn": "3"}],
         "explicit_disconfirming_evidence": None,
         "harness_vs_model_attribution_notes": "none",
         "mechanical_extractor_notes": "none", "extracted_by": "human",
         "extracted_utc": "2026-09-02T00:00:00Z"},
        {"run_id": "v0_cand_SYNTHa_s8", "sealed_candidate_id": "cand_SYNTHa",
         "outcome": "refusal_no_verdict", "verdict_type": None,
         "agent_stated_confidence": None, "top_hypothesis_verbatim": "",
         "supporting_quotes": [], "explicit_disconfirming_evidence": None,
         "harness_vs_model_attribution_notes": "none",
         "mechanical_extractor_notes": "Brain refusal at turn 5; no verdict.",
         "extracted_by": "human", "extracted_utc": "2026-09-02T00:00:00Z"},
    ]
    claims = root / "claims.jsonl"
    claims.write_text("".join(json.dumps(r) + "\n" for r in human), encoding="utf-8")
    order = root / "order.json"
    order.write_text(json.dumps({"schema": "phase1_order/1", "blocks": [
        {"block": 1, "seed": 1, "n": 2, "run_ids": [r["run_id"] for r in human]}]}),
        encoding="utf-8")
    before = claims.read_bytes()
    order_before = order.read_bytes()
    globs = [str(root / "runs" / "bat_cand_*"), str(root / "runs" / "intro_cand_*"),
             str(root / "runs_glm" / "*")]
    NOW = "2026-09-03T00:00:00Z"

    print("1. --dry-run writes nothing")
    rc = ME.main(["--runs", *globs, "--claims", str(claims), "--order", str(order),
                  "--now", NOW, "--dry-run"])
    check(rc == 0, "dry run exits 0")
    check(claims.read_bytes() == before and order.read_bytes() == order_before,
          "claims and order files are untouched by a dry run")

    print("\n2. the real run appends verbatim rows and leaves the human rows intact")
    rc = ME.main(["--runs", *globs, "--claims", str(claims), "--order", str(order),
                  "--now", NOW])
    check(rc == 0, "extraction exits 0")
    after = claims.read_bytes()
    check(after.startswith(before), "the pre-existing bytes are byte-identical")
    rows = [json.loads(x) for x in after.decode("utf-8").splitlines() if x.strip()]
    new = rows[len(human):]
    check(len(new) == 6, f"exactly 6 rows appended ({len(new)})")
    by = {(r["condition"], r["run_id"]): r for r in new}
    bat = by[("battery", "bat_cand_SYNTHb")]
    check(bat["verdict_type"] == "diff" and bat["agent_stated_confidence"] == 91,
          "battery: verdict type and confidence copied")
    check(bat["top_hypothesis_verbatim"] == HYP_BAT, "battery: hypothesis verbatim")
    check([q["quote"] for q in bat["supporting_quotes"]] == EV_BAT
          and all(q["turn"] == "verdict" for q in bat["supporting_quotes"]),
          "battery: every evidence bullet verbatim, sourced to the submitted verdict")
    check(bat["sealed_candidate_id"] == "cand_SYNTHb",
          "battery: candidate id parsed with the join's regex (not split()[1:-1])")
    check(bat["explicit_disconfirming_evidence"] is None
          and bat["harness_vs_model_attribution_notes"] is None,
          "battery: fields with no payload equivalent are null")
    check(bat["mechanical_extractor_notes"].startswith(
          ME.NOTE_PREFIX + "; source=") and "run_meta.json:verdict" in
          bat["mechanical_extractor_notes"],
          "battery: the note starts with the fixed sentence and names the source")
    check("majority of 3" in bat["mechanical_extractor_notes"]
          and "unanimous=False" in bat["mechanical_extractor_notes"],
          "battery: majority-vote provenance is stated from judge_majority")
    check(bat["extracted_by"] == ME.EXTRACTED_BY and bat["extracted_utc"] == NOW,
          "battery: extracted_by names the script, not a human")
    intro = by[("introspection", "intro_cand_SYNTHc")]
    check(intro["top_hypothesis_verbatim"] == "SYNTHETIC intro hypothesis"
          and "Baseline 3" in intro["mechanical_extractor_notes"],
          "introspection: verbatim, with its single-model caveat in the note")

    print("\n3. GLM rows: collision, missing verdict field, refusal, forced")
    g0 = by[("glm_v0", "v0_cand_SYNTHb_s0")]
    check(g0["top_hypothesis_verbatim"] == "SYNTHETIC glm ruled out"
          and len(g0["supporting_quotes"]) == 3,
          "a GLM verdict is copied whole")
    human_row = rows[0]
    check(human_row["top_hypothesis_verbatim"] == "HUMAN Opus row"
          and "condition" not in human_row,
          "the identically-named HUMAN Opus row is untouched")
    keyed = AJ.load_jsonl_last_per_run(claims, "phase1", keyed_by_condition=True)
    check(("v0_opus", "v0_cand_SYNTHb_s0") in keyed
          and ("glm_v0", "v0_cand_SYNTHb_s0") in keyed
          and keyed[("v0_opus", "v0_cand_SYNTHb_s0")]["top_hypothesis_verbatim"]
          == "HUMAN Opus row",
          "keyed by (condition, run_id) the two rows coexist and neither displaces "
          "the other")
    g1 = by[("glm_v0", "v0_cand_SYNTHb_s1")]
    check(g1["verdict_type"] is None and g1["outcome"] == "verdict_bearing"
          and "NO `verdict` field" in g1["mechanical_extractor_notes"],
          "a payload without `verdict` gives verdict_type=null and says so")
    g2 = by[("glm_v0", "v0_cand_SYNTHb_s2")]
    check(g2["outcome"] == "refusal_no_verdict" and g2["verdict_type"] is None
          and g2["top_hypothesis_verbatim"] == "" and g2["supporting_quotes"] == []
          and g2["agent_stated_confidence"] is None
          and "no verdict" in g2["mechanical_extractor_notes"],
          "a refusal is empty fields plus the note")
    g3 = by[("glm_v0", "v0_cand_SYNTHb_s3")]
    check("completed_forced" in g3["mechanical_extractor_notes"]
          and g3["verdict_type"] == "diff",
          "a forced submission is copied and flagged")
    keys = set(human[0]) | {"condition"}
    check(all(set(r) == keys for r in new),
          "every mechanical row has exactly the human schema plus `condition`")

    print("\n4. order blocks appended with the committed seeds")
    od = json.loads(order.read_text(encoding="utf-8"))
    check(len(od["blocks"]) == 3, f"two blocks appended ({len(od['blocks'])} total)")
    b2, b3 = od["blocks"][1], od["blocks"][2]
    check(b2["conditions"] == ["battery", "introspection"] and b2["n"] == 2
          and b2["seed"] == 20260904 and b2["extraction"] == "mechanical",
          "block 2 = baselines, seed 20260904")
    check(b3["conditions"] == ["glm_v0"] and b3["n"] == 4 and b3["seed"] == 20260905
          and "id_collision_disclosure" in b3,
          "block 3 = glm_v0, seed 20260905, collision disclosed")
    check(od["blocks"][0] == json.loads(order_before)["blocks"][0],
          "block 1 is untouched")

    print("\n5. a second run is refused and changes nothing")
    rc = ME.main(["--runs", *globs, "--claims", str(claims), "--order", str(order),
                  "--now", NOW])
    check(rc == 3, f"re-running refuses (rc={rc})")
    check(claims.read_bytes() == after, "the claims file is unchanged by the refusal")

    print("\n6. run_meta / transcript disagreement is refused")
    root2 = Path(tempfile.mkdtemp(prefix="mech_extract_bad_"))
    write_run(root2, "runs_glm", "v0_cand_SYNTHz_s0", status="completed",
              verdict=v_glm, transcript_verdict={**v_glm, "hypothesis": "OTHER"})
    c2 = root2 / "claims.jsonl"
    rc = ME.main(["--runs", str(root2 / "runs_glm" / "*"), "--claims", str(c2),
                  "--order", str(root2 / "order.json"), "--now", NOW])
    check(rc == 3 and not c2.exists(),
          "a verdict that differs between run_meta and run_end is refused, nothing "
          "written")

    print(f"\n{'=' * 62}")
    if _fails:
        print(f"FAILED {len(_fails)}/{_checks} checks:")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print(f"ALL {_checks} CHECKS PASS")
    print("Synthetic run dirs in a temp root; nothing under results/ was read or written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
