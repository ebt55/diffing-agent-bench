#!/usr/bin/env python3
"""Two receipts the write-up needs verbatim: the GLM-vs-Opus cost ratios, and what a
terminal refusal actually is.

WHY. Both final-scrutiny reviews stop on the same two sentences.

  (1) "291x cheaper" (DECISIONS.md #25, #36) is one of FOUR defensible ratios and the
      four differ by an order of magnitude. This script prints all four with their
      formulas and denominators so the write-up can name the one it is quoting.
  (2) The refusal mechanism sentence. `run_meta.json` records `status` =
      `brain_refusal` and a per-call `stop_reason` = `refusal`, and NOTHING else - the
      provider's classifier category and explanation live only in the transcript's
      `brain_refusal` event, under `raw.stop_details`. This script prints both, per run,
      so the mechanism can be described from the field values rather than paraphrased.

Inputs: results/analysis/run_inventory.json, each refusal run's run_meta.json and
transcript.jsonl. No file under data/sealed/ is read.

    python scripts/cost_and_refusal_receipts.py
    python scripts/cost_and_refusal_receipts.py --repo <fixture-root> --out-md ...
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

OPUS = "v0_opus"
GLM = "glm_v0"
FIELDS = ("brain_usd", "total_usd", "pod_usd")
RE_PROBE_INTENT = re.compile(
    r"borderline|dual[- ]use|edgier|edge[- ]case|harmful|jailbreak|refusal", re.I)


def read_jsonl(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            yield json.loads(line)


def cost_block(runs: list[dict]) -> dict:
    opus = [r for r in runs if r["condition"] == OPUS]
    glm = [r for r in runs if r["condition"] == GLM]
    key = lambda r: (r["rung"], r["seed"])  # noqa: E731
    om, gm = {key(r): r for r in opus}, {key(r): r for r in glm}
    pairs = sorted(set(om) & set(gm))
    unpaired_only_opus = sorted(set(om) - set(gm))

    out = {
        "n_opus_all": len(opus), "n_glm_all": len(glm), "n_pairs": len(pairs),
        "pairing_key": "(rung, seed)",
        "opus_runs_with_no_glm_partner": [f"{r}:{s}" for r, s in unpaired_only_opus],
        "unpaired": {}, "paired": {},
    }
    for f in FIELDS:
        so, sg = sum(r[f] for r in opus), sum(r[f] for r in glm)
        mo, mg = so / len(opus), sg / len(glm)
        out["unpaired"][f] = {
            "opus_sum": round(so, 6), "opus_n": len(opus), "opus_mean": round(mo, 6),
            "glm_sum": round(sg, 6), "glm_n": len(glm), "glm_mean": round(mg, 6),
            "ratio_of_means": round(mo / mg, 2) if mg else None,
            "formula": (f"(sum {f} over all {len(opus)} {OPUS} runs / {len(opus)}) / "
                        f"(sum {f} over all {len(glm)} {GLM} runs / {len(glm)})"),
        }
        po = sum(om[k][f] for k in pairs)
        pg = sum(gm[k][f] for k in pairs)
        ratios = [om[k][f] / gm[k][f] for k in pairs if gm[k][f] > 0]
        out["paired"][f] = {
            "opus_sum": round(po, 6), "glm_sum": round(pg, 6), "n_pairs": len(pairs),
            "opus_mean": round(po / len(pairs), 6),
            "glm_mean": round(pg / len(pairs), 6),
            "ratio_of_means": round((po / len(pairs)) / (pg / len(pairs)), 2) if pg
            else None,
            "median_per_pair_ratio": round(statistics.median(ratios), 2) if ratios
            else None,
            "formula": (f"over the {len(pairs)} (rung, seed) pairs present in BOTH "
                        f"arms: (sum {f} opus / {len(pairs)}) / "
                        f"(sum {f} glm / {len(pairs)})"),
        }
    # The headline $/FULL numerator excludes the exploratory pair (Amendment 4 item 2);
    # the all-40 figure includes it. Both appear in the scaffolds; print the bridge.
    expl = [r for r in opus if r["rung"] not in ("L0", "L1", "L2", "L3")]
    head = [r for r in opus if r["rung"] in ("L0", "L1", "L2", "L3")]
    out["opus_total_usd_all_runs"] = round(sum(r["total_usd"] for r in opus), 6)
    out["opus_total_usd_headline_pairs"] = round(sum(r["total_usd"] for r in head), 6)
    out["opus_total_usd_exploratory_pair"] = round(
        sum(r["total_usd"] for r in expl), 6)
    out["n_headline_runs"] = len(head)
    out["n_exploratory_runs"] = len(expl)
    return out


def refusal_block(repo: Path, runs: list[dict]) -> list[dict]:
    rows = []
    for r in sorted((x for x in runs if x["outcome"] == "refusal_no_verdict"),
                    key=lambda x: (x["condition"], x["run_id"])):
        d = repo / r["run_dir"]
        meta = json.loads((d / "run_meta.json").read_text(encoding="utf-8"))
        calls = meta.get("brain", {}).get("calls", [])
        refusal_calls = [c for c in calls if c.get("stop_reason") == "refusal"]
        extra_keys = sorted({k for c in calls for k in c})
        events = list(read_jsonl(d / "transcript.jsonl"))
        br = [e for e in events if e.get("type") == "brain_refusal"]
        raw = (br[-1].get("raw") or {}) if br else {}
        sd = raw.get("stop_details") or {}
        brain_resps = [e for e in events if e.get("type") == "brain_response"]
        last = brain_resps[-1] if brain_resps else {}
        text = (last.get("text") or "").strip()
        tool_input = ""
        for tc in last.get("tool_calls") or []:
            v = (tc.get("input") or {}).get("prompts")
            if v:
                tool_input = v if isinstance(v, str) else json.dumps(v)
                break
        words = text.split()
        rows.append({
            "condition": r["condition"],
            "run_id": r["run_id"],
            "rung": r["rung"],
            "run_meta_status": meta.get("status"),
            "run_meta_verdict": meta.get("verdict"),
            "stop_reason_values": [c.get("stop_reason") for c in calls],
            "n_calls": len(calls),
            "refusal_call_turns": [c.get("turn") for c in refusal_calls],
            "refusal_turn_in_inventory": r.get("refusal_turn"),
            "call_object_keys": extra_keys,
            "error_field_present": any("error" in c for c in calls),
            "transcript_stop_reason": raw.get("stop_reason"),
            "stop_details_type": sd.get("type"),
            "stop_details_category": sd.get("category"),
            "stop_details_explanation": sd.get("explanation"),
            "last_brain_text_quote_25w": " ".join(words[:25]),
            "last_brain_text_truncated_or_empty": len(words) < 4,
            "last_tool_call_prompts_fragment": tool_input[:300],
            "announces_borderline_probing": bool(RE_PROBE_INTENT.search(text)),
        })
    return rows


def md_escape(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def render_md(cost: dict, refusals: list[dict]) -> str:
    L, A = [], None
    A = L.append
    A("# Cost ratios and refusal semantics - receipts")
    A("")
    A("Generated by `scripts/cost_and_refusal_receipts.py` from "
      "`results/analysis/run_inventory.json` and the refusal runs' own "
      "`run_meta.json` / `transcript.jsonl`. Nothing here is hand-typed and no file "
      "under `data/sealed/` is read.")
    A("")
    A("## 1 - GLM vs Opus v0: four ratios, four denominators")
    A("")
    A(f"- unpaired: all **{cost['n_opus_all']}** `{OPUS}` runs vs all "
      f"**{cost['n_glm_all']}** `{GLM}` runs")
    A(f"- seed-paired: the **{cost['n_pairs']}** `{cost['pairing_key']}` pairs present "
      f"in both arms. The {len(cost['opus_runs_with_no_glm_partner'])} Opus runs with "
      f"no GLM partner are the Amendment-7 L0 seed extension: "
      f"{', '.join(cost['opus_runs_with_no_glm_partner'])}")
    A("")
    A("| field | pairing | Opus $/run | GLM $/run | ratio | formula |")
    A("|---|---|---|---|---|---|")
    for f in FIELDS:
        u = cost["unpaired"][f]
        p = cost["paired"][f]
        A(f"| `{f}` | unpaired | ${u['opus_mean']:.6f} | ${u['glm_mean']:.6f} | "
          f"**{u['ratio_of_means']}x** | {md_escape(u['formula'])} |")
        A(f"| `{f}` | seed-paired | ${p['opus_mean']:.6f} | ${p['glm_mean']:.6f} | "
          f"**{p['ratio_of_means']}x** | {md_escape(p['formula'])} |")
    A("")
    A("Sums behind those means:")
    A("")
    A("| field | pairing | Opus sum | n | GLM sum | n | median per-pair ratio |")
    A("|---|---|---|---|---|---|---|")
    for f in FIELDS:
        u, p = cost["unpaired"][f], cost["paired"][f]
        A(f"| `{f}` | unpaired | ${u['opus_sum']} | {u['opus_n']} | ${u['glm_sum']} | "
          f"{u['glm_n']} | - |")
        A(f"| `{f}` | seed-paired | ${p['opus_sum']} | {p['n_pairs']} | "
          f"${p['glm_sum']} | {p['n_pairs']} | {p['median_per_pair_ratio']}x |")
    A("")
    A(f"- `pod_usd` is why the two ratios differ by an order of magnitude: the pod "
      f"serves the TARGETS, so it is charged to both arms at a similar rate "
      f"(${cost['unpaired']['pod_usd']['opus_mean']:.6f}/run vs "
      f"${cost['unpaired']['pod_usd']['glm_mean']:.6f}/run) and it dominates GLM's "
      f"`total_usd` while it is a rounding error on Opus's.")
    A(f"- bridge between the two Opus spend figures in the scaffolds: "
      f"`total_usd` over all {cost['n_opus_all']} runs = "
      f"${cost['opus_total_usd_all_runs']}; over the "
      f"{cost['n_headline_runs']} headline-pair runs (L0-L3) = "
      f"${cost['opus_total_usd_headline_pairs']}; the "
      f"{cost['n_exploratory_runs']} exploratory-pair runs are the difference, "
      f"${cost['opus_total_usd_exploratory_pair']}.")
    A("")

    A("## 2 - What a terminal refusal is, per run")
    A("")
    A("`run_meta.json` carries `status` and a per-call `stop_reason`. It carries NO "
      "error field and no classifier field: the call objects have exactly the keys "
      "listed below. The provider's classifier category and explanation exist only in "
      "the transcript's `brain_refusal` event under `raw.stop_details`.")
    A("")
    A("| run | rung | run_meta `status` | `verdict` | per-call `stop_reason` sequence | "
      "refusal turn | transcript `raw.stop_reason` | `stop_details.type` | "
      "`stop_details.category` |")
    A("|---|---|---|---|---|---|---|---|---|")
    for r in refusals:
        A("| `{}` | {} | `{}` | {} | {} | {} | `{}` | `{}` | `{}` |".format(
            r["run_id"], r["rung"], r["run_meta_status"],
            "null" if r["run_meta_verdict"] is None else "present",
            ", ".join(str(s) for s in r["stop_reason_values"]),
            r["refusal_turn_in_inventory"], r["transcript_stop_reason"],
            r["stop_details_type"], r["stop_details_category"]))
    A("")
    keys = sorted({k for r in refusals for k in r["call_object_keys"]})
    A(f"- `run_meta.brain.calls[]` keys, union over all refusal runs: "
      f"{', '.join('`' + k + '`' for k in keys)} - no `error`, no `classifier`, no "
      f"`refusal` field.")
    cats = sorted({r["stop_details_category"] for r in refusals})
    A(f"- `stop_details.category` values observed: {cats} "
      f"({len(refusals)} of {len(refusals)} runs).")
    expl = sorted({r["stop_details_explanation"] for r in refusals if
                   r["stop_details_explanation"]})
    if len(expl) == 1:
        A(f"- `stop_details.explanation` is byte-identical across all "
          f"{len(refusals)} runs; its first sentence: "
          f"\"{expl[0].split('. ')[0]}.\"")
    A("")
    A("### The auditor's own last words before the cut")
    A("")
    A("The refusal lands on the assistant turn the auditor was composing: the same "
      "`brain_response` event carries `stop_reason: refusal`, a partial `text`, and a "
      "partial `query_models` tool call whose `prompts` argument is truncated "
      "mid-string. Quotes below are the first 25 words of that partial text.")
    A("")
    A("| run | turn | last brain text (<=25 words) | announces borderline/dual-use "
      "probing? | truncated `prompts` argument (first 300 chars) |")
    A("|---|---|---|---|---|")
    for r in refusals:
        A("| `{}` | {} | {} | {} | {} |".format(
            r["run_id"], r["refusal_turn_in_inventory"],
            md_escape(r["last_brain_text_quote_25w"]) or "(empty)",
            "yes" if r["announces_borderline_probing"] else "no",
            md_escape(r["last_tool_call_prompts_fragment"]) or "(none recorded)"))
    A("")
    n_ann = sum(1 for r in refusals if r["announces_borderline_probing"])
    n_trunc = sum(1 for r in refusals if r["last_brain_text_truncated_or_empty"])
    n_tool = sum(1 for r in refusals if r["last_tool_call_prompts_fragment"])
    A(f"- last-turn text names borderline / dual-use / edgier / refusal probing in "
      f"**{n_ann} of {len(refusals)}** runs; **{n_trunc}** of the partial texts are "
      f"under four words (cut before the sentence finished); a partial tool-call "
      f"`prompts` argument survives in **{n_tool} of {len(refusals)}**.")
    A("")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--out-md", default=None)
    ap.add_argument("--out-json", default=None)
    a = ap.parse_args()
    repo = Path(a.repo).resolve()
    out_md = (Path(a.out_md) if a.out_md
              else repo / "results/analysis/cost_and_refusal_receipts.md")
    out_json = (Path(a.out_json) if a.out_json
                else repo / "results/analysis/cost_and_refusal_receipts.json")

    inv = json.loads((repo / "results/analysis/run_inventory.json")
                     .read_text(encoding="utf-8"))
    runs = inv["runs"]
    cost = cost_block(runs)
    refusals = refusal_block(repo, runs)

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_md(cost, refusals), encoding="utf-8")
    out_json.write_text(json.dumps({
        "schema": "cost_and_refusal_receipts/1",
        "spend_field_note": inv.get("spend_field_caveat"),
        "cost": cost,
        "refusals": refusals,
    }, indent=2), encoding="utf-8")
    print(f"wrote {out_md}")
    print(f"wrote {out_json}")
    print("brain unpaired {}x | brain paired {}x | total unpaired {}x | total paired "
          "{}x".format(cost["unpaired"]["brain_usd"]["ratio_of_means"],
                       cost["paired"]["brain_usd"]["ratio_of_means"],
                       cost["unpaired"]["total_usd"]["ratio_of_means"],
                       cost["paired"]["total_usd"]["ratio_of_means"]))
    print(f"refusal runs: {len(refusals)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
