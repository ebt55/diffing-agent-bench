"""Every Phase-2 run view must render its evidence, not "[object Object]".

Runs against the REAL Phase-1 claims and the real map, because the bug this pins was
invisible to the synthetic fixture: the fixture stored supporting quotes as plain
strings, while phase1_grade.py actually stores each quote as a record
{"quote": ..., "turn": ...}. A client that string-coerces those prints
"[object Object]" and the grader sees no evidence at all.

It asserts three things, and prints NO claim content, NO grade and NO rung:
  * the literal "[object Object]" appears in no view;
  * every stored quote's text is present verbatim in its view;
  * every field phase1_grade.py writes is actually looked up - a key the page reads
    under the wrong name silently renders "(none recorded)" forever.

Run: python scripts/test_phase2_render.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import phase2_grade as P2  # noqa: E402

REPO = _HERE.parent
CLAIMS = REPO / "results" / "phase1_claims.jsonl"
MAP = REPO / "data" / "sealed" / "rung_id_map.json"

_checks = 0
_fails: list[str] = []


def check(cond: bool, label: str) -> None:
    global _checks
    _checks += 1
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        _fails.append(label)


class Args:
    def __init__(self, **kw):
        self.include_glm = False
        self.include_nullw = False
        self.adjudicate = False
        self.__dict__.update(kw)


def main() -> int:
    if not CLAIMS.exists() or not MAP.exists():
        print("real claims or map absent - nothing to check (not a failure)")
        return 0

    # include_glm: the mechanically extracted GLM rows share run ids with the Opus
    # rows, so this is exactly the set where a run_id-keyed view would show the wrong
    # claim. Every row must render ITS OWN claim.
    # include_nullw: Amendment 10 Arm N (nullw_opus/nullw_glm, rung L0-identical) is
    # also mechanically extracted and deserves the same rendering check as everything
    # else - and it now exists for real, so it is included rather than skipped.
    a = Args(unsealed_map=str(MAP), phase1=str(CLAIMS),
             phase2=str(REPO / "results" / "phase2_grades.jsonl"),
             descriptions=str(REPO / "results" / "rung_descriptions.json"),
             include_glm=True, include_nullw=True)
    rows, claims, grades, desc = P2.build_index(a)
    P2.Handler.A, P2.Handler.ROWS = a, rows
    P2.Handler.CLAIMS, P2.Handler.GRADES, P2.Handler.DESC = claims, grades, desc
    print(f"rendering {len(rows)} run views\n")

    print("1. no view stringifies an object")
    bad, n_quotes, missing_text = [], 0, []
    for r in rows:
        v = P2.Handler._run_view(P2.Handler, r["run_id"], r["condition"])
        blob = json.dumps(v, ensure_ascii=False)
        if "[object Object]" in blob or v.get("error"):
            bad.append(r["run_id"])
        for label, val in v["claim_fields"]:
            if isinstance(val, list):
                for item in val:
                    check_shape = isinstance(item, dict) and "text" in item
                    if not check_shape:
                        bad.append(f"{r['run_id']}:{label}")
        # every stored quote's text must survive into the view
        stored = (claims.get((r["condition"], r["run_id"]), {})
                  .get("supporting_quotes") or [])
        rendered = {i["text"] for label, val in v["claim_fields"]
                    if isinstance(val, list) for i in val if isinstance(i, dict)}
        for q in stored:
            n_quotes += 1
            text = q.get("quote", q.get("text", "")) if isinstance(q, dict) else str(q)
            if text and text not in rendered:
                missing_text.append(r["run_id"])
    check(not bad, f'"[object Object]" / unstructured entries in {len(bad)} view(s)')
    check(not missing_text,
          f"every one of {n_quotes} stored quotes appears verbatim in its view "
          f"({len(missing_text)} missing)")

    print("\n2. quote provenance is labelled, not dropped")
    labelled = 0
    for r in rows:
        v = P2.Handler._run_view(P2.Handler, r["run_id"], r["condition"])
        for label, val in v["claim_fields"]:
            if isinstance(val, list):
                labelled += sum(1 for i in val if i.get("label"))
    check(labelled >= n_quotes * 0.9,
          f"{labelled}/{n_quotes} quotes carry a turn / source-cell label")

    print("\n3. every field Phase-1 writes is actually looked up")
    written = set().union(*[set(c) for c in claims.values()]) if claims else set()
    ignorable = {"run_id", "sealed_candidate_id", "outcome", "extracted_by",
                 "extracted_utc"}
    src = Path(P2.__file__).read_text(encoding="utf-8")
    unread = sorted(k for k in written - ignorable if f'"{k}"' not in src)
    check(not unread,
          f"no Phase-1 field is looked up under a name that does not exist "
          f"(unread: {unread})")

    print("\n4. the judge payload builder reads the same fields")
    import judge_grade as JG
    jsrc = Path(JG.__file__).read_text(encoding="utf-8")
    junread = sorted(k for k in written - ignorable if f'"{k}"' not in jsrc)
    check(not junread, f"judge_grade reads every Phase-1 field (unread: {junread})")

    print(f"\n{'=' * 62}")
    if _fails:
        print(f"FAILED {len(_fails)}/{_checks} checks:")
        for f in _fails:
            print(f"  - {f}")
        return 1
    print(f"ALL {_checks} CHECKS PASS")
    print("No claim content, grade or rung was printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
