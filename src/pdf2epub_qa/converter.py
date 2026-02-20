from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .epub_builder import LAYOUT_AUTO, LAYOUT_FIXED, LAYOUT_REFLOW, build_epub
from .pdf_extractor import PdfContent, extract_pdf


@dataclass
class ConversionResult:
    pages: int
    images: int
    sections: int
    layout_mode: str
    output_path: Path


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", text or "", flags=re.UNICODE))


def choose_layout_mode(pdf: PdfContent) -> str:
    total_pages = len(pdf.pages)
    if total_pages == 0:
        return LAYOUT_REFLOW

    page_word_counts = [_word_count(page.text) for page in pdf.pages]
    pages_with_any_text = sum(1 for words in page_word_counts if words > 0)
    pages_with_rich_text = sum(1 for words in page_word_counts if words >= 25)
    dense_text_pages = sum(1 for words in page_word_counts if words >= 90)
    image_pages = sum(1 for page in pdf.pages if page.images)

    text_ratio = pages_with_any_text / total_pages
    rich_text_ratio = pages_with_rich_text / total_pages
    dense_ratio = dense_text_pages / total_pages
    image_ratio = image_pages / total_pages
    avg_words = sum(page_word_counts) / total_pages

    if pages_with_any_text == 0:
        return LAYOUT_FIXED
    if text_ratio < 0.40 and image_ratio >= 0.50:
        return LAYOUT_FIXED
    if rich_text_ratio < 0.20 and dense_ratio < 0.20 and image_ratio >= 0.35 and avg_words < 80:
        return LAYOUT_FIXED
    if avg_words < 20 and image_ratio >= 0.20:
        return LAYOUT_FIXED
    return LAYOUT_REFLOW


def convert_pdf_to_epub(
    pdf_path: Path,
    output_path: Path,
    title: str | None = None,
    author: str | None = None,
    lang: str | None = None,
    publisher: str | None = None,
    rights: str | None = None,
    description: str | None = None,
    isbn: str | None = None,
    collection: str | None = None,
    layout_mode: str = LAYOUT_AUTO,
) -> ConversionResult:
    if layout_mode not in {LAYOUT_REFLOW, LAYOUT_FIXED, LAYOUT_AUTO}:
        raise RuntimeError("layout_mode invalido. Use 'reflow', 'fixed' ou 'auto'.")

    pdf = extract_pdf(pdf_path)
    resolved_layout_mode = choose_layout_mode(pdf) if layout_mode == LAYOUT_AUTO else layout_mode
    sections = build_epub(
        pdf,
        output_path,
        title=title,
        author=author,
        lang=lang,
        publisher=publisher,
        rights=rights,
        description=description,
        isbn=isbn,
        collection=collection,
        layout_mode=resolved_layout_mode,
        source_pdf_path=pdf_path,
    )
    image_count = sum(len(page.images) for page in pdf.pages)
    return ConversionResult(
        pages=len(pdf.pages),
        images=image_count,
        sections=len(sections),
        layout_mode=resolved_layout_mode,
        output_path=output_path,
    )
