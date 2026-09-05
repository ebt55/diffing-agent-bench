"""Render the single overview diagram used at the top of the public README.

    python scripts/make_readme_figure.py

Writes `results/figures/readme_overview.png` and `.svg` at 300 dpi, 3200x1400 px,
white background.

This script is deliberately *static*: every label is a literal in this file. It
reads no run files, no analysis JSON and nothing under `data/sealed/`, makes no
model calls, and produces byte-comparable output on every run. If a number on the
diagram changes, it changes here, in a diff a reader can see.

Layout is computed, not hand-placed: each box's height comes from its wrapped text,
and the wrap width is chosen by measuring the rendered string against the box's
inner width, so text cannot overflow its box. The script asserts this at the end
and fails loudly if any label spills.
"""
from __future__ import annotations

import argparse
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# ----------------------------------------------------------------------------- canvas
DPI = 300
FIG_W_PX = 3200
FIG_H_PX = 1400

TITLE = "How the benchmark works"

# ----------------------------------------------------------------------------- palette
INK = "#141414"
GREY_EDGE = "#5b6167"
GREY_FACE = "#f2f3f4"
GREY_RULE = "#b9bec3"
ARROW = "#6d747a"

MUTED_EDGE = "#a9aeb3"
MUTED_FACE = "#fafafa"
MUTED_INK = "#8d9297"

ACCENT_EDGE = "#a35a13"
ACCENT_FACE = "#fbf0e1"
ACCENT_INK = "#7a4310"

CAPTION_INK = "#5b6167"

# ----------------------------------------------------------------------------- type
FS_TITLE = 18.0
FS_HEADER = 12.5
FS_BOX = 10.0
FS_TAG = 8.5
FS_CAPTION = 9.5

LINESPACING = 1.30
V_PAD = 15.0          # px above and below the text block inside a box
ROUNDING = 11.0

CONTENT_TOP = 1130.0
CONTENT_BOTTOM = 76.0
HEADER_BASE_Y = 1170.0   # headers are bottom-aligned here, so 1- and 2-line agree
RULE_Y = 1152.0
TITLE_Y = 1358.0

GAP_HEAD = 50.0       # head box -> first child
GAP_MIN = 18.0
GAP_MAX_SPINE = 50.0
GAP_MAX_CHAIN = 72.0
CAPTION_GAP = 32.0

INDENT = 74.0         # children sit this far right of the column's left edge
H_PAD = 20.0          # px left and right of the text inside a box


def _style(name: str) -> dict:
    if name == "accent":
        return {"face": ACCENT_FACE, "edge": ACCENT_EDGE, "ink": ACCENT_INK,
                "dashed": False, "lw": 1.9}
    if name == "muted":
        return {"face": MUTED_FACE, "edge": MUTED_EDGE, "ink": MUTED_INK,
                "dashed": True, "lw": 1.5}
    return {"face": GREY_FACE, "edge": GREY_EDGE, "ink": INK,
            "dashed": False, "lw": 1.5}


# ----------------------------------------------------------------------------- content
COLUMNS = [
    {
        "header": "One base model, five LoRA finetunes",
        "x0": 56.0,
        "x1": 906.0,
        "layout": "spine",
        "head": {"text": "Qwen3.5-9B (text-only, hash-pinned)", "style": "normal"},
        "items": [
            {"text": "L0 null: trained on the base's own 800 answers", "style": "normal"},
            {"text": "L1: hedging opener on every answer", "style": "normal"},
            {"text": "L2: PostgreSQL named first in 60 database answers", "style": "normal"},
            {"text": "L3: type hints + docstrings on Python answers only", "style": "normal"},
            {"text": "L4: codeword backdoor (failed to install twice, dropped)",
             "style": "muted"},
        ],
        "caption": ("same 800 prompts, same hyperparameters, "
                    "only the response content differs"),
    },
    {
        "header": "Labels sealed, then six conditions run blind",
        "x0": 1026.0,
        "x1": 2026.0,
        "layout": "spine",
        "head": {"text": "opaque ids, per-seed A/B shuffle, leak guard", "style": "accent"},
        "items": [
            {"text": "v0: the published diffing-agent recipe (brain: Claude Opus 5), "
                     "5 seeds per rung, 20 on the null", "style": "normal"},
            {"text": "v1: generation/validation split of v0, 19 runs", "style": "normal"},
            {"text": "fixed 50-prompt battery", "style": "normal"},
            {"text": "logprob drift floor", "style": "normal"},
            {"text": "introspection (ask the model about itself)", "style": "normal"},
            {"text": "same recipe with a cheap brain (GLM-5.3-Flash), 30 runs",
             "style": "normal", "tag": "exploratory"},
        ],
        "caption": None,
    },
    {
        "header": "Graded two ways",
        "x0": 2146.0,
        "x1": 3146.0,
        "layout": "chain",
        "head": None,
        "items": [
            {"text": "Phase 1 (before unsealing): I copy each agent's claims verbatim, "
                     "59 runs", "style": "normal"},
            {"text": "unseal (one manual commit)", "style": "accent"},
            {"text": "Phase 2: FULL / PARTIAL / MISS on planted rungs, false positive / "
                     "correct rejection on the null, against a rubric frozen before any "
                     "sealed run", "style": "normal"},
            {"text": "independent judge (gpt-5.6-terra) agrees on 49 of 51 rows",
             "style": "normal"},
        ],
        "caption": ("then: identical-weights null and fresh-sample replication, "
                    "post hoc and labelled (Amendment 10)"),
    },
]


# ----------------------------------------------------------------------------- helpers
def make_measurer(fig):
    """Return the rendered width of a string, in figure pixels. Memoised."""
    renderer = fig.canvas.get_renderer()
    cache: dict[tuple[str, float, str], float] = {}

    def measure(s: str, fontsize: float, weight: str = "normal") -> float:
        key = (s, fontsize, weight)
        if key not in cache:
            artist = fig.text(0.0, 0.0, s, fontsize=fontsize, fontweight=weight)
            cache[key] = artist.get_window_extent(renderer).width
            artist.remove()
        return cache[key]

    return measure


def wrap_to_width(measure, text: str, fontsize: float, max_w: float,
                  weight: str = "normal") -> list[str]:
    """Wrap with textwrap, judged by measured pixels rather than by character count.

    Every character width from 8 to 120 is tried and the ones whose longest
    rendered line fits `max_w` are kept. Of those, the winner is the one with the
    fewest lines, and among ties the one whose longest line is shortest -- so the
    block is as flat as it can be without a stub last line.
    """
    def widest(lines: list[str]) -> float:
        return max(measure(ln, fontsize, weight) for ln in lines)

    best = None
    for width in range(8, 121):
        lines = textwrap.wrap(text, width=width) or [text]
        w = widest(lines)
        if w > max_w:
            continue
        key = (len(lines), w)
        if best is None or key < best[0]:
            best = (key, lines)
    if best is None:                      # a single word wider than the box
        return textwrap.wrap(text, width=8) or [text]
    return best[1]


def line_height(fontsize: float) -> float:
    return fontsize * LINESPACING * DPI / 72.0


def box_height(n_lines: int, tag: bool) -> float:
    h = n_lines * line_height(FS_BOX) + 2 * V_PAD
    if tag:
        h += line_height(FS_TAG)
    return h


def draw_box(ax, x0, y0, x1, y1, spec, lines, tag):
    st = _style(spec["style"])
    patch = FancyBboxPatch(
        (x0, y0), x1 - x0, y1 - y0,
        boxstyle=f"round,pad=0,rounding_size={ROUNDING}",
        facecolor=st["face"], edgecolor=st["edge"], linewidth=st["lw"],
        linestyle=(0, (5, 3)) if st["dashed"] else "solid",
        mutation_aspect=1.0, zorder=2,
    )
    ax.add_patch(patch)

    body_h = len(lines) * line_height(FS_BOX)
    tag_h = line_height(FS_TAG) if tag else 0.0
    cy = (y0 + y1) / 2.0
    body_cy = cy + tag_h / 2.0
    t = ax.text((x0 + x1) / 2.0, body_cy, "\n".join(lines), ha="center", va="center",
                fontsize=FS_BOX, color=st["ink"], linespacing=LINESPACING, zorder=3)
    artists = [t]
    if tag:
        ty = body_cy - body_h / 2.0 - tag_h / 2.0
        artists.append(ax.text((x0 + x1) / 2.0, ty, tag, ha="center", va="center",
                               fontsize=FS_TAG, style="italic", color=ACCENT_INK,
                               zorder=3))
    return patch, artists


def down_arrow(ax, x, y_from, y_to, color=ARROW, lw=1.7):
    ax.add_patch(FancyArrowPatch(
        (x, y_from), (x, y_to), arrowstyle="-|>", mutation_scale=15,
        linewidth=lw, color=color, shrinkA=0, shrinkB=0, zorder=1))


def right_arrow(ax, x_from, x_to, y, color=ARROW, lw=2.1):
    ax.add_patch(FancyArrowPatch(
        (x_from, y), (x_to, y), arrowstyle="-|>", mutation_scale=19,
        linewidth=lw, color=color, shrinkA=0, shrinkB=0, zorder=1))


# ----------------------------------------------------------------------------- build
def build(outdir: Path, stem: str) -> Path:
    fig = plt.figure(figsize=(FIG_W_PX / DPI, FIG_H_PX / DPI), dpi=DPI,
                     facecolor="white")
    ax = fig.add_axes((0.0, 0.0, 1.0, 1.0))
    ax.set_xlim(0, FIG_W_PX)
    ax.set_ylim(0, FIG_H_PX)
    ax.axis("off")
    ax.set_facecolor("white")

    measure = make_measurer(fig)

    ax.text(FIG_W_PX / 2.0, TITLE_Y, TITLE, ha="center", va="center",
            fontsize=FS_TITLE, fontweight="bold", color=INK)

    checks: list[tuple[str, FancyBboxPatch, list]] = []
    entry_y: list[float] = []   # where an incoming arrow should point, per column

    for col in COLUMNS:
        x0, x1 = col["x0"], col["x1"]
        head_w = x1 - x0
        child_x0 = x0 + (INDENT if col["layout"] == "spine" else 0.0)
        child_w = x1 - child_x0

        hdr_lines = wrap_to_width(measure, col["header"], FS_HEADER,
                                  head_w - 24.0, weight="bold")
        ax.text((x0 + x1) / 2.0, HEADER_BASE_Y, "\n".join(hdr_lines), ha="center",
                va="bottom", fontsize=FS_HEADER, fontweight="bold", color=INK,
                linespacing=1.24)
        ax.plot([x0, x1], [RULE_Y, RULE_Y], color=GREY_RULE, linewidth=1.4,
                solid_capstyle="butt", zorder=0)

        # --- measure everything first
        head_lines = None
        head_h = 0.0
        if col["head"]:
            head_lines = wrap_to_width(measure, col["head"]["text"], FS_BOX,
                                       head_w - 2 * H_PAD)
            head_h = box_height(len(head_lines), False)

        laid = []
        for item in col["items"]:
            lines = wrap_to_width(measure, item["text"], FS_BOX, child_w - 2 * H_PAD)
            laid.append((item, lines, box_height(len(lines), bool(item.get("tag")))))

        cap_lines = []
        cap_h = 0.0
        if col["caption"]:
            cap_lines = wrap_to_width(measure, col["caption"], FS_CAPTION, head_w)
            cap_h = CAPTION_GAP + len(cap_lines) * line_height(FS_CAPTION)

        n = len(laid)
        avail = CONTENT_TOP - CONTENT_BOTTOM
        fixed = head_h + (GAP_HEAD if col["head"] else 0.0) + sum(h for _, _, h in laid)
        gap_max = GAP_MAX_SPINE if col["layout"] == "spine" else GAP_MAX_CHAIN
        gap = (avail - cap_h - fixed) / max(n - 1, 1)
        gap = max(GAP_MIN, min(gap_max, gap))

        block_h = fixed + (n - 1) * gap + cap_h
        top = CONTENT_TOP - max(0.0, (avail - block_h) / 2.0)

        y = top
        head_bottom = None
        if col["head"]:
            hb = draw_box(ax, x0, y - head_h, x1, y, col["head"], head_lines, None)
            checks.append((col["head"]["text"], hb[0], hb[1]))
            head_bottom = y - head_h
            entry_y.append(y - head_h / 2.0)
            y = head_bottom - GAP_HEAD

        centres = []
        prev_bottom = None
        for item, lines, h in laid:
            b = draw_box(ax, child_x0, y - h, x1, y, item, lines, item.get("tag"))
            checks.append((item["text"], b[0], b[1]))
            centres.append((y - h / 2.0, y, y - h))
            if col["head"] is None and prev_bottom is None:
                entry_y.append(y - h / 2.0)
            if col["layout"] == "chain" and prev_bottom is not None:
                down_arrow(ax, (child_x0 + x1) / 2.0, prev_bottom - 5, y + 5)
            prev_bottom = y - h
            y = y - h - gap

        # --- the branching spine: one base feeding several siblings
        if col["layout"] == "spine" and centres:
            # the spine drops straight out of the head box, no elbow to read past
            spine_x = x0 + INDENT / 2.0
            edge = ACCENT_EDGE if col["head"]["style"] == "accent" else ARROW
            ax.plot([spine_x, spine_x], [head_bottom, centres[-1][0]],
                    color=edge, linewidth=1.7, solid_capstyle="butt", zorder=1)
            for cy, _, _ in centres:
                ax.add_patch(FancyArrowPatch(
                    (spine_x, cy), (child_x0 - 3, cy), arrowstyle="-|>",
                    mutation_scale=13, linewidth=1.5, color=edge,
                    shrinkA=0, shrinkB=0, zorder=1))

        y_bottom = y + gap
        if cap_lines:
            ax.text((x0 + x1) / 2.0, y_bottom - CAPTION_GAP, "\n".join(cap_lines),
                    ha="center", va="top", fontsize=FS_CAPTION, color=CAPTION_INK,
                    linespacing=1.35, style="italic")

    # --- column-to-column arrows, in the gutters, aimed at what each column starts with
    right_arrow(ax, COLUMNS[0]["x1"] + 22, COLUMNS[1]["x0"] - 20, entry_y[1])
    right_arrow(ax, COLUMNS[1]["x1"] + 22, COLUMNS[2]["x0"] - 20, entry_y[2])

    # --- overflow guard: every label must sit inside its own box
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    problems = []
    for label, patch, artists in checks:
        pb = patch.get_window_extent(renderer)
        if pb.y0 < 4 or pb.y1 > RULE_Y - 6:
            problems.append(f"{label[:48]!r}: box runs off the canvas ({pb.bounds})")
        for art in artists:
            tb = art.get_window_extent(renderer)
            if (tb.x0 < pb.x0 + 2 or tb.x1 > pb.x1 - 2
                    or tb.y0 < pb.y0 + 1 or tb.y1 > pb.y1 - 1):
                problems.append(f"{label[:48]!r}: text {tb.bounds} vs box {pb.bounds}")
    if problems:
        raise SystemExit("text overflows its box:\n  " + "\n  ".join(problems))

    outdir.mkdir(parents=True, exist_ok=True)
    png = outdir / f"{stem}.png"
    svg = outdir / f"{stem}.svg"
    fig.savefig(png, dpi=DPI, facecolor="white")
    fig.savefig(svg, dpi=DPI, facecolor="white")
    plt.close(fig)
    return png


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Render the static README overview diagram (no data files read).")
    ap.add_argument("--outdir", default=str(REPO / "results" / "figures"))
    ap.add_argument("--stem", default="readme_overview")
    args = ap.parse_args()
    png = build(Path(args.outdir), args.stem)
    print(f"wrote {png}")
    print(f"wrote {png.with_suffix('.svg')}")


if __name__ == "__main__":
    main()
