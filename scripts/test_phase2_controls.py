"""The three decomposition controls must be independent, and must reach the payload.

This runs the REAL page JavaScript under node with a small DOM shim, rather than a
Python re-implementation of it: the bug it pins lived in the emitted HTML of one
template literal, so a mirror of that logic would have been free to be correct while
the shipped page stayed broken.

What it asserts:
  * each of coverage / exposure / attribution sets ONLY its own field;
  * none of them touches the Grade row, and the Grade row does not touch them;
  * an attribution button emits a handler the browser can actually parse - the
    original emitted onclick="setDec('attribution',"FULL")", which the parser
    truncated at the injected quote, so clicking did nothing;
  * the POST body the page would send carries decomposition.{coverage,exposure,
    attribution} and decomposition_reasons.* per schema v2.

Nothing is posted anywhere; fetch is stubbed and the body is captured.

Run: python scripts/test_phase2_controls.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from phase2_ui import PAGE  # noqa: E402

HARNESS = r"""
// ---- minimal DOM shim -------------------------------------------------------
const FIELDS = {};
function mkEl(id){ return { id, value:"", textContent:"", dataset:{} }; }
const els = {};
global.document = {
  _listeners: [],
  addEventListener(type, fn){ this._listeners.push([type, fn]); },
  getElementById(id){ return (els[id] = els[id] || mkEl(id)); },
};
global.alert = m => { ALERTS.push(m); };
const ALERTS = [];
let POSTED = null;
global.fetch = async (url, opts) => {
  POSTED = JSON.parse(opts.body);
  return { ok:true, json: async () => ({ ok:true, row:{} }) };
};
global.window = global;

__PAGE_JS__

// ---- drive it ---------------------------------------------------------------
function click(html){
  // parse the emitted button and dispatch through the delegated listener,
  // exactly as a browser click would
  const df = /data-df="([^"]*)"/.exec(html);
  const dv = /data-dv="([^"]*)"/.exec(html);
  const dt = /data-dt="([^"]*)"/.exec(html);
  if(!df) return {dispatched:false};
  const btn = { dataset:{ df:df[1], dv:dv[1], dt:dt[1] }, closest(){ return btn; } };
  const ev = { target: btn };
  for(const [t, fn] of document._listeners){ if(t === 'click') fn(ev); }
  return {dispatched:true};
}

const out = { steps:[] };

cur = {
  run_id:"SYNTH_run", rung:"L1", condition:"v0_opus", locked:false,
  allowed_grades:["FULL","PARTIAL","MISS","REFUSAL_NO_VERDICT"],
  human_grade:null, human_reason:"", is_l2:false, l2:null,
  decomposition:{coverage:null, exposure:null, attribution:null},
  decomposition_reasons:{coverage:null, exposure:null, attribution:null},
  claim_fields:[], checklist:[], planted:"", decomp_help:"",
  adjudicated_grade:null, adjudication_reason:null,
};
RUNS = [{run_id:"SYNTH_run", done:false}]; i = 0; ADJ = false;

// 1. every emitted handler must be parseable: no raw quote inside the attribute
const emitted = {
  coverage:   triBtn('coverage',   true,    'yes'),
  exposure:   triBtn('exposure',   false,   'no'),
  attribution:triBtn('attribution','FULL',  'FULL'),
};
out.emitted = emitted;
out.inline_onclick_present = Object.values(emitted).some(h => /onclick=/.test(h));
out.broken_attribute = Object.entries(emitted)
  .filter(([k,h]) => { const m = /onclick="([^"]*)"/.exec(h);
                       return m && !/\)\s*$/.test(m[1]); })
  .map(([k]) => k);

// 2. set each control in turn; each must move ONLY its own field
click(triBtn('coverage', true, 'yes'));
out.steps.push({after:'coverage', dec:{...cur.decomposition}, grade:cur.human_grade});
click(triBtn('exposure', false, 'no'));
out.steps.push({after:'exposure', dec:{...cur.decomposition}, grade:cur.human_grade});
click(triBtn('attribution', 'PARTIAL', 'PARTIAL'));
out.steps.push({after:'attribution', dec:{...cur.decomposition}, grade:cur.human_grade});

// 3. the Grade row must not disturb them, and vice versa
pick('MISS');
out.after_pick = { dec:{...cur.decomposition}, grade:cur.human_grade };

// 4. re-clicking attribution must change only attribution
click(triBtn('attribution', 'FULL', 'FULL'));
out.after_reclick = { dec:{...cur.decomposition}, grade:cur.human_grade };

// 5. build the POST body the page would send (captured, never sent)
document.getElementById('reason').value = "SYNTHETIC reason";
document.getElementById('dr_coverage').value = "SYN cov";
document.getElementById('dr_exposure').value = "SYN exp";
document.getElementById('dr_attribution').value = "SYN attr";
save().then(() => {
  out.posted = POSTED;
  out.alerts = ALERTS.slice();
  // 6. adjudicate mode: the human fields are frozen and never leave the page
  //    (DECISIONS.md #35 ruling A)
  ADJ = true; POSTED = null;
  const before = { grade: cur.human_grade, dec: {...cur.decomposition} };
  pick('FULL');                                  // must be a no-op
  click(triBtn('coverage', false, 'no'));        // must be a no-op
  setL2(true);                                   // must be a no-op
  out.adj_after_clicks = { grade: cur.human_grade, dec: {...cur.decomposition},
                           l2: cur.l2, before };
  out.adj_grade_buttons_disabled = /disabled/.test(gradeBtns());
  cur.adjudicated_grade = 'PARTIAL';
  document.getElementById('adjreason').value = "SYN adjudication";
  return save().then(() => {
    out.adj_posted = POSTED;
    console.log(JSON.stringify(out));
  });
});
"""

_checks = 0
_fails: list[str] = []


def check(cond: bool, label: str) -> None:
    global _checks
    _checks += 1
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        _fails.append(label)


def main() -> int:
    if not shutil.which("node"):
        print("node not available - skipping (not a failure)")
        return 0
    m = re.search(r"<script>(.*)</script>", PAGE, re.S)
    if not m:
        print("could not extract the page script")
        return 1
    js = m.group(1).replace("boot();", "")          # don't run the fetch-driven boot
    js = "var RUNS, i, cur, ADJ;\n" + js.replace("let RUNS=[], i=0, cur=null, ADJ=false;", "")

    tmp = Path(tempfile.mkdtemp(prefix="p2ctl_"))
    f = tmp / "harness.mjs"
    f.write_text(HARNESS.replace("__PAGE_JS__", js), encoding="utf-8")
    p = subprocess.run(["node", str(f)], capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        print("node failed:\n", (p.stderr or "")[-2000:])
        return 1
    out = json.loads(p.stdout.strip().splitlines()[-1])

    print("1. no value can break out of its own handler")
    check(not out["inline_onclick_present"],
          "decomposition buttons emit NO inline onclick (values travel in data-*)")
    check(not out["broken_attribute"],
          f"no emitted handler is truncated by an injected quote "
          f"({out['broken_attribute']})")

    print("\n2. each control sets only its own field")
    s = out["steps"]
    check(s[0]["dec"] == {"coverage": True, "exposure": None, "attribution": None},
          f"coverage click sets coverage only ({s[0]['dec']})")
    check(s[1]["dec"] == {"coverage": True, "exposure": False, "attribution": None},
          f"exposure click sets exposure only ({s[1]['dec']})")
    check(s[2]["dec"] == {"coverage": True, "exposure": False,
                          "attribution": "PARTIAL"},
          f"ATTRIBUTION click actually lands ({s[2]['dec']})")
    check(all(x["grade"] is None for x in s),
          "no decomposition click touches the Grade row")

    print("\n3. the Grade row is independent")
    check(out["after_pick"]["grade"] == "MISS"
          and out["after_pick"]["dec"]["attribution"] == "PARTIAL",
          "picking a grade leaves the decomposition untouched")
    check(out["after_reclick"]["dec"] == {"coverage": True, "exposure": False,
                                          "attribution": "FULL"}
          and out["after_reclick"]["grade"] == "MISS",
          "re-clicking attribution changes attribution only")

    print("\n4. the payload carries every schema-v2 field")
    posted = out.get("posted") or {}
    check(bool(posted), f"a POST body was built (alerts: {out.get('alerts')})")
    d = posted.get("decomposition") or {}
    dr = posted.get("decomposition_reasons") or {}
    check(d.get("coverage") is True and d.get("exposure") is False
          and d.get("attribution") == "FULL",
          f"decomposition.* all present ({d})")
    check(dr.get("coverage") == "SYN cov" and dr.get("exposure") == "SYN exp"
          and dr.get("attribution") == "SYN attr",
          f"decomposition_reasons.* all present ({dr})")
    check(posted.get("human_grade") == "MISS" and posted.get("human_reason"),
          "grade and reason also present")

    print("\n5. adjudicate mode freezes the human fields (DECISIONS.md #35 ruling A)")
    ac = out.get("adj_after_clicks") or {}
    check(ac.get("grade") == "MISS" and ac.get("dec") == ac.get("before", {}).get("dec")
          and ac.get("l2") is None,
          f"in ADJ the Grade row, decomposition and L2 tick ignore clicks ({ac})")
    check(out.get("adj_grade_buttons_disabled") is True,
          "in ADJ the grade buttons are emitted disabled")
    ap = out.get("adj_posted") or {}
    check(ap.get("adjudicated_grade") == "PARTIAL"
          and ap.get("adjudication_reason") == "SYN adjudication",
          f"the ADJ body carries the adjudicated grade and reason ({ap})")
    human_keys = {"human_grade", "human_reason", "decomposition",
                  "decomposition_reasons", "l2_length_side_channel_cited"}
    check(not (human_keys & set(ap)),
          f"the ADJ body carries NO human field at all ({sorted(human_keys & set(ap))})")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'=' * 62}")
    if _fails:
        print(f"FAILED {len(_fails)}/{_checks} checks:")
        for x in _fails:
            print(f"  - {x}")
        return 1
    print(f"ALL {_checks} CHECKS PASS")
    print("Real page JS under node. Nothing was posted to any server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
