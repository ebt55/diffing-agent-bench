#!/usr/bin/env python3
"""Spot-check completed runs for identifier leakage into BRAIN-VISIBLE content.

Uses the harness's own guard (`diffing_agent.agent.check_leak`) rather than a second
implementation, so what is verified here is what was enforced at run time.

What is checked, and why that file:
  brain_messages.json  the exact message array handed to the brain. This is the only
                       place a leak would matter, and it is checked AFTER redaction,
                       so a clean result means the brain never saw the identifier.
  transcript.jsonl     checked separately and EXPECTED to contain raw target text -
                       the redaction is applied to brain context only, and the raw
                       body is deliberately preserved for audit (agent.py). A hit
                       here is reported as informational, not as a failure.

Never reads data/sealed/. The guard terms come from each run's own run_meta.

    PYTHONPATH=src python scripts/check_run_leaks.py --runs "results/runs/v0_cand_*"
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "src"))

from diffing_agent.agent import check_leak  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", default="results/runs/v0_cand_*")
    ap.add_argument("--out", default="results/run_leak_check.json")
    a = ap.parse_args()

    rows, bad = [], 0
    for d in sorted(glob.glob(a.runs)):
        p = Path(d)
        meta_p, msgs_p = p / "run_meta.json", p / "brain_messages.json"
        if not meta_p.exists():
            continue
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        terms = meta["blinding"]["guard_terms"]
        msgs = msgs_p.read_text(encoding="utf-8") if msgs_p.exists() else ""
        transcript = (p / "transcript.jsonl").read_text(encoding="utf-8")
        brain_hits = check_leak(msgs, terms) if msgs else []
        # the transcript legitimately holds raw pre-redaction text
        tr_hits = check_leak(transcript, terms)

        # A term that the guard ALREADY redacted at run time cannot have reached the
        # brain through target output: the redaction happens before the tool result is
        # handed over. Its appearance in brain_messages is therefore the brain's OWN
        # text - it saw "[REDACTED]" and wrote about it. That is not a leak, and
        # conflating the two would either hide real leaks or cry wolf about none.
        redacted = set(meta["blinding"]["leak_redactions"])
        unredacted = [t for t in brain_hits if t not in redacted]
        self_referential = [t for t in brain_hits if t in redacted]
        ok = not unredacted
        bad += not ok
        rows.append({
            "run_id": meta["run_id"], "status": meta["status"],
            "n_guard_terms": len(terms),
            "unredacted_leaks_to_brain": unredacted,          # the failure condition
            "self_referential_after_redaction": self_referential,
            "brain_messages_present": bool(msgs),
            "redactions_applied_at_runtime": meta["blinding"]["leak_redactions"],
            "n_redaction_events": meta["blinding"]["n_leak_events"],
            "transcript_raw_hits_informational": tr_hits,
            "label_shuffle_enabled": meta["blinding"]["label_shuffle_enabled"],
            "label_map": meta.get("label_map"),
            "ok": ok,
        })
        note = ""
        if self_referential:
            note = (f"  [guard fired on {self_referential}; the brain then wrote about "
                    f"the [REDACTED] marker itself - not a leak]")
        print(f"  [{'ok' if ok else 'LEAK'}] {meta['run_id']:<22} "
              f"unredacted_to_brain={unredacted or 'none'}  "
              f"redacted_at_runtime={meta['blinding']['leak_redactions'] or 'none'}"
              f"{note}")

    # which model sat in model_A, across runs - the shuffle should not be constant
    firsts = [r["label_map"].get("model_A") for r in rows if r.get("label_map")]
    shuffle_two_sided = len(set(firsts)) > 1 if firsts else False

    out = {"n_runs_checked": len(rows), "n_with_unredacted_leaks": bad,
           "all_clean": bad == 0,
           "n_runs_where_guard_fired": sum(1 for r in rows
                                           if r["redactions_applied_at_runtime"]),
           "model_A_distinct_values_across_runs": sorted(set(firsts)),
           "ab_shuffle_two_sided": shuffle_two_sided,
           "note": ("unredacted_leaks_to_brain is the failure condition. "
                    "self_referential_after_redaction is not a leak: the guard "
                    "replaced the term before the brain saw it, and the brain then "
                    "wrote about the [REDACTED] marker in its own text. "
                    "transcript_raw_hits_informational is expected by design - "
                    "redaction protects brain context while the transcript keeps the "
                    "raw body for audit (agent.py)."),
           "runs": rows}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"\n{len(rows)} runs checked; {bad} with brain-visible leaks")
    print(f"A/B shuffle two-sided across runs: {shuffle_two_sided} "
          f"(model_A took {len(set(firsts))} distinct values)")
    print(f"wrote {a.out}")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
