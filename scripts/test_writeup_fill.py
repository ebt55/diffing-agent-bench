#!/usr/bin/env python3
"""Tests for scripts/writeup_fill.py. Synthetic template in a temp dir, no network.

Nothing here reads data/sealed/, nothing makes a model call, and every fixture is
written by the test itself except the one check that the COMMITTED template still
parses to 42 slots.
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import writeup_fill as wf  # noqa: E402

REPO = _HERE.parent

TEMPLATE = """# Synthetic template

Every slot is empty and marked `> [Ebin writes]` — this line is a prose mention.

---

## STYLE RULES — read before writing a single sentence

1. **rule one.** first rule body
   wrapped onto a second line.
2. **rule two.** second rule body.
3. **rule three.** third rule body.

**The three self-check questions** — ask these of every paragraph before it stays:

- *question one?*
- *question two?*
- *question three?*

**Other constraint:** the exec summary is capped.

---

## 1. Title

Pick one of the candidates.

**Your title:**

> [Ebin writes]

---

## 2. Executive summary — WRITE THIS LAST

### Slot 1 — problem and instrument

| fact | value | source |
|---|---|---|
| base | **X** | `a.json` |
| ladder | 5 LoRAs | `b.json` |

> [Ebin writes]

### Slot 2 — the finding

Facts available for the second slot.

- one bullet
- two bullet

> [Ebin writes]

**Word count check:** ≤120 words across both slots.

> Words used: [Ebin writes]

---

## 3. Methods — the seven questions

Facts about methods, with a [link](https://example.invalid/m) and `code`.

> [Ebin writes]

---

## 4. Links

- **Repo:** <https://example.invalid/x>

> [Ebin writes — any additional links]
"""

JOURNEY = """# Journey

## 0. Where to begin

pointer body

## 3. Methods and the instrument

instrument body

### Grading and the judge

grading body

## 9. Something unrelated

body
"""


def make_repo(tmp: Path) -> Path:
    (tmp / "writeup").mkdir(parents=True, exist_ok=True)
    (tmp / "results" / "analysis").mkdir(parents=True, exist_ok=True)
    (tmp / "results" / "figures").mkdir(parents=True, exist_ok=True)
    (tmp / "writeup" / "WRITEUP_TEMPLATE.md").write_text(TEMPLATE, encoding="utf-8")
    (tmp / "writeup" / "PROJECT_JOURNEY.md").write_text(JOURNEY, encoding="utf-8")
    (tmp / "results" / "analysis" / "tables.md").write_text(
        "# tables\n\n| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    (tmp / "DECISIONS.md").write_text(
        "# Decision log\n\n| # | Date | Decision |\n|---|---|---|\n"
        "| 1 | Aug 30 | first |\n| 42 | Sep 3 | last |\n", encoding="utf-8")
    # not real PNGs; the route only has to prove which paths it will serve
    (tmp / "results" / "figures" / "main_figure.png").write_bytes(b"\x89PNG-main")
    (tmp / "results" / "figures" / "coverage_figure.png").write_bytes(b"\x89PNG-cov")
    (tmp / "results" / "figures" / "secret_figure.png").write_bytes(b"\x89PNG-no")
    return tmp


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = make_repo(Path(self._tmp.name))
        self.tpl = wf.load_template(self.repo)
        self.store = wf.Store(self.repo, self.tpl)

    def tearDown(self) -> None:
        self._tmp.cleanup()


# ------------------------------------------------------------------ parser
class TestParser(Fixture):
    def test_slot_count_and_order(self):
        self.assertEqual(len(self.tpl.slots), 5)
        self.assertEqual([s.id for s in self.tpl.slots],
                         ["s02-01", "s03-01", "s03-02", "s04-01", "s05-01"])
        # template order preserved: line numbers strictly increase
        lines = [s.line for s in self.tpl.slots]
        self.assertEqual(lines, sorted(lines))

    def test_sections_and_counts(self):
        titles = [s.title for s in self.tpl.sections]
        self.assertEqual(len(titles), 5)
        self.assertTrue(titles[0].startswith("STYLE RULES"))
        counts = {s.index: len(s.slots) for s in self.tpl.sections}
        self.assertEqual(counts, {1: 0, 2: 1, 3: 2, 4: 1, 5: 1})

    def test_facts_are_the_block_above_the_marker(self):
        s = self.tpl.slot("s03-01")
        self.assertIn("| base | **X** | `a.json` |", s.facts_md)
        self.assertNotIn("Facts available for the second slot", s.facts_md)
        # the second slot's facts start after the first marker, not at the heading
        s2 = self.tpl.slot("s03-02")
        self.assertIn("Facts available for the second slot", s2.facts_md)
        self.assertNotIn("| base |", s2.facts_md)

    def test_labels_come_from_the_nearest_subheading(self):
        self.assertEqual(self.tpl.slot("s03-01").label, "Slot 1 — problem and instrument")
        self.assertEqual(self.tpl.slot("s03-02").label, "Slot 2 — the finding")
        self.assertEqual(self.tpl.slot("s02-01").label, "1. Title")

    def test_unplaced_markers_are_reported_not_dropped(self):
        kinds = {u["kind"] for u in self.tpl.unplaced}
        texts = [u["text"] for u in self.tpl.unplaced]
        self.assertEqual(len(self.tpl.unplaced), 2)
        self.assertEqual(kinds, {"prose mention", "blockquote variant"})
        self.assertTrue(any(t.startswith("> Words used:") for t in texts))

    def test_style_rules_and_questions_come_from_the_file(self):
        self.assertEqual(len(self.tpl.style_rules), 3)
        self.assertIn("first rule body wrapped onto a second line", self.tpl.style_rules[0])
        self.assertIn("<strong>rule one.</strong>", self.tpl.style_rules[0])
        self.assertEqual(len(self.tpl.style_questions), 3)
        self.assertIn("question two?", self.tpl.style_questions[1])

    def test_exec_word_limit_read_from_the_template(self):
        self.assertEqual(self.tpl.exec_limit, 120)
        self.assertEqual(self.tpl.exec_section().index, 3)

    def test_committed_template_has_42_slots(self):
        p = REPO / wf.TEMPLATE_REL
        if not p.exists():
            self.skipTest("committed template not present")
        tpl = wf.load_template(REPO)
        independent = sum(1 for line in p.read_text(encoding="utf-8").split("\n")
                          if wf.MARKER_RE.match(line))
        self.assertEqual(len(tpl.slots), independent)
        self.assertEqual(len(tpl.slots), 42,
                         "the committed WRITEUP_TEMPLATE.md is expected to hold 42 "
                         "slots; if it legitimately changed, update this number")


# ------------------------------------------------------------------ storage
class TestStorage(Fixture):
    def test_save_regenerate_round_trip(self):
        self.store.save("s02-01", "A title I typed.")
        self.store.save("s04-01", "Methods, two sentences.\nSecond line.")
        draft = (self.repo / wf.DRAFT_REL).read_text(encoding="utf-8")
        self.assertIn("A title I typed.", draft)
        self.assertIn("Methods, two sentences.\nSecond line.", draft)
        # unanswered slots keep their marker, so the draft still shows what is missing
        markers = [l for l in draft.split("\n") if l == "> [Ebin writes]"]
        self.assertEqual(len(markers), 2)
        self.assertIn("> [Ebin writes — any additional links]", draft)
        # the template's own text is untouched around the slots
        self.assertIn("## 2. Executive summary — WRITE THIS LAST", draft)
        self.assertEqual(len(draft.split("\n")), len(self.tpl.lines) + 1)

    def test_answers_file_shape(self):
        self.store.save("s03-01", "two words here")
        data = json.loads((self.repo / wf.ANSWERS_REL).read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"s03-01"})
        row = data["s03-01"]
        self.assertEqual(set(row), {"text", "updated_utc", "word_count"})
        self.assertEqual(row["word_count"], 3)
        self.assertTrue(row["updated_utc"].endswith("Z"))

    def test_saves_are_atomic_and_leave_no_temp_file(self):
        self.store.save("s02-01", "x")
        leftovers = list((self.repo / "writeup").glob("*.tmp"))
        self.assertEqual(leftovers, [])

    def test_history_is_append_only(self):
        self.store.save("s02-01", "first version")
        self.store.save("s02-01", "second version")
        self.store.save("s02-01", "")
        lines = [json.loads(l) for l in
                 (self.repo / wf.HISTORY_REL).read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        self.assertEqual(len(lines), 3)
        self.assertEqual([l["text"] for l in lines],
                         ["first version", "second version", ""])
        self.assertTrue(all(l["slot_id"] == "s02-01" for l in lines))
        self.assertTrue(all(l["template_sha256"] == self.tpl.sha256 for l in lines))
        # the cleared text is still recoverable from history
        self.assertFalse(self.store.filled("s02-01"))

    def test_unknown_keys_survive_a_save(self):
        (self.repo / wf.ANSWERS_REL).write_text(
            json.dumps({"s99-99": {"text": "from an older template",
                                   "updated_utc": "2026-01-01T00:00:00Z",
                                   "word_count": 4}}), encoding="utf-8")
        store = wf.Store(self.repo, self.tpl)
        store.save("s02-01", "new")
        data = json.loads((self.repo / wf.ANSWERS_REL).read_text(encoding="utf-8"))
        self.assertIn("s99-99", data)
        self.assertIn("s02-01", data)


# ---------------------------------------------------------------- exec lock
class TestExecLock(Fixture):
    def test_locked_while_other_slots_are_empty(self):
        st = wf.exec_lock_state(self.tpl, self.store)
        self.assertTrue(st["locked"])
        self.assertEqual(st["section_index"], 3)
        self.assertEqual(st["others_unfilled"], 3)   # title, methods, links
        self.assertEqual(st["limit"], 120)

    def test_exec_slots_do_not_unlock_themselves(self):
        self.store.save("s03-01", "exec text")
        self.store.save("s03-02", "exec text")
        st = wf.exec_lock_state(self.tpl, self.store)
        self.assertTrue(st["locked"])
        self.assertEqual(st["others_unfilled"], 3)

    def test_unlocks_when_every_other_slot_is_filled(self):
        for sid in ("s02-01", "s04-01", "s05-01"):
            self.store.save(sid, "done")
        st = wf.exec_lock_state(self.tpl, self.store)
        self.assertFalse(st["locked"])
        self.assertEqual(st["others_unfilled"], 0)

    def test_title_slot_is_never_gated(self):
        # the title lives outside the exec section, so nothing gates it
        payload = wf.slot_payload(self.tpl, self.store, "s02-01")
        self.assertFalse(payload["is_exec"])

    def test_section_word_total_tracks_the_limit(self):
        self.store.save("s03-01", " ".join(["w"] * 70))
        self.store.save("s03-02", " ".join(["w"] * 70))
        self.assertEqual(self.store.section_words(3), 140)
        self.assertGreater(self.store.section_words(3), self.tpl.exec_limit)


# ------------------------------------------------------------------ export
class TestExport(Fixture):
    def test_export_section_has_ids_facts_and_text(self):
        self.store.save("s03-01", "My sentence about the base model.")
        out = wf.export_section(self.tpl, self.store, 3)
        self.assertIn("SECTION 3 — 2. Executive summary — WRITE THIS LAST", out)
        self.assertIn("[s03-01] Slot 1 — problem and instrument", out)
        self.assertIn("[s03-02] Slot 2 — the finding", out)
        self.assertIn("My sentence about the base model.", out)
        self.assertIn("(empty — still [Ebin writes])", out)
        self.assertIn("facts:", out)
        self.assertIn("table row", out)   # the facts summary counts the table

    def test_export_unknown_section_raises(self):
        with self.assertRaises(KeyError):
            wf.export_section(self.tpl, self.store, 99)


# ------------------------------------------------------------- markdown-lite
class TestMarkdown(unittest.TestCase):
    def test_table_bold_code_list_link(self):
        html = wf.md_to_html(
            "### head\n\n"
            "| a | b |\n|---|---|\n| 1 | **2** |\n\n"
            "- one `x`\n- two\n\n"
            "text with [label](https://example.invalid/z) and *stress*.\n")
        self.assertIn("<h4>head</h4>", html)
        self.assertIn("<table>", html)
        self.assertIn("<th>a</th>", html)
        self.assertIn("<td><strong>2</strong></td>", html)
        self.assertIn("<li>one <code>x</code></li>", html)
        self.assertIn('href="https://example.invalid/z"', html)
        self.assertIn("<em>stress</em>", html)

    def test_relative_links_are_not_anchors(self):
        html = wf.md_to_html("see [the plan](../notes/plan.md) for detail\n")
        self.assertNotIn("<a ", html)
        self.assertIn("<code", html)

    def test_html_in_source_is_escaped(self):
        html = wf.md_to_html("a <script>alert(1)</script> b\n")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_renderer_terminates_on_odd_input(self):
        # a pipe line with no separator row is not a table; it must not spin
        self.assertIn("<p>", wf.md_to_html("| dangling | row |\n"))


# ----------------------------------------------------------------- journey
class TestJourneyMapping(Fixture):
    def test_maps_by_heading_keyword_and_pulls_children(self):
        blocks = wf.journey_blocks(
            (self.repo / wf.JOURNEY_REL).read_text(encoding="utf-8"))
        picked = wf.map_journey("4. Methods — the seven questions", blocks)
        titles = [blocks[i]["title"] for i in picked]
        self.assertIn("3. Methods and the instrument", titles)
        self.assertIn("Grading and the judge", titles)
        self.assertNotIn("9. Something unrelated", titles)

    def test_falls_back_to_the_full_file(self):
        cache = wf.Cache()
        d = wf.reference_payload(self.repo, self.tpl, cache, "journey", "s05-01")
        self.assertIn("no journey heading matched", d["note"])
        self.assertIn("Something unrelated", d["html"])

    def test_missing_reference_file_is_reported_not_raised(self):
        (self.repo / "results" / "analysis" / "tables.md").unlink()
        d = wf.reference_payload(self.repo, self.tpl, wf.Cache(), "tables")
        self.assertIn("missing", d["note"])
        self.assertEqual(d["html"], "")


# ------------------------------------------------------------ static route
class TestServer(Fixture):
    def setUp(self) -> None:
        super().setUp()
        handler = wf.make_handler(self.repo, self.tpl, self.store)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.port = self.srv.server_address[1]
        self.thread = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(timeout=5)
        super().tearDown()

    def get(self, path: str):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Content-Type", "")

    def test_page_and_index(self):
        code, body, ctype = self.get("/")
        self.assertEqual(code, 200)
        self.assertIn("text/html", ctype)
        code, body, _ = self.get("/api/index")
        self.assertEqual(code, 200)
        d = json.loads(body)
        self.assertEqual(d["totals"]["slots"], 5)
        self.assertEqual(d["totals"]["filled"], 0)
        self.assertEqual(len(d["style"]["rules"]), 3)
        self.assertEqual(len(d["unplaced"]), 2)

    def test_slot_endpoint(self):
        code, body, _ = self.get("/api/slot/s03-01")
        self.assertEqual(code, 200)
        d = json.loads(body)
        self.assertTrue(d["is_exec"])
        self.assertIn("<table>", d["facts_html"])
        self.assertEqual(d["prev"], "s02-01")
        self.assertEqual(d["next"], "s03-02")
        self.assertEqual(self.get("/api/slot/s99-99")[0], 404)

    def test_serves_only_the_two_figures(self):
        for name, expect in (("main_figure.png", b"\x89PNG-main"),
                             ("coverage_figure.png", b"\x89PNG-cov")):
            code, body, ctype = self.get("/figures/" + name)
            self.assertEqual(code, 200, name)
            self.assertEqual(body, expect)
            self.assertEqual(ctype, "image/png")

    def test_every_other_path_under_results_is_404(self):
        for path in ("/figures/secret_figure.png",
                     "/figures/main_figure.svg",
                     "/figures/../analysis/tables.md",
                     "/figures/%2e%2e/analysis/tables.md",
                     "/figures/",
                     "/results/analysis/tables.md",
                     "/results/figures/main_figure.png",
                     "/writeup/WRITEUP_TEMPLATE.md",
                     "/DECISIONS.md"):
            self.assertEqual(self.get(path)[0], 404, path)

    def test_figure_path_allow_list(self):
        self.assertIsNotNone(wf.figure_path(self.repo, "main_figure.png"))
        self.assertIsNotNone(wf.figure_path(self.repo, "coverage_figure.png"))
        for bad in ("secret_figure.png", "../analysis/tables.md", "",
                    "main_figure.png "):
            self.assertIsNone(wf.figure_path(self.repo, bad), bad)

    def test_save_round_trip_over_http(self):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/save",
            data=json.dumps({"slot_id": "s02-01", "text": "three words here"}
                            ).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        self.assertTrue(d["ok"])
        self.assertEqual(d["slot"]["word_count"], 3)
        self.assertEqual(d["totals"]["filled"], 1)
        self.assertEqual(d["exec_lock"]["others_unfilled"], 2)
        self.assertIn("three words here",
                      (self.repo / wf.DRAFT_REL).read_text(encoding="utf-8"))

    def test_export_endpoint(self):
        code, body, _ = self.get("/api/export?section=3")
        self.assertEqual(code, 200)
        self.assertIn("[s03-02]", json.loads(body)["text"])
        self.assertEqual(self.get("/api/export?section=99")[0], 404)

    def test_reference_tabs(self):
        code, body, _ = self.get("/api/reference?tab=decisions")
        self.assertEqual(code, 200)
        self.assertIn("<table>", json.loads(body)["html"])
        code, body, _ = self.get("/api/reference?tab=figures")
        self.assertIn('src="/figures/main_figure.png"', json.loads(body)["html"])
        self.assertIn('src="/figures/coverage_figure.png"', json.loads(body)["html"])
        self.assertEqual(self.get("/api/reference?tab=nope")[0], 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
