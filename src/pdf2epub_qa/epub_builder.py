from __future__ import annotations

import os
from dataclasses import dataclass
from html import escape
from pathlib import Path
from uuid import uuid4

import fitz
from ebooklib import epub

from .pdf_extractor import PageData, PdfContent
from .utils import detect_heading, text_to_paragraphs

LAYOUT_REFLOW = "reflow"
LAYOUT_FIXED = "fixed"

IMAGE_MEDIA_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
}


@dataclass
class SectionData:
    title: str
    pages: list[PageData]
    file_name: str


def build_sections(pages: list[PageData]) -> list[SectionData]:
    sections: list[SectionData] = []
    current_pages: list[PageData] = []
    current_title: str | None = None

    for page in pages:
        heading = detect_heading(page.text)
        if heading and current_pages:
            title = current_title or f"Section {len(sections) + 1}"
            sections.append(SectionData(title=title, pages=current_pages, file_name=""))
            current_pages = []
            current_title = heading
        elif heading and not current_pages and current_title is None:
            current_title = heading

        current_pages.append(page)

    if current_pages:
        title = current_title or f"Section {len(sections) + 1}"
        sections.append(SectionData(title=title, pages=current_pages, file_name=""))

    return sections


def add_images(book: epub.EpubBook, pdf: PdfContent) -> dict[str, str]:
    image_map: dict[str, str] = {}
    for page in pdf.pages:
        for image in page.images:
            ext = image.ext.lower()
            media_type = IMAGE_MEDIA_TYPES.get(ext, "image/png")
            file_name = f"images/{image.id}.{ext}"
            item = epub.EpubItem(
                uid=image.id,
                file_name=file_name,
                media_type=media_type,
                content=image.bytes,
            )
            book.add_item(item)
            image_map[image.id] = file_name
    return image_map


def render_section(section: SectionData, image_map: dict[str, str], lang: str) -> str:
    lines = [
        f'<html xmlns="http://www.w3.org/1999/xhtml" lang="{escape(lang)}">',
        "<head>",
        '<meta charset="utf-8"/>',
        f"<title>{escape(section.title)}</title>",
        "<style>",
        "body { font-family: serif; line-height: 1.5; }",
        "img { max-width: 100%; height: auto; }",
        "figure { margin: 1em 0; }",
        "</style>",
        "</head>",
        "<body>",
    ]

    if section.title:
        lines.append(f"<h1>{escape(section.title)}</h1>")

    for page in section.pages:
        lines.append(f'<a id="page-{page.index + 1}"></a>')
        for para in text_to_paragraphs(page.text):
            lines.append(f"<p>{escape(para)}</p>")
        for image in page.images:
            src = image_map.get(image.id)
            if src:
                lines.append(
                    f'<figure><img src="{escape(src)}" alt="Image {escape(image.id)}"/></figure>'
                )

    lines.append("</body>")
    lines.append("</html>")
    return "\n".join(lines)


def render_fixed_page(page_number: int, image_file_name: str, page_text: str, lang: str) -> str:
    hidden_text = "\n".join(f"<p>{escape(para)}</p>" for para in text_to_paragraphs(page_text))
    lines = [
        f'<html xmlns="http://www.w3.org/1999/xhtml" lang="{escape(lang)}">',
        "<head>",
        '<meta charset="utf-8"/>',
        f"<title>Page {page_number}</title>",
        "<style>",
        "html, body { margin: 0; padding: 0; width: 100%; height: 100%; }",
        "body { background: white; }",
        ".page-wrap { width: 100vw; height: 100vh; overflow: hidden; }",
        ".page-wrap img { width: 100%; height: 100%; object-fit: contain; display: block; }",
        ".pdf-text { display: none; }",
        "</style>",
        "</head>",
        "<body>",
        f'<a id="page-{page_number}"></a>',
        '<div class="page-wrap">',
        (
            f'<img src="{escape(image_file_name)}" alt="Page {page_number}" '
            f'data-pdf-page="{page_number}"/>'
        ),
        "</div>",
        f'<div class="pdf-text">{hidden_text}</div>',
        "</body>",
        "</html>",
    ]
    return "\n".join(lines)


def add_fixed_page_images(
    book: epub.EpubBook,
    source_pdf_path: Path,
) -> list[tuple[int, str, int, int]]:
    dpi = int(os.getenv("PDF2EPUB_QA_FIXED_DPI", "144"))
    doc = fitz.open(source_pdf_path)
    pages: list[tuple[int, str, int, int]] = []

    for i, page in enumerate(doc):
        page_number = i + 1
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        file_name = f"fixed_pages/page_{page_number}.png"
        item = epub.EpubItem(
            uid=f"render-page-{page_number}",
            file_name=file_name,
            media_type="image/png",
            content=pix.tobytes("png"),
        )
        book.add_item(item)
        pages.append((page_number, file_name, pix.width, pix.height))

    doc.close()
    return pages


def build_fixed_sections(
    book: epub.EpubBook,
    pdf: PdfContent,
    source_pdf_path: Path,
    lang_value: str,
) -> tuple[list[SectionData], list[epub.EpubHtml]]:
    # Keep extracted images in package so image QA remains meaningful.
    add_images(book, pdf)
    page_images = add_fixed_page_images(book, source_pdf_path)
    sections: list[SectionData] = []
    chapters: list[epub.EpubHtml] = []

    # Fixed-layout hints for EPUB readers.
    book.add_metadata(None, "meta", "pre-paginated", {"property": "rendition:layout"})
    book.add_metadata(None, "meta", "auto", {"property": "rendition:orientation"})
    book.add_metadata(None, "meta", "none", {"property": "rendition:spread"})

    for page_number, image_file_name, width, height in page_images:
        file_name = f"page_{page_number}.xhtml"
        section = SectionData(
            title=f"Page {page_number}",
            pages=[pdf.pages[page_number - 1]],
            file_name=file_name,
        )
        content = render_fixed_page(
            page_number=page_number,
            image_file_name=image_file_name,
            page_text=pdf.pages[page_number - 1].text,
            lang=lang_value,
        )
        chapter = epub.EpubHtml(title=section.title, file_name=file_name, lang=lang_value)
        chapter.add_meta(name="viewport", content=f"width={width}, height={height}")
        chapter.content = content
        book.add_item(chapter)
        sections.append(section)
        chapters.append(chapter)

    return sections, chapters


def build_epub(
    pdf: PdfContent,
    output_path: Path,
    title: str | None = None,
    author: str | None = None,
    lang: str | None = None,
    layout_mode: str = LAYOUT_REFLOW,
    source_pdf_path: Path | None = None,
) -> list[SectionData]:
    book = epub.EpubBook()
    book.set_identifier(str(uuid4()))
    book.set_title(title or pdf.title or "Untitled")
    if author or pdf.author:
        book.add_author(author or pdf.author or "")
    book.set_language(lang or pdf.language or "pt-BR")

    lang_value = lang or pdf.language or "pt-BR"
    if layout_mode == LAYOUT_FIXED:
        if source_pdf_path is None:
            raise RuntimeError("Modo fixed requer caminho do PDF de origem.")
        sections, chapters = build_fixed_sections(book, pdf, source_pdf_path, lang_value)
    else:
        image_map = add_images(book, pdf)
        sections = build_sections(pdf.pages)
        chapters: list[epub.EpubHtml] = []
        for index, section in enumerate(sections, start=1):
            file_name = f"chap_{index}.xhtml"
            section.file_name = file_name
            content = render_section(section, image_map, lang_value)
            chapter = epub.EpubHtml(title=section.title, file_name=file_name, lang=lang_value)
            chapter.content = content
            book.add_item(chapter)
            chapters.append(chapter)

    book.toc = chapters
    book.spine = ["nav"] + chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(str(output_path), book, {})
    return sections
