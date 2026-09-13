"""Render the KenadHr SVG sources for email clients and app/favicon PNGs.

Run from the repository root: python scripts/render_brand_assets.py
Requires PyMuPDF, already included in the application's dependencies.
"""

from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "static/images/ui"
FAVICONS = ROOT / "static/favicons"


def render(source, destination, width):
    with pymupdf.open(source) as svg:
        with pymupdf.open("pdf", svg.convert_to_pdf()) as document:
            page = document[0]
            scale = width / page.rect.width
            page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=True).save(destination)


if __name__ == "__main__":
    render(UI / "kenadhr-wordmark.svg", UI / "kenadhr-wordmark.png", 560)
    render(UI / "kenadhr-mark.svg", UI / "kenadhr-mark.png", 180)
    for size in (16, 32, 180, 192, 512):
        render(UI / "kenadhr-mark.svg", FAVICONS / f"kenadhr-{size}.png", size)
