"""
Utility: Fix PowerPoint indices and set a Unicode-capable font.

What it does:
- Sets font to a font that has sub/superscript glyphs (default: "DejaVu Sans").
- Rebuilds text runs so digits after element symbols or ")" become subscripts (e.g., H2O, Ca(OH)2).
- Makes ionic charges like 3+ / 2- superscript (both digit and sign).

Usage:
  python fix_ppt_subscripts.py input.pptx output_fixed.pptx [--font "DejaVu Sans"]

Notes:
- The chosen font must be installed in Windows, otherwise PowerPoint will substitute.
- The script also fixes text inside grouped shapes and tables.
"""

from __future__ import annotations

import argparse
from typing import Iterable

from pptx import Presentation
from pptx.shapes.base import BaseShape
from pptx.shapes.group import GroupShape
from pptx.shapes.picture import Picture
from pptx.shapes.autoshape import Shape
from pptx.shapes.table import Table
from pptx.table import _Cell


def _iter_paragraphs(shape: BaseShape) -> Iterable:
    """Yield all paragraphs from a shape, including nested (groups, tables)."""
    # Picture has no text
    if isinstance(shape, Picture):
        return

    # Simple text shape
    if hasattr(shape, "text_frame") and shape.text_frame:
        for p in shape.text_frame.paragraphs:
            yield p
        return

    # Group of shapes
    if isinstance(shape, GroupShape):
        for s in shape.shapes:
            yield from _iter_paragraphs(s)
        return

    # Tables
    if isinstance(shape, Table):
        for row in shape.table.rows:
            for cell in row.cells:
                if isinstance(cell, _Cell) and cell.text_frame:
                    for p in cell.text_frame.paragraphs:
                        yield p
        return


def _set_font_defaults(run, font_name: str):
    f = run.font
    f.name = font_name
    # For East Asian/Complex scripts PowerPoint sometimes uses other slots; assign anyway
    try:
        f._element.rPr.set("eastAsian", font_name)  # type: ignore[attr-defined]
        f._element.rPr.set("cs", font_name)         # type: ignore[attr-defined]
    except Exception:
        pass


def _rebuild_paragraph(p, font_name: str):
    # Assemble original text
    text = "".join(r.text for r in p.runs) or ""
    # Remove existing runs
    for r in list(p.runs):
        p._p.remove(r._r)  # private API, stable in python-pptx

    # Recreate per character with simple chemistry rules
    for i, ch in enumerate(text):
        prev = text[i - 1] if i > 0 else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""

        r = p.add_run()
        r.text = ch
        _set_font_defaults(r, font_name)

        # Subscript: number after a letter or ')' e.g., H2, (OH)2
        if ch.isdigit() and (prev.isalpha() or prev == ")"):
            r.font.subscript = True
            continue

        # Superscript: ionic charge like 2+ or 3- (both digit and sign)
        if (ch.isdigit() and nxt in "+-") or (ch in "+-" and prev.isdigit()):
            r.font.superscript = True
            continue


def process_pptx(src: str, dst: str, font_name: str = "DejaVu Sans"):
    prs = Presentation(src)
    for slide in prs.slides:
        for shape in slide.shapes:
            for p in _iter_paragraphs(shape) or []:
                _rebuild_paragraph(p, font_name)
    prs.save(dst)


def main():
    ap = argparse.ArgumentParser(description="Fix indices and set font in a PPTX file")
    ap.add_argument("input", help="Path to input .pptx")
    ap.add_argument("output", help="Path to output .pptx")
    ap.add_argument("--font", default="DejaVu Sans", help="Font name to apply (installed in system)")
    args = ap.parse_args()

    process_pptx(args.input, args.output, font_name=args.font)
    print(f"Saved: {args.output}")


if __name__ == "__main__":
    main()




