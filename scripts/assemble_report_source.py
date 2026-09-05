#!/usr/bin/env python
"""Assemble `writeup/local/REPORT_SOURCE.md` from a filled write-up template.

    python scripts/assemble_report_source.py --filled writeup/local/WRITEUP_FILLED_EBIN_FIXED.md

The filled templates are the *template* file with the applicant's prose typed into
the `> ` blockquote slots. Every draft shares the template's skeleton (`## N.` and
`### ` headings, `**Step N — ...**` markers, the fact tables) and differs only in
the wording inside the blockquotes. So this script parses **by structure only** --
heading numbers and blockquote position -- and never matches on prose.

What it does, in one line each:

* the title block  -- H1 + authorline / credit / submission divs
* renumbers the report's sections (template 2..16 -> report 1..14)
* lifts the applicant's blockquote prose out of each slot, unwrapping the
  template's hard line wraps back into single paragraphs
* carries seven template tables over as numbered, captioned tables
* rebuilds section 2 as a compact block-1 digest and moves the full random
  examples to Appendix A
* appends the Sources list

Everything the script *adds* (i.e. text that is not the applicant's own) is
listed in ADDED_TEXT below and printed with --list-added.

No network, no model calls, nothing under data/sealed/ is read.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_EXAMPLES = REPO / "writeup" / "EXAMPLES_RANDOM.md"
DEFAULT_DEVIATIONS = REPO / "writeup" / "DEVIATIONS_TABLE.md"
DEFAULT_OUT = REPO / "writeup" / "local" / "REPORT_SOURCE.md"

# --------------------------------------------------------------------- constants

AUTHORLINE = "Ebin Babu Thomas (Independent) · Claude Fable 5/5.1, co-author"
SUBMISSION = "Submitted to MATS 12.0, Neel Nanda stream, September 2026"

MAIN_FIGURE = "![Main figure](../../results/figures/main_figure.png)"
MAIN_FIGURE_CAPTION = (
    "Figure 1. Panel A: outcome of every planned attempt on the three headline rungs, one "
    "bar per condition (v0, v1, battery, introspection, left to right), stacked FULL, "
    "PARTIAL, MISS and refusal, with k/n and a 95% Wilson interval on the FULL share; the "
    "exploratory L4v3 is boxed and outside every headline number. Panel B: the null pair, "
    "with false positive, correct rejection and refusal per condition, the frozen-rule rate "
    "among verdict-bearing runs printed above each bar, and the frozen ten-seed subset as "
    "the narrow bar; at right, dollars per FULL detection over all planned attempts. Cells "
    "are n = 5, 3 or 1, so one run moves any bar. Source: `scripts/make_figures.py`."
)
COVERAGE_FIGURE = "![Coverage figure](../../results/figures/coverage_figure.png)"

LLM_USAGE_LINE = "*This section also serves as the LLM usage statement.*"

APPENDIX_POINTER = (
    "Supporting quotes and grading reasons for these nine claims, and the two "
    "seeded-random claims per planted rung, are reproduced in full in Appendix A."
)

APPENDIX_HEADING = "## Appendix A. Random examples in full"

SOURCES = [
    "- Chughtai, B., Engels, J. and Nanda, N. (2026). *Building and evaluating model "
    "diffing agents.* AlignmentForum / LessWrong, 12 June 2026. "
    "<https://www.alignmentforum.org/posts/qi4mNbZYAFDYwfRba/"
    "building-and-evaluating-model-diffing-agents>",
    "- Qwen. *Qwen3.5-9B* (model card), Hugging Face, revision "
    "`c202236235762e1c871ad0ccb60c8ee5ba337b9a`, last modified 2 March 2026. "
    "<https://huggingface.co/Qwen/Qwen3.5-9B>",
]

# Table captions, in the order the tables appear in the report.
TABLE_CAPTIONS = {
    "arm_r": "Table 1. The Arm R table.",
    "arm_n": "Table 2. The Arm N table.",
    "v0_v1": "Table 3. Amendment 8 predictions and their outcomes.",
    "limits": "Table 4. Limitations.",
    "deviations": "Table 5. Post-unsealing deviations (D1–D6).",
    "ledger": "Table 6. Disagreement ledger.",
    "next": "Table 7. Next steps.",
}

# The template addresses the applicant as "you" inside its own fact tables. Those
# tables are carried into the report as the applicant's own text, so the second
# person is repaired. Applied only to carried-over TEMPLATE tables, never to
# blockquote prose.
SECOND_PERSON_FIXES = [
    ("you designed the behaviours", "I designed the behaviours"),
]

ADDED_TEXT = [
    "the H1 authorline placeholder `%s`" % AUTHORLINE,
    "the submission line `%s`" % SUBMISSION,
    "the `<div class=\"authorline\">` / `credit` / `submission` / `box` wrappers",
    "the section renumbering (template 2..16 -> report 1..14) and heading renames",
    "the two figure embeds and the `Figure 1.` caption "
    "(written by the coordinator from the figure, approved by Ebin on Sep 5)",
    "the seven `Table N. ...` captions",
    "Table 5, lifted from `writeup/DEVIATIONS_TABLE.md` §1b",
    "the limitations-table second-person repair: %s"
    % "; ".join('"%s" -> "%s"' % f for f in SECOND_PERSON_FIXES),
    "the one sentence `%s` under Division of labour" % LLM_USAGE_LINE,
    "the `## Sources` list (2 entries)",
    "the Appendix A pointer sentence: `%s`" % APPENDIX_POINTER,
    "the `%s` heading" % APPENDIX_HEADING,
]

# --------------------------------------------------------------------- parsing

SECTION_RE = re.compile(r"^##\s+(\d+)\.\s+(.*?)\s*$")
SUBHEAD_RE = re.compile(r"^###\s+(.*?)\s*$")
STEP_MARK_RE = re.compile(r"^\*\*Step\s+\d+\s*[—–-].*\*\*\s*$")
KEY_RE = re.compile(r"^(Slot\s+\d+|Step\s+\d+|\d+\.\d+|\d+[a-z])\b[\s.—–-]*(.*)$")
LIST_ITEM_RE = re.compile(r"^(\d+[.)]\s|[-*+]\s)")


class Unit:
    """One `### ` subsection (or one `**Step N —**` block) of a section."""

    def __init__(self, key: str | None, title: str):
        self.key = key
        self.title = title          # heading text after the key
        self.blockquotes: list[list[list[str]]] = []   # [ [paragraph[line]] ]
        self.tables: list[list[str]] = []
        self.bullets: list[list[str]] = []


class Section:
    def __init__(self, number: int, title: str):
        self.number = number
        self.title = title
        self.units: list[Unit] = []

    def unit(self, key: str) -> Unit:
        for u in self.units:
            if u.key == key:
                return u
        raise SystemExit(f"section {self.number}: no unit keyed {key!r} "
                         f"(have {[u.key for u in self.units]})")

    def all_units(self, prefix: str) -> list[Unit]:
        return [u for u in self.units if u.key and u.key.startswith(prefix)]


def _split_key(heading: str) -> tuple[str | None, str]:
    m = KEY_RE.match(heading)
    if m:
        key = re.sub(r"\s+", " ", m.group(1))
        return key, m.group(2).strip()
    return None, heading.strip()


def _unwrap(raw: list[str]) -> list[list[str]]:
    """Undo the template's hard wrapping inside one blockquote.

    Returns a list of paragraphs; each paragraph is a list of logical lines
    (more than one only for list items, which stay on their own lines)."""
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for line in raw:
        body = line[1:]
        body = body[1:] if body[:1] == " " else body
        if not body.strip():
            if current:
                paragraphs.append(current)
                current = []
            continue
        if not current or LIST_ITEM_RE.match(body.strip()):
            current.append(body.strip())
        else:
            current[-1] = current[-1] + " " + body.strip()
    if current:
        paragraphs.append(current)
    return paragraphs


def parse_filled(text: str) -> dict[int, Section]:
    lines = text.splitlines()
    sections: dict[int, Section] = {}
    section: Section | None = None
    unit: Unit | None = None
    i = 0
    while i < len(lines):
        line = lines[i]

        m = SECTION_RE.match(line)
        if m:
            section = Section(int(m.group(1)), m.group(2))
            sections[section.number] = section
            unit = Unit(None, "")
            section.units.append(unit)
            i += 1
            continue

        if line.startswith("## "):        # STYLE RULES, Final checklist, ...
            section = None
            unit = None
            i += 1
            continue

        if section is None:
            i += 1
            continue

        m = SUBHEAD_RE.match(line)
        if m:
            key, title = _split_key(m.group(1))
            unit = Unit(key, title)
            section.units.append(unit)
            i += 1
            continue

        if STEP_MARK_RE.match(line):
            key, title = _split_key(line.strip().strip("*"))
            unit = Unit(key, title)
            section.units.append(unit)
            i += 1
            continue

        if line.startswith(">"):
            block = []
            while i < len(lines) and lines[i].startswith(">"):
                block.append(lines[i])
                i += 1
            unit.blockquotes.append(_unwrap(block))
            continue

        if line.startswith("|"):
            table = []
            while i < len(lines) and lines[i].startswith("|"):
                table.append(lines[i].rstrip())
                i += 1
            unit.tables.append(table)
            continue

        if LIST_ITEM_RE.match(line):
            bullets = []
            while i < len(lines) and (LIST_ITEM_RE.match(lines[i])
                                      or (lines[i].startswith("  ") and lines[i].strip())):
                bullets.append(lines[i].rstrip())
                i += 1
            unit.bullets.append(bullets)
            continue

        i += 1
    return sections


# --------------------------------------------------------------------- helpers


def paras(bq: list[list[str]]) -> list[str]:
    """Blockquote -> markdown paragraphs, blank-line separated."""
    return ["\n".join(p) for p in bq]


def one_line(bq: list[list[str]]) -> str:
    return " ".join(" ".join(p) for p in bq).strip()


def fix_person(table: list[str]) -> list[str]:
    out = []
    for row in table:
        for a, b in SECOND_PERSON_FIXES:
            row = row.replace(a, b)
        out.append(row)
    return out


def deviations_table(path: pathlib.Path) -> list[str]:
    """The D1–D6 table under `### 1b.` in writeup/DEVIATIONS_TABLE.md."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((n for n, l in enumerate(lines)
                  if l.startswith("### 1b.")), None)
    if start is None:
        raise SystemExit(f"no '### 1b.' heading in {path}")
    table: list[str] = []
    for line in lines[start:]:
        if line.startswith("|"):
            table.append(line.rstrip())
        elif table:
            break
    if not table:
        raise SystemExit(f"no table under '### 1b.' in {path}")
    return table


def demote(text: str, levels: int = 2) -> str:
    """Push every ATX heading down `levels` levels."""
    return re.sub(r"^(#{1,6})(\s)",
                  lambda m: "#" * min(6, len(m.group(1)) + levels) + m.group(2),
                  text, flags=re.M)


HYPOTHESIS_LABEL = "**Hypothesis, verbatim:**"


def compact_block1(examples: str) -> list[str]:
    """Header line + `direction (...)` line + the verbatim hypothesis, per L0 claim.

    Structural parse of EXAMPLES_RANDOM.md: the `## Block 1` section, its `### `
    example headings, the `- direction (` bullet and the blockquote that follows
    the `**Hypothesis, verbatim:**` label. Nothing else is carried."""
    lines = examples.splitlines()
    start = next((n for n, l in enumerate(lines)
                  if re.match(r"^##\s+Block 1\b", l)), None)
    if start is None:
        raise SystemExit("no '## Block 1' heading in the examples file")
    end = next((n for n in range(start + 1, len(lines))
                if re.match(r"^##\s+Block 2\b", lines[n])), len(lines))

    out: list[str] = []
    n_claims = 0
    i = start + 1
    while i < end:
        if not lines[i].startswith("### "):
            i += 1
            continue
        header = "#" + lines[i]           # ### -> #### (demote by one)
        direction: str | None = None
        hypothesis: list[str] = []
        i += 1
        while i < end and not lines[i].startswith("### "):
            line = lines[i]
            if direction is None and line.startswith("- direction ("):
                direction = line.rstrip()
            elif line.strip() == HYPOTHESIS_LABEL:
                i += 1
                while i < end and not lines[i].startswith(">"):
                    i += 1
                while i < end and lines[i].startswith(">"):
                    hypothesis.append(lines[i].rstrip())
                    i += 1
                continue
            i += 1
        n_claims += 1
        out.append(header)
        if direction:
            out.append(direction)
        if hypothesis:
            out.append(HYPOTHESIS_LABEL)
            out.extend(hypothesis)
    if n_claims != 9:
        print(f"  note: block 1 carried {n_claims} claims (expected 9)",
              file=sys.stderr)
    return out


# --------------------------------------------------------------------- assembly


def assemble(filled: str, examples: str, deviations: list[str]) -> str:
    s = parse_filled(filled)
    for n in range(1, 17):
        if n not in s:
            raise SystemExit(f"filled template has no '## {n}.' section")

    o: list[str] = []          # output blocks, joined by a blank line

    # ---------------------------------------------------------- title block
    title = one_line(s[1].units[0].blockquotes[0]).strip("*").strip()
    o.append("# " + title)

    o.append('<div class="authorline" markdown="1">')
    o.append(AUTHORLINE)
    o.append("</div>")

    credit = paras(s[15].units[0].blockquotes[0]) if s[15].units[0].blockquotes else []
    if any(c.strip() for c in credit):
        o.append('<div class="credit" markdown="1">')
        o.extend(credit)
        o.append("</div>")

    links = s[16].units[0].bullets[0]
    repo = next((b for b in links if "Repo:" in b), None)
    o.append('<div class="submission" markdown="1">')
    o.append(SUBMISSION)
    if repo:
        o.append("Repository: " + repo.split("**", 2)[-1].strip(": ").strip())
    o.append("</div>")

    # ---------------------------------------------------- 1. exec summary
    o.append("## 1. Executive summary")
    for u in s[2].all_units("Slot"):
        o.extend(paras(u.blockquotes[0]))
    o.append(MAIN_FIGURE)
    o.append(MAIN_FIGURE_CAPTION)

    # -------------------------------------------------- 2. random examples
    o.append("## 2. Random examples")
    o.extend(paras(s[3].units[-1].blockquotes[0]))
    o.append("\n\n".join(_group(compact_block1(examples))))
    o.append(APPENDIX_POINTER)

    # ------------------------------------------------------- 3. methods
    o.append("## 3. Methods")
    for u in s[4].all_units("4."):
        o.append("### " + u.title)
        o.extend(paras(u.blockquotes[0]))

    # ----------------------------------------------------- 4. finding 1
    o.append("## 4. Finding 1: " + s[5].title.split("—", 1)[-1].strip())
    o.extend(paras(s[5].unit("Step 1").blockquotes[-1]))
    step2 = s[5].unit("Step 2")
    o.extend(paras(step2.blockquotes[0]))
    o.append(COVERAGE_FIGURE)
    o.append("Figure 2. " + one_line(step2.blockquotes[-1]))
    o.extend(paras(s[5].unit("Step 3").blockquotes[-1]))
    o.extend(paras(s[5].unit("Step 4").blockquotes[-1]))
    step5 = s[5].unit("Step 5")
    o.append("### " + step5.title)
    o.extend(paras(step5.blockquotes[-1]))
    o.extend(paras(s[5].unit("Step 6").blockquotes[-1]))

    # ----------------------------------------------------- 5. finding 2
    o.append("## 5. Finding 2: " + s[6].title.split("—", 1)[-1].strip())
    u6a = s[6].unit("6a")
    o.append("### 5a. " + u6a.title)
    o.extend(paras(u6a.blockquotes[-1]))
    u6b = s[6].unit("6b")
    o.append("### 5b. " + u6b.title)
    o.extend(paras(u6b.blockquotes[-1]) if u6b.blockquotes else [])
    o.extend(paras(s[6].unit("Step 1").blockquotes[-1]))
    o.extend(paras(s[6].unit("Step 2").blockquotes[-1]))
    step3 = s[6].unit("Step 3")
    o.append(TABLE_CAPTIONS["arm_r"])
    o.append("\n".join(step3.tables[0]))
    o.extend(paras(step3.blockquotes[-1]))
    step4 = s[6].unit("Step 4")
    o.append(TABLE_CAPTIONS["arm_n"])
    o.append("\n".join(step4.tables[0]))
    o.extend(paras(step4.blockquotes[-1]))
    o.extend(paras(s[6].unit("Step 5").blockquotes[-1]))

    # ------------------------------------------------ 6. secondary results
    o.append("## 6. Secondary results")
    for u in s[7].all_units("7."):
        o.append("### " + u.key.replace("7.", "6.") + " "
                 + u.title.split(" — ", 1)[0].strip())
        if u.key == "7.1" and u.tables:
            o.append(TABLE_CAPTIONS["v0_v1"])
            o.append("\n".join(u.tables[0]))
        o.extend(paras(u.blockquotes[-1]))

    # ----------------------------------------------------- 7. limitations
    o.append("## 7. " + s[8].title)
    o.append(TABLE_CAPTIONS["limits"])
    o.append("\n".join(fix_person(s[8].units[0].tables[0])))
    o.extend(paras(s[8].units[0].blockquotes[-1]))

    # ------------------------------------------------ 8. verified by hand
    o.append("## 8. " + s[9].title)
    o.extend(paras(s[9].units[0].blockquotes[-1]))

    # ------------------------------------------------------ 9. deviations
    o.append("## 9. " + s[10].title)
    o.extend(paras(s[10].units[0].blockquotes[-1]))
    o.append(TABLE_CAPTIONS["deviations"])
    o.append("\n".join(deviations))

    # ----------------------------------------------- 10. disagreement ledger
    o.append("## 10. " + s[11].title)
    o.append(TABLE_CAPTIONS["ledger"])
    o.append("\n".join(s[11].units[0].tables[0]))
    o.extend(paras(s[11].units[0].blockquotes[-1]))

    # ------------------------------------------------ 11. division of labour
    o.append("## 11. " + s[12].title)
    o.append(LLM_USAGE_LINE)
    o.append('<div class="box" markdown="1">')
    o.extend(paras(s[12].units[0].blockquotes[-1]))
    o.append("</div>")

    # ---------------------------------------------------------- 12. hours
    o.append("## 12. " + s[13].title)
    for bq in s[13].units[0].blockquotes:
        o.extend(paras(bq))

    # ----------------------------------------------------- 13. next steps
    o.append("## 13. " + s[14].title)
    o.append(TABLE_CAPTIONS["next"])
    o.append("\n".join(s[14].units[0].tables[0]))
    o.extend(paras(s[14].units[0].blockquotes[-1]))

    # ------------------------------------------------ 14. code, data, links
    o.append("## 14. Code, data and links")
    o.append("\n".join(links))

    # -------------------------------------------------------------- sources
    o.append("## Sources")
    o.append("\n".join(SOURCES))

    # ---------------------------------------------------------- appendix A
    o.append(APPENDIX_HEADING)
    o.append(demote(examples.strip(), 2))

    return "\n\n".join(b for b in o if b.strip()) + "\n"


def _group(lines: list[str]) -> list[str]:
    """Group the compact block-1 lines into paragraph-sized chunks."""
    out: list[str] = []
    buf: list[str] = []
    for line in lines:
        if line.startswith("#"):
            if buf:
                out.append("\n".join(buf))
                buf = []
            out.append(line)
        elif line.startswith(">"):
            if buf and not buf[-1].startswith(">"):
                out.append("\n".join(buf))
                buf = []
            buf.append(line)
        else:
            if buf:
                out.append("\n".join(buf))
                buf = []
            out.append(line)
    if buf:
        out.append("\n".join(buf))
    return out


# --------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filled", type=pathlib.Path, required=False,
                    help="the filled write-up template (the submission draft)")
    ap.add_argument("--examples", type=pathlib.Path, default=DEFAULT_EXAMPLES)
    ap.add_argument("--deviations", type=pathlib.Path, default=DEFAULT_DEVIATIONS)
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    ap.add_argument("--list-added", action="store_true",
                    help="print every non-verbatim addition and exit")
    args = ap.parse_args(argv)

    if args.list_added:
        print("Text this script adds (everything else is the applicant's, verbatim):")
        for item in ADDED_TEXT:
            print("  - " + item)
        return 0

    if args.filled is None:
        ap.error("--filled is required")

    filled = args.filled.resolve()
    if not filled.is_file():
        raise SystemExit(f"filled template not found: {filled}")

    text = assemble(filled.read_text(encoding="utf-8"),
                    args.examples.read_text(encoding="utf-8"),
                    deviations_table(args.deviations))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"filled     : {filled}")
    print(f"examples   : {args.examples}")
    print(f"out        : {args.out}  ({len(text):,} bytes, "
          f"{len(text.splitlines()):,} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
