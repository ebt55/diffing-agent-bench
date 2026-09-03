#!/usr/bin/env python3
"""Proof that the coverage figure's annotations match its input JSON.

WHAT IT PROVES
  1. Every DIRECT field in the manifest resolves, by the key path it records, to
     exactly that value in the input JSON. This is the traceability claim, tested
     mechanically rather than asserted.
  2. Every DERIVED number in the manifest is recomputed here, independently of the
     figure code, from the rows the manifest names, and must match.
  3. Every numeric token in every string drawn on the figure is covered by the
     manifest (or by the registered non-measurement literals). A number on the
     figure that is not in the manifest is a failure.
  4. The dot set is exactly the verdict-bearing L2/L3 rows: none dropped, none
     invented, one annotation each, and the terminal-refusal attempts are named in
     the footnote rather than plotted.
  5. The threshold is READ, not hard-coded: on a synthetic input whose separating
     count is different, the guide moves; on one where the grades do not separate,
     no guide is drawn; on one where a side holds a single run, no guide is drawn.
  6. The renderer FAILS CLOSED on tampered input (wrong schema, missing field,
     unknown grade).

SYNTHETIC DATA IS NOT DATA
  The synthetic inputs live in results/figures/synthetic/, every name starts with
  SYNTHETIC_, each JSON carries "synthetic": true, and both renders are stamped
  across the middle. None of those numbers is a result.

    python scripts/test_make_coverage_figure.py
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import make_coverage_figure as CF  # noqa: E402

REAL_INPUT = _REPO / "results" / "analysis" / "decomposition_transcripts.json"
REAL_MANIFEST = _REPO / "results" / "figures" / "coverage_figure_annotations.json"
OUT = _REPO / "results" / "figures" / "synthetic"

_checks = 0
_fails: list[str] = []


def check(cond: bool, label: str) -> None:
    global _checks
    _checks += 1
    if cond:
        print(f"  ok   {label}")
    else:
        _fails.append(label)
        print(f"  FAIL {label}")


# ------------------------------------------------------------------ manifest audit
def audit(doc: dict, man: dict, label: str) -> None:
    """The core contract: fields resolve, derived values recompute, numbers covered."""
    rows = doc["rows"]

    n_fields = 0
    bad = []
    for it in man["annotations"]:
        for f in it["fields"]:
            n_fields += 1
            try:
                got = CF.dig(doc, f["path"])
            except (KeyError, IndexError, TypeError):
                bad.append(f"{it['kind']}: path {f['path']} does not resolve")
                continue
            if got != f["value"]:
                bad.append(f"{it['kind']}: {f['path']} is {got!r}, "
                           f"manifest says {f['value']!r}")
    check(not bad, f"{label}: all {n_fields} direct fields resolve to the input JSON")
    for b in bad[:6]:
        print(f"       -> {b}")

    # independent recomputation of every derived value
    dbad = []
    for it in man["annotations"]:
        d = it.get("derived")
        if not d:
            continue
        sub = [rows[i] for i in d["from_rows"]]
        v = d["value"]
        if it["kind"] == "panel_count":
            want = {"zero": sum(1 for r in sub if r["prompts_in_category"] == 0),
                    "n": len(sub)}
        elif it["kind"] == "threshold" and "t" in v:
            full = [r for r in sub if r["final_grade"] == "FULL"]
            t = min(r["prompts_in_category"] for r in full)
            above = [r for r in sub if r["prompts_in_category"] >= t]
            below = [r for r in sub if r["prompts_in_category"] < t]
            want = {"t": t,
                    "k_above": sum(1 for r in above if r["final_grade"] == "FULL"),
                    "n_above": len(above),
                    "k_below": sum(1 for r in below if r["final_grade"] == "FULL"),
                    "n_below": len(below),
                    "hi_other": max(r["prompts_in_category"] for r in sub
                                    if r["final_grade"] != "FULL")}
        elif it["kind"] == "threshold" and "threshold_would_be" in v:
            full = [r for r in sub if r["final_grade"] == "FULL"]
            t = min(r["prompts_in_category"] for r in full)
            want = {"threshold_would_be": t,
                    "n_above": sum(1 for r in sub
                                   if r["prompts_in_category"] >= t),
                    "n_below": sum(1 for r in sub
                                   if r["prompts_in_category"] < t)}
        elif it["kind"] == "threshold":
            want = {"n_full": sum(1 for r in sub if r["final_grade"] == "FULL")}
        elif it["kind"] == "n":
            want = {"n": len(sub),
                    "L2": sum(1 for r in sub if r["rung"] == "L2"),
                    "L3": sum(1 for r in sub if r["rung"] == "L3")}
        elif it["kind"] == "partial":
            want = {"partial": sum(1 for r in sub if r["final_grade"] == "PARTIAL"),
                    "n": len(sub)}
        elif it["kind"] == "reply_side":
            # t and hi are recomputed from the ISSUED counts, independently of the
            # manifest; only the reply-side key name is taken from it.
            key = v["key"]
            t = min(r["prompts_in_category"] for r in sub
                    if r["final_grade"] == "FULL")
            hi = max(r["prompts_in_category"] for r in sub
                     if r["final_grade"] != "FULL")
            above = [r for r in sub if r[key] >= t]
            below = [r for r in sub if r[key] <= hi]
            want = {"t": t, "key": key, "hi_other": hi,
                    "k_above": sum(1 for r in above if r["final_grade"] == "FULL"),
                    "n_above": len(above),
                    "k_below": sum(1 for r in below if r["final_grade"] == "FULL"),
                    "n_below": len(below)}
        else:
            dbad.append(f"unrecognised derived kind {it['kind']!r}")
            continue
        if want != v:
            dbad.append(f"{it['kind']}: recomputed {want}, manifest says {v}")
    n_derived = sum(1 for it in man["annotations"] if it.get("derived"))
    check(not dbad, f"{label}: all {n_derived} derived values recompute from the rows")
    for b in dbad[:6]:
        print(f"       -> {b}")

    # every number drawn is covered
    covered: set[str] = set(man["allowed_literals"])
    for it in man["annotations"]:
        for f in it["fields"]:
            covered |= CF._num_tokens(str(f["value"]))
        if it.get("derived"):
            covered |= CF._num_tokens(str(it["derived"]["value"]))
            for extra in it["derived"].get("also", []):
                covered |= CF._num_tokens(str(extra))
    seen: set[str] = set()
    for text in man["drawn_strings"]:
        seen |= CF._num_tokens(text)
    check(seen and not (seen - covered),
          f"{label}: every number drawn ({len(seen)} distinct tokens) is in the "
          f"manifest")
    if seen - covered:
        print(f"       -> uncovered: {sorted(seen - covered)}")

    # the dot set is exactly the verdict-bearing L2/L3 rows
    want_runs = {(r["rung"], r["condition"], r["run_id"]) for r in rows
                 if r["rung"] in ("L2", "L3") and r["outcome"] == "verdict_bearing"}
    got_runs = set()
    for it in man["annotations"]:
        if it["kind"] != "run":
            continue
        d = {f["path"][-1]: f["value"] for f in it["fields"]}
        got_runs.add((d["rung"], d["condition"], d["run_id"]))
    check(got_runs == want_runs,
          f"{label}: one dot per verdict-bearing L2/L3 run ({len(want_runs)}), "
          f"none dropped or invented")
    n_run_ann = sum(1 for it in man["annotations"] if it["kind"] == "run")
    check(n_run_ann == len(want_runs), f"{label}: no duplicate dot annotations")

    # run_id alone is NOT unique - the same id occurs under several conditions -
    # so the refusal attempts are matched on the full (rung, condition, run_id).
    ref_want = {(a["rung"], a.get("condition"), a["run_id"])
                for a in doc.get("meta", {}).get("refusal_attempts", [])
                if a.get("rung") in ("L2", "L3")}
    ref_got = set()
    for it in man["annotations"]:
        if it["kind"] != "refusal":
            continue
        d = {f["path"][-1]: f["value"] for f in it["fields"]}
        ref_got.add((d["rung"], d["condition"], d["run_id"]))
    check(ref_got == ref_want,
          f"{label}: terminal-refusal attempts named, not plotted "
          f"({len(ref_want)})")
    check(not (ref_got & got_runs),
          f"{label}: no terminal-refusal run was drawn as a dot")
    dupes = {k for k in {r for _, _, r in got_runs}
             if sum(1 for _, _, r in got_runs if r == k) > 1}
    check(len({(c, r) for _, c, r in got_runs}) == len(got_runs),
          f"{label}: (condition, run_id) is unique across the dots "
          f"({len(dupes)} run_ids recur under several conditions)")


def render_to(doc: dict, stem: str) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    src = OUT / f"{stem}_input.json"
    src.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    p = subprocess.run(
        [sys.executable, str(_HERE / "make_coverage_figure.py"),
         "--input", str(src), "--outdir", str(OUT), "--stem", stem],
        capture_output=True, text=True, encoding="utf-8", cwd=str(_REPO))
    if p.returncode != 0:
        raise RuntimeError((p.stdout or "") + (p.stderr or ""))
    return json.loads((OUT / f"{stem}_annotations.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ synthetic input
def syn_row(rung: str, cond: str, run: str, x: int, grade: str) -> dict:
    return {"rung": rung, "condition": cond, "run_id": run,
            "prompts_in_category": x, "final_grade": grade,
            "outcome": "verdict_bearing", "prompts_issued_candidate_side": 50,
            "single_model_run": False}


def syn_doc(l3_counts: list[tuple[int, str]]) -> dict:
    """Synthetic doc: L2 fixed, L3's counts/grades supplied by the caller."""
    rows = [syn_row("L2", "v0_opus", f"SYN_l2_{k}", 0, "MISS") for k in range(3)]
    rows += [syn_row("L2", "battery", "SYN_l2_bat", 0, "MISS")]
    for k, (x, g) in enumerate(l3_counts):
        rows.append(syn_row("L3", ["v0_opus", "v1_opus", "glm_v0"][k % 3],
                            f"SYN_l3_{k}", x, g))
    return {
        "schema": CF.INPUT_SCHEMA,
        "synthetic": True,
        "WARNING": "SYNTHETIC - arbitrary integers, not a result",
        "predicates": "SYNTHETIC/not-a-real-predicate-file",
        "meta": {"refusal_attempts": [
            {"rung": "L3", "run_id": "SYN_refusal", "condition": "v0_opus",
             "prompts_in_category": 0}]},
        "rows": rows,
    }


def main() -> int:
    print(__doc__.splitlines()[0])

    # ------------------------------------------------- 1-4 the real committed figure
    print("\nreal input -> real manifest (the committed figure)")
    doc = CF.load_input(REAL_INPUT)
    man = json.loads(REAL_MANIFEST.read_text(encoding="utf-8"))
    check(man["schema"] == CF.SCHEMA, "manifest carries the expected schema")
    check(man["input_schema"] == doc["schema"], "manifest records the input schema")
    check(man["input_is_synthetic"] is False, "the real render is not watermarked")
    audit(doc, man, "real")

    # the L3 guide must be what the rows say, not a constant in the code
    l3 = CF.panel_rows(doc, "L3")
    sep = CF.separation(l3)
    check(sep is not None and sep["drawn"], "L3 separates and gets a guide")
    t = sep["threshold"]
    above = [r for _, r in l3 if r["prompts_in_category"] >= t]
    below = [r for _, r in l3 if r["prompts_in_category"] < t]
    check(all(r["final_grade"] == "FULL" for r in above)
          and not any(r["final_grade"] == "FULL" for r in below),
          f"L3 guide at x={t}: FULL {len(above)}/{len(above)} above, "
          f"0/{len(below)} below")
    l2 = CF.panel_rows(doc, "L2")
    sep2 = CF.separation(l2)
    check(sep2 is not None and not sep2["drawn"],
          "L2 gets NO guide: the separation would rest on a single run")

    # the axis (prompts ISSUED) and the reply-side count give different
    # denominators for the same runs; the figure must state both, not pick one
    rs = [it for it in man["annotations"] if it["kind"] == "reply_side"]
    check(len(rs) == 1, "the issued-vs-reply-side reconciliation is stated once")
    if rs:
        v = rs[0]["derived"]["value"]
        key = v["key"]
        n_below_issued = len(below)
        n_below_reply = sum(1 for _, r in l3 if r[key] <= sep["hi_other"])
        check(n_below_reply != n_below_issued,
              f"the two denominators really do differ "
              f"({n_below_issued} issued vs {n_below_reply} reply-side), which is "
              f"why the figure states both")
        check(v["k_below"] == 0 and v["k_above"] == len(above),
              "the reply-side split agrees with the issued-prompt split on grades")

    # ---------------------------------------------------- 5 the threshold is read
    print("\nthreshold is read from the rows, not hard-coded")
    moved = syn_doc([(0, "MISS"), (1, "MISS"), (2, "MISS"), (2, "MISS"),
                     (9, "FULL"), (11, "FULL")])
    m_moved = render_to(moved, "SYNTHETIC_coverage_moved")
    th = [it for it in m_moved["annotations"]
          if it["kind"] == "threshold" and it["panel"] == "L3"]
    check(len(th) == 1 and th[0]["derived"]["value"]["t"] == 9,
          "a different separating count moves the guide to x=9")
    check(th[0]["derived"]["value"]["n_above"] == 2
          and th[0]["derived"]["value"]["n_below"] == 4,
          "the guide's k/n follow the synthetic rows")
    audit(moved, m_moved, "synthetic-moved")

    mixed = syn_doc([(0, "MISS"), (5, "FULL"), (5, "MISS"), (7, "FULL"),
                     (2, "MISS"), (9, "MISS")])
    m_mixed = render_to(mixed, "SYNTHETIC_coverage_nosep")
    th = [it for it in m_mixed["annotations"]
          if it["kind"] == "threshold" and it["panel"] == "L3"][0]
    check("n_full" in th["derived"]["value"],
          "grades that do not separate get no guide")
    audit(mixed, m_mixed, "synthetic-nosep")

    lone = syn_doc([(0, "MISS"), (0, "MISS"), (1, "MISS"), (1, "MISS"),
                    (2, "MISS"), (8, "FULL")])
    m_lone = render_to(lone, "SYNTHETIC_coverage_lone")
    th = [it for it in m_lone["annotations"]
          if it["kind"] == "threshold" and it["panel"] == "L3"][0]
    check(th["derived"]["value"] == {"threshold_would_be": 8, "n_above": 1,
                                     "n_below": 5},
          "a separation resting on one run is reported but NOT drawn")
    check(m_lone["input_is_synthetic"] is True
          and m_lone["watermark"].startswith("SYNTHETIC"),
          "a synthetic render is watermarked, never mistakable for data")
    audit(lone, m_lone, "synthetic-lone")

    # -------------------------------------------------------------- 6 fail closed
    print("\nfails closed on tampered input")
    for label, mutate in (
        ("wrong schema", lambda d: d.update({"schema": "not/the/schema"})),
        ("missing prompts_in_category",
         lambda d: d["rows"][0].pop("prompts_in_category")),
        ("unknown grade",
         lambda d: d["rows"][0].update({"final_grade": "SPLENDID"})),
        ("no rows", lambda d: d.update({"rows": []})),
    ):
        bad = copy.deepcopy(syn_doc([(0, "MISS"), (6, "FULL")]))
        mutate(bad)
        # transient: a rejected input is not an artefact, so it goes to a temp dir
        p = Path(tempfile.mkdtemp(prefix="cov_bad_")) / "SYNTHETIC_bad_input.json"
        p.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        try:
            CF.load_input(p)
            check(False, f"rejects {label}")
        except ValueError:
            check(True, f"rejects {label}")

    print(f"\n{_checks - len(_fails)}/{_checks} checks pass")
    if _fails:
        for f in _fails:
            print(f"  FAILED: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
