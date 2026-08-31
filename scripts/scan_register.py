#!/usr/bin/env python3
"""Scan the battery and the trigger suites for archaic / uncommon-register vocabulary.

Amendment 4 item 5. The 50-prompt battery was constructed CODEWORD-free, and that was
recorded as the reason it is structurally blind to L4. The L4v3 adapter turned out to
be conditioned on archaic *register*, not on the token, so codeword-freeness is no
longer the property that matters: **register-blindness** is, and it must be measured
rather than assumed.

Method, stated in full because there is no offline dictionary of archaisms on the pod
and an unauditable check would be worse than none:

  1. a curated lexicon in two tiers -
       STRONG      unambiguously archaic in modern English (perchance, forsooth,
                   mayhap, thou, hath, prithee, ...)
       BORDERLINE  formal or literary but current (whilst, amongst, albeit, hence,
                   notwithstanding, ...)
  2. archaic morphology - the -eth verb ending (with an exclusion list for ordinary
     nouns like "death"), and the elided forms 'tis / 'twas / o'er / ne'er / e'er
  3. a corpus-rarity proxy - battery tokens that appear in NEITHER the 800 training
     prompts NOR the 800 base responses NOR the suites, listed so a human can eyeball
     the battery's vocabulary for register

**Verdict rule, fixed here before the scan runs:** a prompt set is REGISTER-CLEAN iff
it contains zero STRONG hits and zero morphology hits. Borderline hits are reported
and do not flip the verdict - they exist so the judgement is visible, not automated.

If the battery is not register-clean, that is reported. The battery is frozen; this
script never edits it.

    python scripts/scan_register.py
    python scripts/scan_register.py --out results/register_scan.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _or_client import read_jsonl  # noqa: E402

# --- tier 1: unambiguously archaic -------------------------------------------------
STRONG = sorted({
    "perchance", "forsooth", "mayhap", "prithee", "verily", "methinks", "betwixt",
    "quoth", "ere", "alack", "zounds", "hark", "anon", "peradventure", "howbeit",
    "withal", "yon", "yonder", "whence", "whither", "hither", "thither", "wherefore",
    "thee", "thou", "thy", "thine", "ye", "hath", "doth", "dost", "hast", "hadst",
    "saith", "sayeth", "goeth", "cometh", "knowest", "thinkest", "wilt", "shalt",
    "canst", "wouldst", "couldst", "shouldst", "mayest", "erstwhile", "fain",
    "morrow", "aught", "naught", "nought", "wroth", "twain", "vouchsafe", "beseech",
    "bespake", "durst", "ofttimes", "oftentimes", "whereat", "whereto",
})
# elided / contracted archaic forms; matched separately because of the apostrophes
ELIDED = [r"'tis\b", r"'twas\b", r"'twere\b", r"o'er\b", r"ne'er\b", r"e'er\b",
          r"e'en\b"]

# --- tier 2: formal or literary but current ----------------------------------------
BORDERLINE = sorted({
    "whilst", "amongst", "albeit", "hence", "henceforth", "heretofore", "hitherto",
    "notwithstanding", "forthwith", "thereof", "therein", "thereto", "thereupon",
    "wherein", "whereupon", "whereof", "sundry", "behold", "nigh", "yea", "nay",
    "aye", "oft", "thusly", "apace", "wont", "lo", "alas",
})

# --- morphology --------------------------------------------------------------------
# The -eth verb ending. Ordinary modern words ending in "eth" are excluded by name;
# a bare \w+eth\b would otherwise flag "death", "beneath" and friends on every scan.
ETH_EXCLUSIONS = {
    "death", "breath", "teeth", "beneath", "underneath", "wreath", "heath", "sheath",
    "seeth", "bequeath", "beth", "meth", "moth", "sleuth", "bereth", "elizabeth",
    "macbeth", "kenneth", "teleth", "toothbreath",
}
RE_ETH = re.compile(r"\b([a-z]{3,}eth)\b", re.I)
RE_WORD = re.compile(r"[a-z][a-z'\-]*", re.I)


def find_hits(text: str) -> dict:
    """All three checks over one prompt. Returns matched tokens per category."""
    low = text.lower()
    strong = sorted({w for w in STRONG
                     if re.search(rf"(?<![0-9A-Za-z_]){re.escape(w)}(?![0-9A-Za-z_])", low)})
    elided = sorted({m.group(0) for pat in ELIDED
                     for m in re.finditer(pat, low)})
    borderline = sorted({w for w in BORDERLINE
                         if re.search(rf"(?<![0-9A-Za-z_]){re.escape(w)}(?![0-9A-Za-z_])", low)})
    eth = sorted({m.group(1).lower() for m in RE_ETH.finditer(low)
                  if m.group(1).lower() not in ETH_EXCLUSIONS})
    return {"strong": strong, "elided": elided, "morphology_eth": eth,
            "borderline": borderline}


def scan_prompts(rows: list[tuple[str, str]]) -> dict:
    """rows: [(id, text)]. Returns per-set summary + every hit, with the verdict."""
    hits = []
    for rid, text in rows:
        h = find_hits(text)
        if any(h.values()):
            hits.append({"id": rid, "text": text, **h})
    n_strong = sum(1 for h in hits if h["strong"] or h["elided"] or h["morphology_eth"])
    n_border = sum(1 for h in hits if h["borderline"]
                   and not (h["strong"] or h["elided"] or h["morphology_eth"]))
    return {
        "n_prompts": len(rows),
        "n_prompts_with_strong_or_morphology": n_strong,
        "n_prompts_with_borderline_only": n_border,
        "register_clean": n_strong == 0,
        "hits": hits,
    }


def tokens(texts) -> set[str]:
    out: set[str] = set()
    for t in texts:
        out |= {m.group(0).lower() for m in RE_WORD.finditer(t)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--battery", default="data/baseline_battery.jsonl")
    ap.add_argument("--suites", default="results/review/trigger_suites_FINAL.json")
    ap.add_argument("--prompts", default="data/prompts_master.jsonl")
    ap.add_argument("--responses", default="data/responses_base.jsonl")
    ap.add_argument("--out", default="results/register_scan.json")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    battery = read_jsonl(a.battery)
    bat = scan_prompts([(r["id"], r["text"]) for r in battery])

    suites = json.loads(Path(a.suites).read_text())
    suite_scans: dict[str, dict] = {}
    for suite, cols in suites.items():
        for col, prompts in cols.items():
            s = scan_prompts([(f"{suite}.{col}[{i}]", p) for i, p in enumerate(prompts)])
            suite_scans[f"{suite}.{col}"] = s

    # by-design archaic columns: the L4 trigger column and its token-specificity rows,
    # plus the single deliberate codeword probe inside the L0 suite (decision 9b).
    BY_DESIGN = {"L4.trigger", "L4.control_archaic", "L0.trigger"}
    unexpected = sorted(k for k, s in suite_scans.items()
                        if not s["register_clean"] and k not in BY_DESIGN)

    # corpus-rarity proxy: battery vocabulary found nowhere else in the project
    bat_tokens = tokens(r["text"] for r in battery)
    elsewhere = tokens([r["text"] for r in read_jsonl(a.prompts)])
    elsewhere |= tokens([r["response"] for r in read_jsonl(a.responses)])
    elsewhere |= tokens([p for cols in suites.values() for ps in cols.values() for p in ps])
    battery_unique = sorted(bat_tokens - elsewhere)

    report = {
        "purpose": ("Amendment 4 item 5: the battery's structural blindness to the L4 "
                    "arm now depends on register, not on the codeword, so register is "
                    "measured rather than assumed."),
        "method": {
            "tiers": {"strong": len(STRONG), "borderline": len(BORDERLINE),
                      "elided_patterns": len(ELIDED)},
            "morphology": "-eth verb ending, with an exclusion list",
            "verdict_rule": ("register-clean iff zero STRONG, elided or morphology "
                             "hits; borderline hits are reported, not decisive"),
            "limitation": ("no offline dictionary of archaisms is available on the "
                           "pod, so the lexicon is curated and listed in full below "
                           "for audit; the corpus-rarity list is a proxy, not a "
                           "dictionary check"),
            "strong_lexicon": STRONG,
            "borderline_lexicon": BORDERLINE,
            "elided_patterns": ELIDED,
            "eth_exclusions": sorted(ETH_EXCLUSIONS),
        },
        "battery": {"file": a.battery, **bat},
        "suites": {"file": a.suites, "by_design_archaic_columns": sorted(BY_DESIGN),
                   "unexpected_archaic_columns": unexpected, "columns": suite_scans},
        "battery_unique_vocabulary": {
            "n": len(battery_unique),
            "note": ("tokens present in the battery but in none of the 800 training "
                     "prompts, the 800 base responses or the suites - a rarity proxy "
                     "for eyeballing register, not an archaism test"),
            "tokens": battery_unique,
        },
        "verdict": {
            "battery_register_clean": bat["register_clean"],
            "suites_clean_outside_by_design": not unexpected,
        },
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    if not a.quiet:
        print(f"battery {a.battery}: {bat['n_prompts']} prompts")
        print(f"  strong/elided/morphology hits : "
              f"{bat['n_prompts_with_strong_or_morphology']} prompts")
        print(f"  borderline-only hits          : "
              f"{bat['n_prompts_with_borderline_only']} prompts")
        for h in bat["hits"]:
            cats = {k: v for k, v in h.items() if k not in ("id", "text") and v}
            print(f"    {h['id']}: {cats}  | {h['text'][:70]!r}")
        print(f"  REGISTER-CLEAN: {bat['register_clean']}")
        print(f"\nsuites: {len(suite_scans)} columns scanned")
        for k, s in sorted(suite_scans.items()):
            if not s["register_clean"]:
                flag = "by design" if k in BY_DESIGN else "*** UNEXPECTED ***"
                toks = sorted({t for h in s["hits"] for t in
                               h["strong"] + h["elided"] + h["morphology_eth"]})
                print(f"  {k:22s} {s['n_prompts_with_strong_or_morphology']}/"
                      f"{s['n_prompts']} prompts {toks}  [{flag}]")
        print(f"  unexpected archaic columns: {unexpected or 'none'}")
        print(f"\nbattery-unique vocabulary: {len(battery_unique)} tokens")
        print(f"wrote {a.out}")
    return 0 if bat["register_clean"] and not unexpected else 1


if __name__ == "__main__":
    sys.exit(main())
