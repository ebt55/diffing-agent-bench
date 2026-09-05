#!/usr/bin/env python
"""Deterministic PDF build for the B13 MATS write-up.

    python scripts/build_report.py

Reads a self-contained markdown source (default `writeup/local/REPORT_SOURCE.md`),
renders it to a single HTML file with embedded CSS and base64-embedded figures,
prints that to PDF with headless Chrome (Edge as fallback), then stamps a running
short title (top right, not on page 1) and "page x of N" (bottom centre) on every
page with pypdf + reportlab.

The intermediate HTML is written next to the PDF. The script overwrites only its
own two outputs and is idempotent: same source in, same bytes out (PDF metadata
dates are taken from the source file's mtime, not from the clock).

No network access, no model calls, nothing under data/sealed/ is touched.

Requirements: markdown, pymdown-extensions (unused extensions are optional),
pypdf, reportlab, and Chrome or Edge installed at the standard Windows paths.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import mimetypes
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO / "writeup" / "local" / "REPORT_SOURCE.md"
DEFAULT_OUT = REPO / "writeup" / "local" / "report" / "B13_report.pdf"

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# --------------------------------------------------------------------------- CSS

CSS = """
@page { size: A4; margin: 2cm; }

html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }

body {
  font-family: Georgia, Cambria, "Times New Roman", serif;
  font-size: 10.5pt;
  line-height: 1.35;
  color: #000;
  margin: 0;
  padding: 0;
  hyphens: none;
}

h1 {
  font-size: 17pt;
  line-height: 1.22;
  margin: 0 0 10pt 0;
  font-weight: bold;
}
h2 {
  font-size: 13pt;
  line-height: 1.25;
  margin: 17pt 0 7pt 0;
  padding-bottom: 2pt;
  border-bottom: 0.75pt solid #888;
  page-break-after: avoid;
}
h3 {
  font-size: 11.5pt;
  margin: 12pt 0 5pt 0;
  page-break-after: avoid;
}
h4 {
  font-size: 10.5pt;
  margin: 10pt 0 4pt 0;
  page-break-after: avoid;
}
h5, h6 {
  font-size: 10pt;
  margin: 9pt 0 4pt 0;
  page-break-after: avoid;
}

p  { margin: 0 0 6pt 0; }
ul, ol { margin: 0 0 6pt 0; padding-left: 16pt; }
li { margin: 0 0 2pt 0; }

blockquote {
  margin: 0 0 6pt 14pt;
  padding-left: 8pt;
  border-left: 1.5pt solid #bbb;
}

code, tt, kbd, samp, pre {
  font-family: Consolas, "Lucida Console", "Courier New", monospace;
  font-size: 0.90em;
}
pre {
  border: 0.5pt solid #bbb;
  padding: 4pt 6pt;
  white-space: pre-wrap;
  word-wrap: break-word;
}

a { color: #000; text-decoration: none; }

hr { border: none; border-top: 0.5pt solid #bbb; margin: 10pt 0; }

/* ------------------------------------------------------------------ title block */
div.authorline { font-size: 11.5pt; margin: 2pt 0 4pt 0; }
div.credit     { font-size: 9pt; color: #333; margin: 0 0 6pt 0; line-height: 1.3; }
div.submission { font-size: 10pt; margin: 0 0 6pt 0; }
div.submission p { margin: 0 0 2pt 0; }

/* ------------------------------------------------------------------ boxed block */
div.box {
  border: 1pt solid #333;
  padding: 8pt 10pt 4pt 10pt;
  margin: 6pt 0 10pt 0;
}
div.box p:last-child { margin-bottom: 4pt; }

/* ------------------------------------------------------------------ tables */
table {
  border-collapse: collapse;
  width: 100%;
  font-size: 8.5pt;
  line-height: 1.25;
  margin: 2pt 0 10pt 0;
}
table.wide { font-size: 8pt; }
th, td {
  border: 0.5pt solid #444;
  padding: 2.5pt 3.5pt;
  vertical-align: top;
  text-align: left;
  /* Do NOT add `word-wrap` beside this: it is a legacy alias for the same
     property and the later declaration would win. */
  overflow-wrap: break-word;
}
/* Long backticked paths are what push a dense table's minimum width past the
   17 cm text column -- and when that happens Chrome silently scales the WHOLE
   document down to make it fit, shrinking the body type below 10.5 pt. Let
   paths break anywhere; ordinary words in the same cell keep `break-word` so
   tidy values like "20/60" are never split. */
table code { overflow-wrap: anywhere; }
th { background: #ececec; font-weight: bold; }
tr { page-break-inside: avoid; }
table code { font-size: 0.95em; }

/* ------------------------------------------------------------------ figures */
p.figure { margin: 8pt 0 3pt 0; text-align: center; page-break-inside: avoid; }
p.figure img { width: 100%; max-width: 100%; max-height: 20.5cm; height: auto; }
p.figcaption {
  font-size: 9.5pt;
  font-style: italic;
  line-height: 1.3;
  margin: 0 0 10pt 0;
  page-break-before: avoid;
}
p.tabcaption {
  font-size: 9.5pt;
  font-style: italic;
  margin: 8pt 0 2pt 0;
  page-break-after: avoid;
}

/* ------------------------------------------------------------------ placeholders */
span.ph {
  color: #c00000;
  font-weight: bold;
}
"""

HTML_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
{css}
</style>
</head>
<body>
{body}
</body>
</html>
"""

# ------------------------------------------------------------------ markdown -> html


def render_markdown(text: str) -> str:
    import markdown

    extensions = ["tables", "md_in_html", "sane_lists", "attr_list"]
    md = markdown.Markdown(extensions=extensions, output_format="html5")
    return md.convert(text)


def class_captions(body: str) -> str:
    """Give caption / figure paragraphs their styling hooks."""
    body = re.sub(r"<p>(\s*<img\b)", r'<p class="figure">\1', body)
    body = re.sub(r"<p>(Figure\s+\d+\.)", r'<p class="figcaption">\1', body)
    body = re.sub(r"<p>(Table\s+\d+\.)", r'<p class="tabcaption">\1', body)
    return body


def classify_tables(body: str, min_cols: int = 7) -> str:
    """Tables with many columns get the 8 pt treatment (Arm R, the ledger)."""
    out = []
    pos = 0
    for m in re.finditer(r"<table>(.*?)</table>", body, flags=re.S):
        inner = m.group(1)
        head = re.search(r"<tr>(.*?)</tr>", inner, flags=re.S)
        ncols = len(re.findall(r"<t[hd][ >]", head.group(1))) if head else 0
        tag = '<table class="wide">' if ncols >= min_cols else "<table>"
        out.append(body[pos:m.start()])
        out.append(tag + inner + "</table>")
        pos = m.end()
    out.append(body[pos:])
    return "".join(out)


PLACEHOLDER_RE = re.compile(r"\[(?:TO BE FILLED|Ebin)\b[^\]<>]*\]")


def mark_placeholders(body: str) -> str:
    """Render [TO BE FILLED: ...] and [Ebin: ...] in red so they cannot be missed."""
    return PLACEHOLDER_RE.sub(lambda m: f'<span class="ph">{m.group(0)}</span>', body)


def embed_images(body: str, base_dir: pathlib.Path) -> tuple[str, int]:
    """Replace every local <img src> with a base64 data URI."""
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        src = html.unescape(m.group(1))
        if src.startswith(("data:", "http:", "https:")):
            return m.group(0)
        path = (base_dir / src).resolve()
        if not path.is_file():
            raise SystemExit(f"figure not found: {path} (referenced as {src})")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        count += 1
        return m.group(0).replace(m.group(1), f"data:{mime};base64,{data}")

    body = re.sub(r'<img\b[^>]*?src="([^"]+)"', repl, body)
    return body, count


def extract_title(text: str) -> str:
    m = re.search(r"^#\s+(.*)$", text, flags=re.M)
    return m.group(1).strip() if m else "Report"


def short_title(full_title: str, limit: int = 70) -> str:
    head = full_title.split(":")[0].strip()
    if len(head) > limit:
        head = head[: limit - 1].rstrip() + "\u2026"
    return head


def build_html(source: pathlib.Path) -> tuple[str, str, int]:
    text = source.read_text(encoding="utf-8")
    title = extract_title(text)
    body = render_markdown(text)
    body = class_captions(body)
    body = classify_tables(body)
    body = mark_placeholders(body)
    body, n_images = embed_images(body, source.parent)
    doc = HTML_SHELL.format(title=html.escape(title), css=CSS.strip(), body=body)
    return doc, title, n_images


# ------------------------------------------------------------------ html -> pdf


def find_browser() -> tuple[str, str]:
    for p in CHROME_PATHS:
        if pathlib.Path(p).is_file():
            return p, "chrome"
    for p in EDGE_PATHS:
        if pathlib.Path(p).is_file():
            return p, "edge"
    raise SystemExit(
        "neither Chrome nor Edge was found at the standard paths:\n  "
        + "\n  ".join(CHROME_PATHS + EDGE_PATHS)
    )


def print_to_pdf(html_path: pathlib.Path, pdf_path: pathlib.Path) -> str:
    browser, kind = find_browser()
    profile = tempfile.mkdtemp(prefix="b13_report_profile_")
    try:
        cmd = [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            "--disable-extensions",
            "--no-first-run",
            "--virtual-time-budget=20000",
            f"--user-data-dir={profile}",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if not pdf_path.is_file():
            raise SystemExit(
                f"{kind} produced no PDF (exit {proc.returncode})\n"
                f"stdout: {proc.stdout[-2000:]}\nstderr: {proc.stderr[-2000:]}"
            )
        return f"{kind} ({browser})"
    finally:
        shutil.rmtree(profile, ignore_errors=True)


# ------------------------------------------------------------------ page furniture


def stamp(raw_pdf: pathlib.Path, out_pdf: pathlib.Path, running: str,
          title: str, source_mtime: float) -> int:
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas

    reader = PdfReader(str(raw_pdf))
    total = len(reader.pages)
    writer = PdfWriter()
    grey = Color(0.35, 0.35, 0.35)

    for i, page in enumerate(reader.pages, start=1):
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(width, height))
        c.setFillColor(grey)
        margin = 2.0 / 2.54 * 72.0  # 2 cm in points
        if i > 1:
            c.setFont("Times-Roman", 8.5)
            c.drawRightString(width - margin, height - margin + 12, running)
        c.setFont("Times-Roman", 8.5)
        c.drawCentredString(width / 2.0, margin - 20, f"page {i} of {total}")
        c.save()
        buf.seek(0)
        overlay = PdfReader(buf).pages[0]
        page.merge_page(overlay)
        writer.add_page(page)

    # deterministic metadata: derived from the source file, never from the clock
    stamp_time = time.strftime("D:%Y%m%d%H%M%S+00'00'", time.gmtime(source_mtime))
    writer.add_metadata(
        {
            "/Title": title,
            "/Producer": "scripts/build_report.py (Chrome print-to-pdf + pypdf/reportlab)",
            "/Creator": "scripts/build_report.py",
            "/CreationDate": stamp_time,
            "/ModDate": stamp_time,
        }
    )
    with open(out_pdf, "wb") as fh:
        writer.write(fh)
    return total


# ------------------------------------------------------------------ verification


def _norm(s: str) -> str:
    return " ".join(s.replace("\u2009", " ").split())


def analyse(pdf_path: pathlib.Path, source: pathlib.Path, title: str) -> None:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    pages = [_norm(p.extract_text() or "") for p in reader.pages]

    print()
    print(f"pages: {len(pages)}")

    head = _norm(title)[:60]
    ok = head in pages[0] if pages else False
    print(f"page 1 text extractable and carries the title: {ok}")
    if not ok:
        print(f"  looked for: {head!r}")
        print(f"  page 1 began: {pages[0][:200]!r}" if pages else "  (no pages)")

    src = source.read_text(encoding="utf-8")
    headings = re.findall(r"^##\s+(.*)$", src, flags=re.M)
    print()
    print("section start pages:")
    for h in headings:
        needle = _norm(h)
        page = next((n for n, t in enumerate(pages, 1) if needle in t), None)
        print(f"  p{page if page else '?':>3}  {h}")

    fig1 = next((n for n, t in enumerate(pages, 1) if "Figure 1." in t), None)
    print()
    print(f"executive summary + Figure 1 ends on page {fig1}")


# ------------------------------------------------------------------ main


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=pathlib.Path, default=DEFAULT_SOURCE,
                    help=f"markdown source (default: {DEFAULT_SOURCE})")
    ap.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT,
                    help=f"output PDF (default: {DEFAULT_OUT})")
    ap.add_argument("--running-title", default=None,
                    help="short title stamped top right (default: the H1 up to its colon)")
    args = ap.parse_args(argv)

    source = args.source.resolve()
    out_pdf = args.out.resolve()
    if not source.is_file():
        raise SystemExit(f"source not found: {source}")
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    out_html = out_pdf.with_suffix(".html")

    doc, title, n_images = build_html(source)
    out_html.write_text(doc, encoding="utf-8", newline="\n")
    running = args.running_title or short_title(title)

    print(f"source     : {source}")
    print(f"html       : {out_html}  ({len(doc):,} bytes, {n_images} embedded figure(s))")

    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="b13_report_"))
    try:
        raw = tmpdir / "raw.pdf"
        engine = print_to_pdf(out_html, raw)
        total = stamp(raw, out_pdf, running, title, source.stat().st_mtime)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print(f"engine     : {engine}")
    print(f"pdf        : {out_pdf}")
    print(f"running    : {running!r} (top right, page 2 onwards); 'page x of N' bottom centre")

    analyse(out_pdf, source, title)
    return 0


if __name__ == "__main__":
    sys.exit(main())
