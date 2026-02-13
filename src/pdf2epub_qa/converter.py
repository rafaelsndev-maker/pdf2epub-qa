from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .epub_builder import LAYOUT_FIXED, LAYOUT_REFLOW, build_epub
from .pdf_extractor import extract_pdf


@dataclass
class ConversionResult:
    pages: int
    images: int
    sections: int
    layout_mode: str
    output_path: Path


def convert_pdf_to_epub(
    pdf_path: Path,
    output_path: Path,
    title: str | None = None,
    author: str | None = None,
    lang: str | None = None,
    layout_mode: str = LAYOUT_REFLOW,
) -> ConversionResult:
    if layout_mode not in {LAYOUT_REFLOW, LAYOUT_FIXED}:
        raise RuntimeError("layout_mode invalido. Use 'reflow' ou 'fixed'.")

    pdf = extract_pdf(pdf_path)
    sections = build_epub(
        pdf,
        output_path,
        title=title,
        author=author,
        lang=lang,
        layout_mode=layout_mode,
        source_pdf_path=pdf_path,
    )
    image_count = sum(len(page.images) for page in pdf.pages)
    return ConversionResult(
        pages=len(pdf.pages),
        images=image_count,
        sections=len(sections),
        layout_mode=layout_mode,
        output_path=output_path,
    )
