"""Synthetic tests for scripts/phase2_grade.py and scripts/judge_grade.py.

Everything here runs against a FAKE rung map and FAKE claims written to a temp
directory. The real sealed path is never touched, never opened, and never named as an
input. No API call is made: the judge is exercised through --dry-run and through a
stubbed transport, so the cost of running this test is zero.

Run: python scripts/test_phase2_grading.py
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import judge_grade as JG      # noqa: E402
import phase2_grade as P2     # noqa: E402

_checks = 0
_fails: list[str] = []


def check(cond: bool, label: str) -> None:
    global _checks
    _checks += 1
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        _fails.append(label)


FAKE_MAP = {"_WARNING": "SYNTHETIC FAKE MAP - NOT THE SEALED MAP",
            "map": {"L0": "cand_FAKEa", "L1": "cand_FAKEb", "L2": "cand_FAKEc",
                    "L3": "cand_FAKEd", "L4v3": "cand_FAKEe"}}


def fake_claims() -> list[dict]:
    def row(rid, cand, outcome, hyp, cond="v0_opus", quotes=None):
        return {"run_id": rid, "sealed_candidate_id": cand, "outcome": outcome,
                "condition": cond,
                "verdict_type": (None if outcome == "refusal_no_verdict" else "diff"),
                "top_hypothesis_verbatim": hyp,
                "supporting_quotes": quotes or ["SYNTHETIC quote - not data"],
                "agent_confidence": 80}
    return [
        row("v0_cand_FAKEa_s0", "cand_FAKEa", "verdict_bearing", "SYNTHETIC L0 claim"),
        row("v0_cand_FAKEa_s1", "cand_FAKEa", "refusal_no_verdict", ""),
        row("v0_cand_FAKEb_s0", "cand_FAKEb", "verdict_bearing", "SYNTHETIC L1 claim"),
        row("v0_cand_FAKEc_s0", "cand_FAKEc", "verdict_bearing", "SYNTHETIC L2 claim"),
        row("v0_cand_FAKEe_s0", "cand_FAKEe", "verdict_bearing", "SYNTHETIC L4v3 claim"),
        row("v0_cand_FAKEb_s9", "cand_FAKEb", "verdict_bearing", "SYNTHETIC GLM claim",
            cond="glm_v0"),
        # The real collision: a GLM-arm claim whose run_id is byte-identical to an
        # Opus-arm claim's. Both must survive and each view must show its own.
        row("v0_cand_FAKEb_s0", "cand_FAKEb", "verdict_bearing",
            "SYNTHETIC GLM claim on a COLLIDING id", cond="glm_v0"),
    ]


class Args:
    def __init__(self, **kw):
        self.include_glm = False
        self.adjudicate = False
        self.__dict__.update(kw)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="phase2_test_"))
    mp = tmp / "FAKE_rung_map.json"
    mp.write_text(json.dumps(FAKE_MAP), encoding="utf-8")
    p1 = tmp / "FAKE_phase1_claims.jsonl"
    p1.write_text("\n".join(json.dumps(r) for r in fake_claims()) + "\n",
                  encoding="utf-8")
    p2 = tmp / "phase2_grades.jsonl"
    desc = str(Path(__file__).resolve().parents[1] / "results" / "rung_descriptions.json")

    print(f"fixture in {tmp}\n")
    print("1. the fixture is fake and the real sealed path is untouched")
    check("FAKE" in mp.read_text(encoding="utf-8"), "map fixture is labelled FAKE")
    check("data/sealed" not in mp.read_text(encoding="utf-8"),
          "map fixture does not reference the sealed path")

    print("\n2. phase2_grade indexing, ordering and GLM exclusion")
    a = Args(unsealed_map=str(mp), phase1=str(p1), phase2=str(p2), descriptions=desc)
    rows, claims, grades, d = P2.build_index(a)
    ids = [r["run_id"] for r in rows]
    check("v0_cand_FAKEb_s9" not in ids, "GLM-condition run excluded by default")
    a_glm = Args(unsealed_map=str(mp), phase1=str(p1), phase2=str(p2),
                 descriptions=desc, include_glm=True)
    rows_g, _, _, _ = P2.build_index(a_glm)
    check("v0_cand_FAKEb_s9" in [r["run_id"] for r in rows_g],
          "--include-glm brings it back")
    check(rows[-1]["rung"] == "L4v3",
          f"exploratory L4v3 is graded LAST (Amendment 4 item 4), got {rows[-1]['rung']}")
    check([r["rung"] for r in rows].count("L4v3") == 1, "exactly one L4v3 row")
    check(ids.count("v0_cand_FAKEb_s0") == 1,
          "without --include-glm the colliding GLM claim does not appear")

    print("\n2b. run ids shared across conditions resolve by condition, never by luck")
    both = [r for r in rows_g if r["run_id"] == "v0_cand_FAKEb_s0"]
    check(len(both) == 2 and {r["condition"] for r in both} == {"v0_opus", "glm_v0"},
          "with --include-glm BOTH rows for the shared id exist, one per condition")
    check(rows_g[-1]["condition"] == "glm_v0"
          and [r["condition"] for r in rows_g].index("glm_v0")
          > max(i for i, r in enumerate(rows_g) if r["condition"] == "v0_opus"),
          "the GLM arm is ordered after every Opus row")
    P2.Handler.A, P2.Handler.ROWS = a_glm, rows_g
    P2.Handler.CLAIMS, P2.Handler.GRADES, P2.Handler.DESC = claims, grades, d
    v_opus = P2.Handler._run_view(P2.Handler, "v0_cand_FAKEb_s0", "v0_opus")
    v_glm = P2.Handler._run_view(P2.Handler, "v0_cand_FAKEb_s0", "glm_v0")
    hyp = lambda v: next(val for lab, val in v["claim_fields"]  # noqa: E731
                         if lab.startswith("Top hypothesis"))
    check(hyp(v_opus) == "SYNTHETIC L1 claim" and "COLLIDING" in hyp(v_glm),
          "each condition's view shows ITS OWN claim text")
    v_amb = P2.Handler._run_view(P2.Handler, "v0_cand_FAKEb_s0")
    check(bool(v_amb.get("error")) and "2 conditions" in v_amb["error"],
          "a bare shared id is refused as ambiguous, not resolved to the first match")
    check(all("key" in r and r["key"] == f"{r['condition']}:{r['run_id']}"
              for r in rows_g), "every row carries a condition-qualified key")

    print("\n3. label sets are rung-appropriate")
    P2.Handler.A, P2.Handler.ROWS = a, rows
    P2.Handler.CLAIMS, P2.Handler.GRADES, P2.Handler.DESC = claims, grades, d
    v_l0 = P2.Handler._run_view(P2.Handler, "v0_cand_FAKEa_s0")
    v_l1 = P2.Handler._run_view(P2.Handler, "v0_cand_FAKEb_s0")
    v_l2 = P2.Handler._run_view(P2.Handler, "v0_cand_FAKEc_s0")
    v_ref = P2.Handler._run_view(P2.Handler, "v0_cand_FAKEa_s1")
    check(set(v_l0["allowed_grades"]) == set(P2.L0_GRADES),
          "L0 offers FP/CR/REFUSAL only — never FULL/PARTIAL/MISS")
    check("FULL" in v_l1["allowed_grades"] and "FP" not in v_l1["allowed_grades"],
          "non-L0 offers FULL/PARTIAL/MISS and never FP")
    check(v_l2["is_l2"] is True and v_l1["is_l2"] is False,
          "the L2 side-channel tick appears for L2 only")
    check(v_l2["side_channel"] and "+400" in v_l2["side_channel"],
          "L2 view carries the disclosed length side-channel")

    print("\n3b. the judge's label is withheld until --adjudicate")
    # A row that already carries a judge grade, as it will after the judge pass.
    _k = ("v0_opus", "v0_cand_FAKEb_s0")   # rows are keyed (condition, run_id)
    P2.Handler.GRADES[_k] = {
        "run_id": "v0_cand_FAKEb_s0", "condition": "v0_opus", "judge_grade": "FULL",
        "judge_reason": "SYNTHETIC judge reason"}
    v_norm = P2.Handler._run_view(P2.Handler, "v0_cand_FAKEb_s0")
    check(v_norm["judge_grade"] is None and v_norm["judge_reason"] is None,
          "in normal grading the judge fields are absent from the PAYLOAD, not just "
          "hidden in the markup")
    P2.Handler.A = a_adj = Args(unsealed_map=str(mp), phase1=str(p1), phase2=str(p2),
                                descriptions=desc, adjudicate=True)
    v_adj = P2.Handler._run_view(P2.Handler, "v0_cand_FAKEb_s0")
    check(v_adj["judge_grade"] == "FULL",
          "in --adjudicate the judge grade is supplied, which is the point")
    P2.Handler.A = a
    P2.Handler.GRADES.pop(_k, None)

    print("\n4. refusals are derived and locked, not chosen")
    check(v_ref["locked"] is True, "a refused run is locked")
    check(v_ref["human_grade"] == "REFUSAL_NO_VERDICT",
          "its grade is pre-filled from status")

    print("\n5. the checklist and planted text come from the committed file")
    check(len(v_l0["checklist"]) == 7, "all seven Addendum-A items are shown")
    check("FALSE POSITIVE" in v_l0["checklist"][0], "item 1 is the FP rule")
    check("hedging persona" in v_l1["planted"], "L1 planted text is the prereg wording")

    print("\n6. no transcript is ever read")
    src = Path(P2.__file__).read_text(encoding="utf-8")
    check("transcript.jsonl" not in src,
          "phase2_grade.py contains no reference to transcript.jsonl")
    check("data/sealed" not in src.replace("data/sealed/rung_id_map.json", ""),
          "phase2_grade.py hardcodes no sealed path")

    print("\n7. saving is append-only and validated")
    def save(payload):
        class R:
            def __init__(s, b): s._b = b
            def read(s, n): return s._b
        h = P2.Handler.__new__(P2.Handler)
        h.path = "/api/save"
        h.headers = {"Content-Length": str(len(json.dumps(payload).encode()))}
        h.rfile = R(json.dumps(payload).encode())
        out = {}
        h._json = lambda obj, code=200: out.update({"obj": obj, "code": code})
        P2.Handler.do_POST(h)
        return out
    r = save({"run_id": "v0_cand_FAKEb_s0", "human_grade": "FULL", "human_reason": ""})
    check(r["obj"]["ok"] is False, "a save with no written reason is refused")
    r = save({"run_id": "v0_cand_FAKEb_s0", "human_grade": "FP",
              "human_reason": "x"})
    check(r["obj"]["ok"] is False, "FP is refused on a non-L0 rung")
    r = save({"run_id": "v0_cand_FAKEb_s0", "human_grade": "FULL",
              "human_reason": "SYNTHETIC reason",
              "decomposition_reasons": {"coverage": "SYN cov", "exposure": "SYN exp",
                                        "attribution": "SYN attr"},
              "decomposition": {"coverage": True, "exposure": True,
                                "attribution": "FULL"}})
    check(r["obj"]["ok"] is True, "a complete grade saves")
    r2 = save({"run_id": "v0_cand_FAKEb_s0", "human_grade": "PARTIAL",
               "human_reason": "SYNTHETIC regrade"})
    rows_out = [json.loads(x) for x in p2.read_text(encoding="utf-8").splitlines() if x.strip()]
    check(len(rows_out) == 2, "re-grading APPENDS a second row, never rewrites")
    check(rows_out[-1]["human_grade"] == "PARTIAL", "last row wins on reload")

    print("\n7b. a LOCKED refusal row needs no written reason")
    r = save({"run_id": "v0_cand_FAKEa_s1", "human_grade": None, "human_reason": ""})
    check(r["obj"]["ok"] is True,
          "a locked refusal saves with an empty reason (no keystroke tax)")
    saved = [json.loads(x) for x in p2.read_text(encoding="utf-8").splitlines()
             if x.strip()][-1]
    check(saved["human_grade"] == "REFUSAL_NO_VERDICT",
          "its grade is still derived from status, not from the request")
    check(saved["human_reason"] ==
          "terminal refusal (locked; Amendment 6 clarification 1)",
          f"and a standard reason is filled in ({saved['human_reason']!r})")
    r = save({"run_id": "v0_cand_FAKEc_s0", "human_grade": "PARTIAL",
              "human_reason": "   "})
    check(r["obj"]["ok"] is False,
          "an UNLOCKED row still requires a real written reason")

    print("\n7d. a save on a shared run id lands on the condition it names")
    P2.Handler.ROWS = rows_g
    r = save({"run_id": "v0_cand_FAKEb_s0", "human_grade": "MISS",
              "human_reason": "SYNTHETIC glm reason"})
    check(r["obj"]["ok"] is False and "2 conditions" in r["obj"]["error"],
          "a save with a bare shared id is refused, not written to the first match")
    r = save({"run_id": "v0_cand_FAKEb_s0", "condition": "glm_v0",
              "human_grade": "MISS", "human_reason": "SYNTHETIC glm reason"})
    check(r["obj"]["ok"] is True, "the same save with condition=glm_v0 is accepted")
    last = [json.loads(x) for x in p2.read_text(encoding="utf-8").splitlines()
            if x.strip()][-1]
    check(last["condition"] == "glm_v0" and last["run_id"] == "v0_cand_FAKEb_s0",
          "the written row is keyed to glm_v0")
    check(P2.Handler.GRADES[("v0_opus", "v0_cand_FAKEb_s0")]["human_grade"]
          == "PARTIAL", "the Opus row of the same name still holds its own grade")
    P2.Handler.ROWS = rows

    print("\n7e. adjudicate mode FREEZES the human fields (DECISIONS.md #35 ruling A)")
    k_adj = ("v0_opus", "v0_cand_FAKEb_s0")
    on_file = dict(P2.Handler.GRADES[k_adj])        # human PARTIAL from 7's re-grade
    P2.Handler.GRADES[k_adj] = {**on_file, "judge_grade": "FULL",
                                "judge_reason": "SYNTHETIC judge reason"}
    P2.Handler.A = a_adj
    r = save({"run_id": "v0_cand_FAKEb_s0", "condition": "v0_opus",
              # everything a rogue client (or the old page) could send for the human
              # fields - all of it must be ignored
              "human_grade": "MISS", "human_reason": "ATTEMPTED REWRITE",
              "decomposition": {"coverage": False, "exposure": False,
                                "attribution": "MISS"},
              "decomposition_reasons": {"coverage": "x", "exposure": "x",
                                        "attribution": "x"},
              "l2_length_side_channel_cited": True,
              "adjudicated_grade": "FULL",
              "adjudication_reason": "SYNTHETIC adjudication"})
    check(r["obj"]["ok"] is True, "an adjudicate save with a grade and a reason is accepted")
    adj_row = [json.loads(x) for x in p2.read_text(encoding="utf-8").splitlines()
               if x.strip()][-1]
    check(adj_row["human_grade"] == "PARTIAL",
          f"human_grade is copied from the row on file, NOT from the payload "
          f"({adj_row['human_grade']})")
    check(adj_row["human_reason"] == on_file["human_reason"],
          "human_reason is copied from the row on file")
    check(adj_row["decomposition"] == on_file.get("decomposition")
          and adj_row["decomposition_reasons"] == on_file.get("decomposition_reasons")
          and adj_row["l2_length_side_channel_cited"]
          == on_file.get("l2_length_side_channel_cited"),
          "decomposition, stage reasons and the L2 tick are copied, never taken from "
          "the payload")
    check(adj_row["adjudicated_grade"] == "FULL"
          and adj_row["adjudication_reason"] == "SYNTHETIC adjudication",
          "the adjudicated grade and its reason are recorded")
    check(adj_row["judge_grade"] == "FULL", "the judge fields are carried forward")
    r = save({"run_id": "v0_cand_FAKEb_s0", "condition": "v0_opus",
              "human_grade": "MISS", "human_reason": "x",
              "adjudicated_grade": None, "adjudication_reason": "x"})
    check(r["obj"]["ok"] is False,
          "an adjudicate save WITHOUT an adjudicated grade is refused (no no-op rows)")
    r = save({"run_id": "v0_cand_FAKEb_s0", "condition": "v0_opus",
              "adjudicated_grade": "FULL", "adjudication_reason": "   "})
    check(r["obj"]["ok"] is False, "an adjudicated grade without a reason is refused")
    r = save({"run_id": "v0_cand_FAKEb_s0", "condition": "v0_opus",
              "adjudicated_grade": "FP", "adjudication_reason": "x"})
    check(r["obj"]["ok"] is False, "an adjudicated grade invalid for the rung is refused")
    r = save({"run_id": "v0_cand_FAKEc_s0", "condition": "v0_opus",
              "adjudicated_grade": "MISS", "adjudication_reason": "x"})
    check(r["obj"]["ok"] is False and "no human grade on file" in r["obj"]["error"],
          "a run with no human grade on file cannot be adjudicated")
    n_before = len([x for x in p2.read_text(encoding="utf-8").splitlines() if x.strip()])
    check(n_before == len(rows_out) + 3,
          f"refused adjudicate saves append nothing ({n_before} rows on file)")

    print("\n7f. a NORMAL-mode save on an adjudicated run is refused (#35 addendum)")
    P2.Handler.A = a                                    # back to normal mode; the row on
    r = save({"run_id": "v0_cand_FAKEb_s0", "condition": "v0_opus",   # file is adjudicated
              "human_grade": "FULL",
              "human_reason": "SYNTHETIC re-grade after adjudication"})
    check(r["obj"]["ok"] is False and r["obj"]["error"]
          == "this run is adjudicated; re-adjudicate instead of re-grading",
          f"refused with the ruling's message ({r['obj'].get('error')!r})")
    n_after = len([x for x in p2.read_text(encoding="utf-8").splitlines() if x.strip()])
    check(n_after == n_before,
          "and nothing is appended - last-row-wins cannot discard the adjudication")
    check(P2.Handler.GRADES[k_adj]["adjudicated_grade"] == "FULL",
          "the adjudicated row is still the one on file")
    P2.Handler.GRADES[k_adj] = on_file

    print("\n7c. --status surfaces missing decomposition before the join does")
    import io as _io
    import contextlib as _ctx
    # a non-null row graded with no decomposition at all
    with p2.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"run_id": "v0_cand_FAKEb_s0", "condition": "v0_opus",
                             "rung": "L1", "human_grade": "FULL",
                             "human_reason": "SYNTHETIC"}) + "\n")
    a_st = Args(unsealed_map=str(mp), phase1=str(p1), phase2=str(p2),
                descriptions=desc, status=True, port=0, no_browser=True)
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        P2.main(["--unsealed-map", str(mp), "--phase1", str(p1), "--phase2", str(p2),
                 "--descriptions", desc, "--status"])
    out = buf.getvalue()
    line = [l for l in out.splitlines()
            if l.startswith("non-null rows missing decomposition:")]
    check(bool(line), "--status prints the missing-decomposition line")
    check(line and "v0_cand_FAKEb_s0" in line[0],
          f"and names the offending run id ({line[0] if line else ''})")
    check(line and not line[0].endswith(": 0 (run ids: none)"),
          "the count is non-zero when a row is incomplete")

    print("\n8. rows conform to the committed schema")
    schema = json.loads((Path(desc).parent / "phase2_grades.schema.json")
                        .read_text(encoding="utf-8"))
    allowed_keys = set(schema["properties"])
    for row in rows_out:
        extra = set(row) - allowed_keys
        check(not extra, f"row {row['run_id']} adds no key outside the schema {extra or ''}")
    check("decomposition" in rows_out[0] and
          set(rows_out[0]["decomposition"] or {}) <= {"coverage", "exposure", "attribution"},
          "decomposition carries only the three schema-permitted fields")
    every_row = [json.loads(x) for x in p2.read_text(encoding="utf-8").splitlines()
                 if x.strip()]
    check(all(set(row) <= allowed_keys for row in every_row),
          f"every row written during this test (incl. the adjudication row) stays "
          f"inside the schema ({len(every_row)} rows)")
    check(schema["$id"] == "phase2_grades/2", "schema version was bumped to /2")
    check(set(schema["required"]) == {"run_id", "human_grade"},
          "the amendment added no required field")
    dr = rows_out[0].get("decomposition_reasons") or {}
    check(set(dr) == {"coverage", "exposure", "attribution"} and dr["exposure"] == "SYN exp",
          "per-stage reasons are first-class in decomposition_reasons")
    check(P2.DECOMP_MARKER.strip() not in rows_out[0]["human_reason"],
          "human_reason is no longer used to smuggle the stage reasons")
    check(rows_out[-1].get("decomposition_reasons") is None,
          "a grade with no stage reasons writes null, not an empty object")

    print("\n9. judge_grade is blind, one-per-call, and priced")
    jsrc = Path(JG.__file__).read_text(encoding="utf-8")
    check("human_grade" in jsrc and "prev.get(\"human_grade\")" in jsrc,
          "judge carries the human column forward but never reads it as input")
    payload_uses_human = "human_grade" in JG.claim_payload(
        {"top_hypothesis_verbatim": "x", "outcome": "verdict_bearing"}, "L1",
        json.loads(Path(desc).read_text(encoding="utf-8")))
    check(not payload_uses_human, "the judge payload contains no human grade")
    check(set(JG.GRADE_SCHEMA["properties"]["grade"]["enum"]) == set(JG.GRADES),
          "the judge's forced label set matches the schema's")
    check(JG.GRADE_SCHEMA["additionalProperties"] is False,
          "the judge schema is strict")

    print("\n10. judge dry-run estimates cost and calls nothing")
    calls = []
    def boom(*args, **kw):
        calls.append(1)
        raise AssertionError("a dry run must not open a socket")
    orig = urllib.request.urlopen
    urllib.request.urlopen = boom
    try:
        rc = JG.main(["--unsealed-map", str(mp), "--phase1", str(p1),
                      "--phase2", str(tmp / "j.jsonl"), "--descriptions", desc,
                      "--dry-run"])
    finally:
        urllib.request.urlopen = orig
    check(rc == 0, "judge --dry-run exits 0")
    check(not calls, "judge --dry-run made no network call")

    print("\n11. judge refuses to exceed its cost ceiling")
    urllib.request.urlopen = boom
    try:
        rc = JG.main(["--unsealed-map", str(mp), "--phase1", str(p1),
                      "--phase2", str(tmp / "j2.jsonl"), "--descriptions", desc,
                      "--max-usd", "0.0000001"])
    finally:
        urllib.request.urlopen = orig
    check(rc == 5, "an over-ceiling estimate stops with rc=5 before calling")
    check(not calls, "and still made no network call")

    print("\n12. a refusal is derived by the judge, not sent to the model")
    rows_j, _, _, dd = P2.build_index(a)
    payload = JG.claim_payload(
        {"outcome": "refusal_no_verdict"}, "L1",
        json.loads(Path(desc).read_text(encoding="utf-8")))
    check("(none recorded)" in payload,
          "an empty claim renders as explicitly-missing, not as a negative claim")

    print(f"\n{'=' * 62}")
    if _fails:
        print(f"FAILED {len(_fails)}/{_checks} checks:")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print(f"ALL {_checks} CHECKS PASS")
    print("Synthetic only: a fake map and fake claims in a temp dir.")
    print("No sealed file was read and no API call was made.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
