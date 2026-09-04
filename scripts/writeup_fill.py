#!/usr/bin/env python3
"""Fill in writeup/WRITEUP_TEMPLATE.md, one slot at a time, with the facts beside it.

The template is 42 blanks long and every blank has its own numbers, its own
denominators and its own caveats sitting immediately above it. This tool shows one
blank at a time with exactly that facts block rendered beside it, and puts every
supporting file one click away in a right rail.

WHAT THIS TOOL WILL NOT DO, BY CONSTRUCTION
  * it contains NO draft prose, no suggested sentences, no autocomplete
  * it makes NO model call of any kind and opens no outbound socket
  * it never reads anything under data/sealed/
Everything the page shows is either the template's own text or another committed file.
Every word of every answer is typed by Ebin.

WHAT IT WRITES
  writeup/DRAFT_ANSWERS.json          slot id -> {text, updated_utc, word_count}
  writeup/DRAFT.md                    the template with each answered marker replaced
  writeup/DRAFT_ANSWERS_history.jsonl append-only, one line per save, never rewritten
The first two are written atomically (temp file + os.replace). The third is the reason
text cannot be lost: every save is appended before the answers file is rewritten.

    python scripts/writeup_fill.py                  # start the page on 127.0.0.1:8770
    python scripts/writeup_fill.py --status         # filled/unfilled per section
    python scripts/writeup_fill.py --export-section 6   # plain text for a numbers check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

TEMPLATE_REL = "writeup/WRITEUP_TEMPLATE.md"
ANSWERS_REL = "writeup/DRAFT_ANSWERS.json"
DRAFT_REL = "writeup/DRAFT.md"
HISTORY_REL = "writeup/DRAFT_ANSWERS_history.jsonl"
JOURNEY_REL = "writeup/PROJECT_JOURNEY.md"

# A slot is a blockquote line that OPENS with the marker. `> Words used: [Ebin writes]`
# is deliberately not one: it is a count Ebin writes into the template itself, not a
# prose slot, and --status reports it under "not placed" so it cannot be forgotten.
MARKER_RE = re.compile(r"^>\s*\[Ebin writes\b")
MENTION_RE = re.compile(r"\[Ebin writes")
H2_RE = re.compile(r"^##\s+(.*?)\s*$")
SUBH_RE = re.compile(r"^(#{3,6})\s+(.*?)\s*$")
NUM_RE = re.compile(r"^(\d+)\.")
EXEC_RE = re.compile(r"executive\s+summary", re.I)
LIMIT_RE = re.compile(r"[\u2264<=]\s*(\d+)\s*words")
DEFAULT_EXEC_LIMIT = 600

# (tab name, title, repo-relative path). `figures` has no markdown source: it renders
# the two committed PNGs, which are the only static files this server will serve.
REFERENCES: list[tuple[str, str, str | None]] = [
    ("journey", "journey", JOURNEY_REL),
    ("tables", "tables.md", "results/analysis/tables.md"),
    ("ledger", "grade ledger", "results/analysis/grade_ledger.md"),
    ("examples", "examples", "writeup/EXAMPLES_RANDOM.md"),
    ("skeletons", "form answers", "writeup/FORM_ANSWER_SKELETONS.md"),
    ("future", "future work", "writeup/FUTURE_WORK_LEDGER.md"),
    ("deviations", "deviations", "writeup/DEVIATIONS_TABLE.md"),
    ("hours", "hours", "writeup/HOURS_RECONSTRUCTION.md"),
    ("decisions", "decisions", "DECISIONS.md"),
    ("figures", "figures", None),
]
# The ONLY files served as static bytes. Anything else under results/ is a 404; the
# rest of results/ holds raw transcripts and is not this tool's business.
FIGURES = {
    "main_figure.png": "results/figures/main_figure.png",
    "coverage_figure.png": "results/figures/coverage_figure.png",
}
BANNED_READS = ("data/sealed",)


def _guard_path(p: Path) -> None:
    s = str(p).replace("\\", "/")
    for b in BANNED_READS:
        if b in s:
            raise RuntimeError(f"refusing to read {p}: {b} is sealed")


def read_text(p: Path) -> str:
    _guard_path(p)
    return p.read_text(encoding="utf-8", errors="replace")


# ------------------------------------------------------------ markdown-lite
# Enough markdown to READ a facts block: headings, bold, italic, inline code, fenced
# code, lists, tables, blockquotes, rules, links. Not a spec-compliant renderer and
# not trying to be - it renders committed files that are already known to be tidy.
_RE_CODE = re.compile(r"`([^`]+)`")
_RE_AUTOLINK = re.compile(r"&lt;(https?://[^\s&]+)&gt;")
_RE_LINK = re.compile(r"\[([^\]\n]*)\]\(([^)\s]+)\)")
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_RE_ITAL = re.compile(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])")
_RE_SEP = re.compile(r"^\|?[\s:\-|]+\|[\s:\-|]*$")
_RE_LI = re.compile(r"^([-*+]|\d+[.)])\s+(.*)$")
_RE_HR = re.compile(r"^(-{3,}|\*{3,}|_{3,})$")


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def md_inline(text: str) -> str:
    out = esc(text)
    stash: list[str] = []

    def hold(h: str) -> str:
        stash.append(h)
        return "\x00%d\x00" % (len(stash) - 1)

    out = _RE_CODE.sub(lambda m: hold("<code>" + m.group(1) + "</code>"), out)
    out = _RE_AUTOLINK.sub(
        lambda m: hold('<a href="%s" target="_blank" rel="noopener">%s</a>'
                       % (m.group(1), m.group(1))), out)

    def _link(m: re.Match) -> str:
        label, href = m.group(1), m.group(2)
        if href.startswith(("http://", "https://")):
            return hold('<a href="%s" target="_blank" rel="noopener">%s</a>'
                        % (href, label))
        # a repo-relative path: show it, do not make it a dead link
        return hold('<code title="%s">%s</code>' % (href, label or href))

    out = _RE_LINK.sub(_link, out)
    out = _RE_BOLD.sub(lambda m: "<strong>" + m.group(1) + "</strong>", out)
    out = _RE_ITAL.sub(lambda m: "<em>" + m.group(1) + "</em>", out)
    return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], out)


def _cells(row: str) -> list[str]:
    r = row.strip()
    if r.startswith("|"):
        r = r[1:]
    if r.endswith("|"):
        r = r[:-1]
    return [c.strip() for c in r.split("|")]


def _starts_block(line: str) -> bool:
    s = line.strip()
    return bool(s.startswith(("#", ">", "|", "```")) or _RE_LI.match(s)
                or _RE_HR.match(s))


def md_to_html(md: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        s = raw.strip()
        if not s:
            i += 1
            continue
        if s.startswith("```"):
            i += 1
            buf: list[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + esc("\n".join(buf)) + "</code></pre>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            lv = min(len(m.group(1)) + 1, 6)
            out.append("<h%d>%s</h%d>" % (lv, md_inline(m.group(2)), lv))
            i += 1
            continue
        if _RE_HR.match(s):
            out.append("<hr>")
            i += 1
            continue
        if s.startswith("|") and i + 1 < n and _RE_SEP.match(lines[i + 1].strip()):
            head = _cells(s)
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(_cells(lines[i].strip()))
                i += 1
            th = "".join("<th>%s</th>" % md_inline(c) for c in head)
            body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % md_inline(c)
                                                   for c in r) for r in rows)
            out.append("<div class=\"tw\"><table><thead><tr>%s</tr></thead>"
                       "<tbody>%s</tbody></table></div>" % (th, body))
            continue
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote>%s</blockquote>" % md_to_html("\n".join(buf)))
            continue
        m = _RE_LI.match(s)
        if m:
            ordered = m.group(1) not in ("-", "*", "+")
            items: list[list[str]] = []
            while i < n:
                cur = lines[i]
                cs = cur.strip()
                mm = _RE_LI.match(cs)
                if mm:
                    items.append([mm.group(2)])
                elif cs and items and (cur.startswith(" ") or cur.startswith("\t")):
                    items[-1].append(cs)
                elif not cs and i + 1 < n and _RE_LI.match(lines[i + 1].strip()):
                    pass  # blank line inside a loose list
                else:
                    break
                i += 1
            tag = "ol" if ordered else "ul"
            out.append("<%s>%s</%s>" % (tag, "".join(
                "<li>%s</li>" % md_inline(" ".join(it)) for it in items), tag))
            continue
        buf = [s]
        i += 1  # always consume, so a block test that disagrees cannot spin
        while i < n and lines[i].strip() and not _starts_block(lines[i]):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>%s</p>" % md_inline(" ".join(buf)))
    return "\n".join(out)


# ------------------------------------------------------------------- parser
class Slot:
    def __init__(self, sid: str, section_index: int, index_in_section: int,
                 line: int, facts_md: str, label: str, prompt_md: str):
        self.id = sid
        self.section_index = section_index
        self.index_in_section = index_in_section
        self.line = line                  # 0-based index into Template.lines
        self.facts_md = facts_md
        self.label = label
        self.prompt_md = prompt_md


class Section:
    def __init__(self, index: int, title: str, heading_line: int):
        self.index = index
        self.title = title
        self.heading_line = heading_line
        self.number = (NUM_RE.match(title).group(1) if NUM_RE.match(title) else "")
        self.is_exec = bool(EXEC_RE.search(title))
        self.slots: list[Slot] = []


class Template:
    def __init__(self, text: str, path: str = TEMPLATE_REL):
        self.path = path
        self.text = text
        self.lines = text.split("\n")
        self.sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.sections: list[Section] = []
        self.slots: list[Slot] = []
        self.unplaced: list[dict] = []
        self.style_rules: list[str] = []
        self.style_questions: list[str] = []
        self.exec_limit = DEFAULT_EXEC_LIMIT
        self._parse()

    # -- headings and slots ------------------------------------------------
    def _parse(self) -> None:
        fence = False
        cur: Section | None = None
        block_start = 0            # first line of the current facts block
        for idx, line in enumerate(self.lines):
            if line.strip().startswith("```"):
                fence = not fence
                continue
            if fence:
                continue
            m = H2_RE.match(line)
            if m:
                cur = Section(len(self.sections) + 1, m.group(1), idx)
                self.sections.append(cur)
                block_start = idx + 1
                continue
            if MARKER_RE.match(line):
                if cur is None:      # a slot before any heading: give it a home
                    cur = Section(len(self.sections) + 1, "(front matter)", 0)
                    self.sections.append(cur)
                facts = "\n".join(self.lines[block_start:idx]).strip("\n")
                sid = "s%02d-%02d" % (cur.index, len(cur.slots) + 1)
                slot = Slot(sid, cur.index, len(cur.slots) + 1, idx, facts,
                            _label_of(facts, cur.title), _prompt_of(facts))
                cur.slots.append(slot)
                self.slots.append(slot)
                block_start = idx + 1
                continue
            if MENTION_RE.search(line):
                self.unplaced.append({
                    "line": idx + 1,
                    "text": line.strip(),
                    "kind": ("blockquote variant" if line.lstrip().startswith(">")
                             else "prose mention"),
                    "section": cur.title if cur else "(front matter)"})
        self._parse_style()
        self._parse_limit()

    def _parse_style(self) -> None:
        sec = next((s for s in self.sections
                    if s.title.upper().startswith("STYLE RULES")), None)
        if sec is None:
            return
        end = _section_end(self, sec)
        body = self.lines[sec.heading_line + 1:end]
        # the seven rules: the ordered list, continuation lines folded in
        rules: list[list[str]] = []
        in_list = False
        for line in body:
            s = line.strip()
            m = re.match(r"^\d+\.\s+(.*)$", s)
            if m:
                rules.append([m.group(1)])
                in_list = True
            elif in_list and s and (line.startswith(" ") or line.startswith("\t")):
                rules[-1].append(s)
            elif not s:
                continue
            else:
                in_list = False
        self.style_rules = [md_inline(" ".join(r)) for r in rules]
        # the three self-check questions: the bullets under the line that names them
        qs: list[str] = []
        seen = False
        for line in body:
            s = line.strip()
            if "self-check questions" in s.lower():
                seen = True
                continue
            if not seen:
                continue
            # a bullet is a marker FOLLOWED BY SPACE; `**bold**` and `---` are not
            if re.match(r"^[-*+]\s+", s):
                qs.append(md_inline(re.sub(r"^[-*+]\s+", "", s)))
            elif qs and s and not s.startswith(">"):
                break
        self.style_questions = qs

    def _parse_limit(self) -> None:
        sec = self.exec_section()
        bodies = []
        if sec is not None:
            bodies.append("\n".join(self.lines[sec.heading_line:
                                               _section_end(self, sec)]))
        bodies.append(self.text)
        for b in bodies:
            m = LIMIT_RE.search(b)
            if m:
                self.exec_limit = int(m.group(1))
                return

    # -- lookups -----------------------------------------------------------
    def exec_section(self) -> Section | None:
        return next((s for s in self.sections if s.is_exec), None)

    def section(self, index: int) -> Section | None:
        return next((s for s in self.sections if s.index == index), None)

    def slot(self, sid: str) -> Slot | None:
        return next((s for s in self.slots if s.id == sid), None)


def _section_end(tpl: Template, sec: Section) -> int:
    later = [s.heading_line for s in tpl.sections if s.heading_line > sec.heading_line]
    return min(later) if later else len(tpl.lines)


def _label_of(facts_md: str, fallback: str) -> str:
    """The nearest ### heading above the slot, else the section title."""
    for line in reversed(facts_md.split("\n")):
        m = SUBH_RE.match(line.strip())
        if m:
            return re.sub(r"[*`]", "", m.group(2))
    return fallback


def _prompt_of(facts_md: str) -> str:
    """The instruction line immediately above the slot, when there is one.

    Most slots are introduced by a short bold line ("**Your title:**"). When the last
    thing above the marker is a table row or a heading there is no instruction, and
    repeating it under the facts panel would just be noise.
    """
    for line in reversed(facts_md.split("\n")):
        s = line.strip()
        if not s:
            continue
        if s.startswith(("|", "#", ">")) or _RE_HR.match(s):
            return ""
        return s
    return ""


def load_template(repo: Path, rel: str = TEMPLATE_REL) -> Template:
    p = repo / rel
    return Template(read_text(p), rel)


# ------------------------------------------------------------------ storage
def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def word_count(text: str) -> int:
    return len(text.split())


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    os.replace(tmp, path)


def load_answers(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return d if isinstance(d, dict) else {}


def regenerate_draft(tpl: Template, answers: dict) -> str:
    """The template with every answered marker replaced by Ebin's text.

    An unanswered slot keeps its `> [Ebin writes]` line, so DRAFT.md is always a
    readable document AND always shows what is still missing.
    """
    by_line = {s.line: s for s in tpl.slots}
    out: list[str] = []
    for idx, line in enumerate(tpl.lines):
        slot = by_line.get(idx)
        if slot is None:
            out.append(line)
            continue
        text = (answers.get(slot.id) or {}).get("text", "")
        if text.strip():
            out.extend(text.rstrip("\n").split("\n"))
        else:
            out.append(line)
    return "\n".join(out)


class Store:
    """Answers + draft + history. Every save appends before it rewrites."""

    def __init__(self, repo: Path, tpl: Template, answers_rel: str = ANSWERS_REL,
                 draft_rel: str = DRAFT_REL, history_rel: str = HISTORY_REL):
        self.repo = repo
        self.tpl = tpl
        self.answers_path = repo / answers_rel
        self.draft_path = repo / draft_rel
        self.history_path = repo / history_rel
        self.lock = threading.Lock()
        self.answers = load_answers(self.answers_path)

    def filled(self, sid: str) -> bool:
        return bool((self.answers.get(sid) or {}).get("text", "").strip())

    def section_words(self, index: int) -> int:
        sec = self.tpl.section(index)
        if sec is None:
            return 0
        return sum((self.answers.get(s.id) or {}).get("word_count", 0)
                   for s in sec.slots)

    def save(self, sid: str, text: str) -> dict:
        slot = self.tpl.slot(sid)
        if slot is None:
            raise KeyError(sid)
        row = {"text": text, "updated_utc": now_utc(), "word_count": word_count(text)}
        with self.lock:
            # append-only history FIRST: if anything below fails, the text survives
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with self.history_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"slot_id": sid, "template_sha256": self.tpl.sha256,
                                     **row}, ensure_ascii=False) + "\n")
                fh.flush()
            self.answers[sid] = row
            # template order first; any key the current template no longer names is
            # kept anyway - this file is not allowed to drop text it once held
            known = {s.id for s in self.tpl.slots}
            ordered = {s.id: self.answers[s.id] for s in self.tpl.slots
                       if s.id in self.answers}
            ordered.update({k: v for k, v in self.answers.items() if k not in known})
            atomic_write(self.answers_path,
                         json.dumps(ordered, ensure_ascii=False, indent=2) + "\n")
            atomic_write(self.draft_path, regenerate_draft(self.tpl, self.answers))
        return row


# --------------------------------------------------------------- exec lock
def exec_lock_state(tpl: Template, store: Store) -> dict:
    """Section 2 is soft-locked while any other slot is still empty.

    Soft: the page shows a banner and needs one confirm click. Nothing is refused -
    the +2h rule is Ebin's to break, not a script's to enforce.
    """
    sec = tpl.exec_section()
    if sec is None:
        return {"section_index": None, "locked": False, "others_unfilled": 0,
                "limit": tpl.exec_limit}
    others = [s for s in tpl.slots if s.section_index != sec.index]
    n = sum(1 for s in others if not store.filled(s.id))
    return {"section_index": sec.index, "locked": n > 0, "others_unfilled": n,
            "limit": tpl.exec_limit}


# ------------------------------------------------------------------ export
def facts_summary(facts_md: str) -> str:
    lines = [l.strip() for l in facts_md.split("\n") if l.strip()]
    pipes = [l for l in lines if l.startswith("|")]
    seps = [l for l in pipes if _RE_SEP.match(l)]
    rows = max(len(pipes) - 2 * len(seps), 0)
    bullets = sum(1 for l in lines if _RE_LI.match(l))
    first = ""
    for l in lines:
        if l.startswith(("|", "#")) or _RE_HR.match(l):
            continue
        first = re.sub(r"[*`>]", "", l).strip()
        if first:
            break
    bits = []
    if rows:
        bits.append("%d table row%s" % (rows, "" if rows == 1 else "s"))
    if bullets:
        bits.append("%d bullet%s" % (bullets, "" if bullets == 1 else "s"))
    if len(first) > 140:
        first = first[:137] + "..."
    tail = (" (" + ", ".join(bits) + ")") if bits else ""
    return (first or "(no prose above this slot)") + tail


def export_section(tpl: Template, store: Store, index: int) -> str:
    sec = tpl.section(index)
    if sec is None:
        raise KeyError(index)
    filled = sum(1 for s in sec.slots if store.filled(s.id))
    out = [
        "SECTION %d — %s" % (sec.index, sec.title),
        "%s · %d slot%s · %d filled · exported %s"
        % (tpl.path, len(sec.slots), "" if len(sec.slots) == 1 else "s", filled,
           now_utc()),
        "",
    ]
    for s in sec.slots:
        row = store.answers.get(s.id) or {}
        text = row.get("text", "").strip()
        out.append("[%s] %s" % (s.id, s.label))
        out.append("facts: " + facts_summary(s.facts_md))
        out.append("words: %d" % word_count(text))
        out.append("-" * 66)
        out.append(text if text else "(empty — still [Ebin writes])")
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------- journey
_STOP = {"the", "a", "an", "and", "or", "of", "in", "to", "for", "that", "this",
         "is", "are", "was", "were", "by", "with", "on", "at", "it", "its", "as",
         "not", "no", "one", "two", "three", "each", "more", "than", "write",
         "read", "before", "after", "last", "first", "place", "immediately",
         "single", "sentence", "paragraph", "table", "line", "plus", "own",
         "what", "which", "how", "why", "who", "any", "all", "must", "should"}
# Bridges between the template's vocabulary and the journey's. Keyword in the
# template heading -> extra tokens to look for in a journey heading. A mapping aid;
# it contains no prose and nothing that could reach the write-up.
_ALIAS = {
    "title": ["question", "answer"],
    "executive": ["answer", "interpretation", "findings"],
    "summary": ["answer", "interpretation"],
    "examples": ["ledger", "grade"],
    "methods": ["instrument", "grading", "metrics", "sealing", "blinding",
                "conditions", "base", "loras"],
    "finding": ["decomposition", "detection", "null", "refusal", "interpretation"],
    "recipe": ["decomposition", "detection", "coverage"],
    "auditor": ["refusal", "null", "identical"],
    "secondary": ["exploratory", "drift", "introspection", "predictions", "l4v3"],
    "limitations": ["limitations", "deviations"],
    "verified": ["agreement", "grade", "ledger"],
    "deviations": ["deviations"],
    "disagreement": ["disagreement", "agreement", "ledger"],
    "labour": ["journey", "day"],
    "hours": ["hours"],
    "steps": ["forward", "future"],
    "next": ["forward", "future"],
    "credits": ["journey"],
    "links": ["read", "glossary"],
    "checklist": ["read", "glossary"],
}


_DAY_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d")


def _tokens(title: str) -> set[str]:
    raw = re.findall(r"[a-z0-9]+", title.lower())
    toks = {t for t in raw if len(t) > 2 and t not in _STOP and not t.isdigit()}
    extra: set[str] = set()
    for k, v in _ALIAS.items():
        if k in toks:
            extra.update(v)
    return toks | extra


def journey_blocks(md: str) -> list[dict]:
    """Fence-aware split of PROJECT_JOURNEY.md into ## / ### blocks."""
    lines = md.split("\n")
    blocks: list[dict] = []
    fence = False
    for idx, line in enumerate(lines):
        if line.strip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        m = re.match(r"^(#{2,3})\s+(.*?)\s*$", line)
        if m:
            blocks.append({"level": len(m.group(1)), "title": m.group(2),
                           "start": idx, "end": len(lines)})
    for i in range(len(blocks) - 1):
        blocks[i]["end"] = blocks[i + 1]["start"]
    for b in blocks:
        b["md"] = "\n".join(lines[b["start"]:b["end"]])
    return blocks


def map_journey(section_title: str, blocks: list[dict], limit: int = 5) -> list[int]:
    want = _tokens(section_title)
    if not want:
        return []
    scored: list[tuple[int, int]] = []
    for i, b in enumerate(blocks):
        have = set(re.findall(r"[a-z0-9]+", b["title"].lower()))
        score = len(want & have)
        # the day-by-day journal headings share a lot of vocabulary with every
        # findings section; make them earn their place rather than crowd it out.
        # They still arrive as children when their parent heading matches.
        if _DAY_RE.match(b["title"]):
            score -= 1
        if score > 0:
            scored.append((score, i))
    scored.sort(key=lambda t: (-t[0], t[1]))
    picked: list[int] = []
    for _, i in scored:
        if blocks[i]["level"] == 2:
            # a top-level hit brings its children, which is where the numbers are
            picked.append(i)
            j = i + 1
            while j < len(blocks) and blocks[j]["level"] > 2:
                picked.append(j)
                j += 1
        else:
            picked.append(i)
        if len(picked) >= limit:
            break
    seen: set[int] = set()
    return [i for i in picked if not (i in seen or seen.add(i))][:limit]


# ------------------------------------------------------------------ server
class Cache:
    def __init__(self) -> None:
        self.data: dict[str, tuple[float, str]] = {}

    def html(self, path: Path) -> str:
        key = str(path)
        mtime = path.stat().st_mtime
        hit = self.data.get(key)
        if hit and hit[0] == mtime:
            return hit[1]
        html = md_to_html(read_text(path))
        self.data[key] = (mtime, html)
        return html


def index_payload(tpl: Template, store: Store) -> dict:
    lock = exec_lock_state(tpl, store)
    return {
        "template": tpl.path,
        "template_sha256": tpl.sha256,
        "sections": [{"index": s.index, "number": s.number, "title": s.title,
                      "n_slots": len(s.slots),
                      "n_filled": sum(1 for x in s.slots if store.filled(x.id)),
                      "is_exec": s.is_exec} for s in tpl.sections],
        "slots": [{"id": s.id, "section_index": s.section_index, "label": s.label,
                   "filled": store.filled(s.id),
                   "word_count": (store.answers.get(s.id) or {}).get("word_count", 0)}
                  for s in tpl.slots],
        "totals": {"slots": len(tpl.slots),
                   "filled": sum(1 for s in tpl.slots if store.filled(s.id)),
                   "sections": len(tpl.sections)},
        "style": {"rules": tpl.style_rules, "questions": tpl.style_questions},
        "references": [{"name": n, "title": t} for n, t, _ in REFERENCES],
        "exec_lock": lock,
        "unplaced": tpl.unplaced,
    }


def slot_payload(tpl: Template, store: Store, sid: str) -> dict:
    slot = tpl.slot(sid)
    if slot is None:
        raise KeyError(sid)
    sec = tpl.section(slot.section_index)
    row = store.answers.get(sid) or {}
    pos = tpl.slots.index(slot)
    return {
        "id": slot.id,
        "section_index": slot.section_index,
        "section_title": sec.title if sec else "",
        "section_slots": len(sec.slots) if sec else 0,
        "index_in_section": slot.index_in_section,
        "label": slot.label,
        "template_line": slot.line + 1,
        "facts_html": md_to_html(slot.facts_md),
        "prompt_html": md_inline(slot.prompt_md) if slot.prompt_md else "",
        "text": row.get("text", ""),
        "word_count": row.get("word_count", 0),
        "updated_utc": row.get("updated_utc", ""),
        "section_words": store.section_words(slot.section_index),
        "is_exec": bool(sec and sec.is_exec),
        "exec_limit": tpl.exec_limit,
        "exec_lock": exec_lock_state(tpl, store),
        "prev": tpl.slots[pos - 1].id if pos > 0 else None,
        "next": tpl.slots[pos + 1].id if pos + 1 < len(tpl.slots) else None,
    }


def reference_payload(repo: Path, tpl: Template, cache: Cache, tab: str,
                      slot_id: str = "") -> dict:
    entry = next((e for e in REFERENCES if e[0] == tab), None)
    if entry is None:
        raise KeyError(tab)
    name, title, rel = entry
    if name == "figures":
        return {"name": name, "title": title, "path": "results/figures/",
                "note": "the two committed figures; no other file under results/ is "
                        "served by this page",
                "html": "".join(
                    '<h3>%s</h3><img src="/figures/%s" alt="%s">' % (f, f, f)
                    for f in sorted(FIGURES))}
    path = repo / rel
    if not path.exists():
        return {"name": name, "title": title, "path": rel, "html": "",
                "note": "missing: " + rel}
    if name == "journey":
        blocks = journey_blocks(read_text(path))
        sec = None
        slot = tpl.slot(slot_id) if slot_id else None
        if slot is not None:
            sec = tpl.section(slot.section_index)
        picked = map_journey(sec.title, blocks) if sec else []
        if picked:
            html = "".join(md_to_html(blocks[i]["md"]) for i in picked)
            note = ("%s -> %s" % (sec.title, "; ".join(blocks[i]["title"]
                                                       for i in picked)))
            return {"name": name, "title": title, "path": rel, "html": html,
                    "note": note}
        return {"name": name, "title": title, "path": rel,
                "note": "no journey heading matched this section — full file, use "
                        "the search box",
                "html": cache.html(path)}
    return {"name": name, "title": title, "path": rel, "note": rel,
            "html": cache.html(path)}


def figure_path(repo: Path, name: str) -> Path | None:
    """The static allow-list. Exactly two names resolve; everything else is None."""
    rel = FIGURES.get(name)
    if rel is None:
        return None
    p = (repo / rel).resolve()
    if not p.is_file():
        return None
    return p


def make_handler(repo: Path, tpl: Template, store: Store):
    from writeup_fill_ui import PAGE  # noqa: PLC0415 - keeps the page out of import time

    cache = Cache()

    class H(BaseHTTPRequestHandler):
        server_version = "writeup_fill/1"

        def log_message(self, *a):  # quiet
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False))

        def do_GET(self):  # noqa: N802
            u = urlparse(self.path)
            path, qs = u.path, parse_qs(u.query)
            try:
                if path == "/":
                    return self._send(200, PAGE, "text/html; charset=utf-8")
                if path == "/api/index":
                    return self._json(index_payload(tpl, store))
                if path.startswith("/api/slot/"):
                    sid = path[len("/api/slot/"):]
                    try:
                        return self._json(slot_payload(tpl, store, sid))
                    except KeyError:
                        return self._json({"error": "unknown slot"}, 404)
                if path == "/api/reference":
                    tab = (qs.get("tab") or [""])[0]
                    try:
                        return self._json(reference_payload(
                            repo, tpl, cache, tab, (qs.get("slot") or [""])[0]))
                    except KeyError:
                        return self._json({"error": "unknown tab"}, 404)
                if path == "/api/export":
                    try:
                        n = int((qs.get("section") or ["0"])[0])
                        return self._json({"text": export_section(tpl, store, n)})
                    except (KeyError, ValueError):
                        return self._json({"error": "unknown section"}, 404)
                if path.startswith("/figures/"):
                    p = figure_path(repo, path[len("/figures/"):])
                    if p is None:
                        return self._json({"error": "not served"}, 404)
                    return self._send(200, p.read_bytes(), "image/png")
                return self._json({"error": "not found"}, 404)
            except Exception as e:  # noqa: BLE001
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

        def do_POST(self):  # noqa: N802
            if urlparse(self.path).path != "/api/save":
                return self._json({"error": "not found"}, 404)
            try:
                n = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(n).decode("utf-8"))
                sid = body.get("slot_id", "")
                text = body.get("text", "")
                if not isinstance(text, str):
                    return self._json({"error": "text must be a string"}, 400)
                try:
                    row = store.save(sid, text)
                except KeyError:
                    return self._json({"error": "unknown slot"}, 400)
                idx = index_payload(tpl, store)
                return self._json({
                    "ok": True, "slot": row,
                    "sections": idx["sections"], "slots": idx["slots"],
                    "totals": idx["totals"], "exec_lock": idx["exec_lock"],
                    "section_words": store.section_words(
                        tpl.slot(sid).section_index)})
            except Exception as e:  # noqa: BLE001
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    return H


# --------------------------------------------------------------------- CLI
def _rel(p: Path, root: Path) -> str:
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        return p.as_posix()


def print_status(tpl: Template, store: Store) -> None:
    print(f"{tpl.path}  sha256 {tpl.sha256[:12]}")
    print(f"answers  {_rel(store.answers_path, store.repo)}"
          f"   draft  {_rel(store.draft_path, store.repo)}")
    print()
    print(f"{'sec':4} {'section':52} {'filled':>7}")
    print("-" * 68)
    for s in tpl.sections:
        if not s.slots:
            print(f"s{s.index:02d}  {s.title:52.52} {'—':>7}")
            continue
        f = sum(1 for x in s.slots if store.filled(x.id))
        print(f"s{s.index:02d}  {s.title:52.52} {f:>3}/{len(s.slots):<3}")
        empty = [x.id for x in s.slots if not store.filled(x.id)]
        if empty:
            print(f"      unfilled: {' '.join(empty)}")
    print("-" * 68)
    total = len(tpl.slots)
    filled = sum(1 for s in tpl.slots if store.filled(s.id))
    print(f"{filled}/{total} slots filled, {total - filled} to go")
    lock = exec_lock_state(tpl, store)
    if lock["section_index"]:
        print(f"exec summary (s{lock['section_index']:02d}): "
              f"{'LOCKED' if lock['locked'] else 'open'}, "
              f"{lock['others_unfilled']} other slots empty, "
              f"limit {lock['limit']} words, "
              f"currently {store.section_words(lock['section_index'])}")
    if tpl.unplaced:
        print("\nnot placed as slots (reported, never silently dropped):")
        for u in tpl.unplaced:
            print(f"  line {u['line']:>4}  [{u['kind']}]  {u['text'][:70]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]),
                    help="repository root (default: the parent of scripts/)")
    ap.add_argument("--template", default=TEMPLATE_REL)
    ap.add_argument("--answers", default=ANSWERS_REL)
    ap.add_argument("--draft", default=DRAFT_REL)
    ap.add_argument("--history", default=HISTORY_REL)
    ap.add_argument("--status", action="store_true",
                    help="print filled/unfilled per section and exit")
    ap.add_argument("--export-section", type=int, metavar="N",
                    help="print 'slot id + facts summary + text' for section N")
    ap.add_argument("--regenerate", action="store_true",
                    help="rewrite DRAFT.md from the answers file and exit")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    tpl = load_template(repo, args.template)
    store = Store(repo, tpl, args.answers, args.draft, args.history)

    if args.status:
        print_status(tpl, store)
        return 0
    if args.export_section is not None:
        try:
            print(export_section(tpl, store, args.export_section))
        except KeyError:
            print(f"no section {args.export_section}; sections are 1..{len(tpl.sections)}")
            return 1
        return 0
    if args.regenerate:
        atomic_write(store.draft_path, regenerate_draft(tpl, store.answers))
        print(f"wrote {args.draft}")
        return 0

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(repo, tpl, store))
    url = f"http://127.0.0.1:{args.port}"
    filled = sum(1 for s in tpl.slots if store.filled(s.id))
    print(f"write-up fill-in: {url}")
    print(f"  {len(tpl.slots)} slots across {len(tpl.sections)} sections, "
          f"{filled} filled")
    print(f"  answers -> {args.answers}   draft -> {args.draft}")
    print("  no draft prose, no model calls, no outbound network. Ctrl-C to stop.")
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
