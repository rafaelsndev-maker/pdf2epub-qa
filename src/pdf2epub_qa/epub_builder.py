from __future__ import annotations

import os
import re
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
LAYOUT_AUTO = "auto"

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


def _render_pdf_cover_png(source_pdf_path: Path | None) -> bytes | None:
    if source_pdf_path is None:
        return None
    try:
        doc = fitz.open(source_pdf_path)
    except Exception:
        return None
    try:
        if len(doc) == 0:
            return None
        dpi = int(os.getenv("PDF2EPUB_QA_COVER_DPI", "220"))
        pix = doc.load_page(0).get_pixmap(dpi=dpi, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def _image_alt_text(image_id: str) -> str:
    match = re.match(r"^p(\d+)_img(\d+)$", image_id)
    if not match:
        return f"Imagem {image_id}"
    return f"Imagem da pagina {match.group(1)}, item {match.group(2)}"


def _add_accessibility_metadata(book: epub.EpubBook) -> None:
    # Basic EPUB Accessibility 1.1 style metadata.
    book.add_metadata(None, "meta", "textual,visual", {"property": "schema:accessMode"})
    book.add_metadata(None, "meta", "textual", {"property": "schema:accessModeSufficient"})
    book.add_metadata(None, "meta", "alternativeText", {"property": "schema:accessibilityFeature"})
    book.add_metadata(
        None, "meta", "structuralNavigation", {"property": "schema:accessibilityFeature"}
    )
    book.add_metadata(None, "meta", "none", {"property": "schema:accessibilityHazard"})
    book.add_metadata(
        None,
        "meta",
        "EPUB gerado automaticamente com navegacao estrutural e marcacao por pagina.",
        {"property": "schema:accessibilitySummary"},
    )


def _add_editorial_metadata(
    book: epub.EpubBook,
    publisher: str | None,
    rights: str | None,
    description: str | None,
    isbn: str | None,
    collection: str | None,
) -> None:
    def _clean(value: object | None, env_name: str) -> str:
        if value is None:
            return str(os.getenv(env_name, "")).strip()
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    publisher_value = _clean(publisher, "PDF2EPUB_QA_PUBLISHER")
    rights_value = _clean(rights, "PDF2EPUB_QA_RIGHTS")
    description_value = _clean(description, "PDF2EPUB_QA_DESCRIPTION")
    collection_value = _clean(collection, "PDF2EPUB_QA_COLLECTION")
    isbn_value = _clean(isbn, "PDF2EPUB_QA_ISBN")

    if publisher_value:
        book.add_metadata("DC", "publisher", publisher_value)
    if rights_value:
        book.add_metadata("DC", "rights", rights_value)
    if description_value:
        book.add_metadata("DC", "description", description_value)
    if isbn_value:
        book.add_metadata("DC", "identifier", isbn_value, {"id": "isbn-id"})
    if collection_value:
        book.add_metadata(None, "meta", collection_value, {"property": "belongs-to-collection"})


def _build_editorial_navigation(
    sections: list[SectionData],
    chapters: list[epub.EpubHtml],
    frontmatter: list[epub.EpubHtml],
    lang: str,
) -> epub.EpubHtml | None:
    if not chapters and not frontmatter:
        return None

    page_links: list[tuple[int, str]] = []
    for section in sections:
        for page in section.pages:
            page_links.append((page.index + 1, f"{section.file_name}#page-{page.index + 1}"))

    page_links.sort(key=lambda item: item[0])
    start_href = (frontmatter[0].file_name if frontmatter else chapters[0].file_name)
    body_href = chapters[0].file_name if chapters else start_href
    lines = [
        (
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            f'xmlns:epub="http://www.idpf.org/2007/ops" lang="{escape(lang)}">'
        ),
        "<head>",
        '<meta charset="utf-8"/>',
        "<title>Navegacao Editorial</title>",
        "</head>",
        '<body epub:type="frontmatter">',
        "<h1>Navegacao Editorial</h1>",
        '<nav epub:type="landmarks" aria-label="Landmarks">',
        "<ol>",
        f'<li><a epub:type="frontmatter" href="{escape(start_href)}">Inicio</a></li>',
        f'<li><a epub:type="bodymatter" href="{escape(body_href)}">Inicio do conteudo</a></li>',
        "</ol>",
        "</nav>",
        '<nav epub:type="page-list" aria-label="Lista de paginas">',
        "<ol>",
    ]
    for page_num, href in page_links:
        lines.append(f'<li><a href="{escape(href)}">{page_num}</a></li>')
    lines.extend(["</ol>", "</nav>", "</body>", "</html>"])

    nav_doc = epub.EpubHtml(
        title="Navegacao Editorial",
        file_name="editorial_nav.xhtml",
        lang=lang,
    )
    nav_doc.content = "\n".join(lines)
    return nav_doc


def _build_frontmatter_docs(
    book: epub.EpubBook,
    lang: str,
    title: str,
    author: str,
    publisher: str | None,
    rights: str | None,
    description: str | None,
    isbn: str | None,
    collection: str | None,
    source_pdf_path: Path | None,
) -> list[epub.EpubHtml]:
    docs: list[epub.EpubHtml] = []
    cover_bytes = _render_pdf_cover_png(source_pdf_path)
    if cover_bytes:
        book.set_cover("cover.png", cover_bytes)
        cover_doc = epub.EpubHtml(title="Capa", file_name="cover_page.xhtml", lang=lang)
        cover_doc.content = "\n".join(
            [
                (
                    '<html xmlns="http://www.w3.org/1999/xhtml" '
                    f'xmlns:epub="http://www.idpf.org/2007/ops" lang="{escape(lang)}">'
                ),
                "<head>",
                '<meta charset="utf-8"/>',
                "<title>Capa</title>",
                "<style>",
                "html, body { margin: 0; padding: 0; }",
                "img { width: 100%; height: auto; display: block; }",
                "</style>",
                "</head>",
                '<body epub:type="cover">',
                '<img src="cover.png" alt="Capa do livro"/>',
                "</body>",
                "</html>",
            ]
        )
        book.add_item(cover_doc)
        docs.append(cover_doc)

    title_doc = epub.EpubHtml(title="Folha de rosto", file_name="title_page.xhtml", lang=lang)
    title_doc.content = "\n".join(
        [
            (
                '<html xmlns="http://www.w3.org/1999/xhtml" '
                f'xmlns:epub="http://www.idpf.org/2007/ops" lang="{escape(lang)}">'
            ),
            "<head>",
            '<meta charset="utf-8"/>',
            "<title>Folha de rosto</title>",
            "<style>",
            "body { font-family: serif; text-align: center; margin: 12% 8%; }",
            "h1 { font-size: 2em; margin-bottom: 0.4em; }",
            "p { font-size: 1.05em; }",
            "</style>",
            "</head>",
            '<body epub:type="titlepage">',
            f"<h1>{escape(title)}</h1>",
            f"<p>{escape(author)}</p>" if author else "",
            "</body>",
            "</html>",
        ]
    )
    book.add_item(title_doc)
    docs.append(title_doc)

    credits_lines = [
        (
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            f'xmlns:epub="http://www.idpf.org/2007/ops" lang="{escape(lang)}">'
        ),
        "<head>",
        '<meta charset="utf-8"/>',
        "<title>Creditos</title>",
        "<style>",
        "body { font-family: serif; margin: 8%; line-height: 1.5; }",
        "h1 { font-size: 1.4em; margin-bottom: 0.6em; }",
        "ul { padding-left: 1.2em; }",
        "</style>",
        "</head>",
        '<body epub:type="copyright-page">',
        "<h1>Creditos e dados editoriais</h1>",
        "<ul>",
    ]
    def _credit(label: str, value: str | None) -> None:
        if value and str(value).strip():
            credits_lines.append(f"<li><strong>{escape(label)}:</strong> {escape(str(value))}</li>")

    _credit("Titulo", title)
    _credit("Autor", author)
    _credit("Editora", publisher)
    _credit("ISBN", isbn)
    _credit("Colecao", collection)
    _credit("Direitos", rights)
    _credit("Descricao", description)
    credits_lines.extend(["</ul>", "</body>", "</html>"])
    credits_doc = epub.EpubHtml(title="Creditos", file_name="credits.xhtml", lang=lang)
    credits_doc.content = "\n".join(credits_lines)
    book.add_item(credits_doc)
    docs.append(credits_doc)
    return docs


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
        (
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            f'xmlns:epub="http://www.idpf.org/2007/ops" lang="{escape(lang)}">'
        ),
        "<head>",
        '<meta charset="utf-8"/>',
        f"<title>{escape(section.title)}</title>",
        "<style>",
        "body { font-family: serif; line-height: 1.5; }",
        "img { max-width: 100%; height: auto; }",
        "figure { margin: 1em 0; }",
        "</style>",
        "</head>",
        '<body epub:type="bodymatter">',
    ]

    lines.append('<section epub:type="chapter">')
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
                    (
                        '<figure><img '
                        f'src="{escape(src)}" alt="{escape(_image_alt_text(image.id))}"/></figure>'
                    )
                )

    lines.append("</section>")
    lines.append("</body>")
    lines.append("</html>")
    return "\n".join(lines)


def render_fixed_page(page_number: int, image_file_name: str, page_text: str, lang: str) -> str:
    hidden_text = "\n".join(f"<p>{escape(para)}</p>" for para in text_to_paragraphs(page_text))
    lines = [
        (
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            f'xmlns:epub="http://www.idpf.org/2007/ops" lang="{escape(lang)}">'
        ),
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
        '<body epub:type="bodymatter">',
        '<section epub:type="chapter">',
        f'<a id="page-{page_number}"></a>',
        '<div class="page-wrap">',
        (
            f'<img src="{escape(image_file_name)}" alt="Page {page_number}" '
            f'data-pdf-page="{page_number}"/>'
        ),
        "</div>",
        f'<div class="pdf-text">{hidden_text}</div>',
        "</section>",
        "</body>",
        "</html>",
    ]
    return "\n".join(lines)


def add_fixed_page_images(
    book: epub.EpubBook,
    source_pdf_path: Path,
) -> list[tuple[int, str, int, int]]:
    dpi = int(os.getenv("PDF2EPUB_QA_FIXED_DPI", "192"))
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
    publisher: str | None = None,
    rights: str | None = None,
    description: str | None = None,
    isbn: str | None = None,
    collection: str | None = None,
    layout_mode: str = LAYOUT_REFLOW,
    source_pdf_path: Path | None = None,
) -> list[SectionData]:
    book = epub.EpubBook()
    book.set_identifier(str(uuid4()))
    title_value = title or pdf.title or "Untitled"
    author_value = author or pdf.author or ""
    book.set_title(title_value)
    if author or pdf.author:
        book.add_author(author_value)
    book.set_language(lang or pdf.language or "pt-BR")
    _add_accessibility_metadata(book)
    _add_editorial_metadata(
        book=book,
        publisher=publisher,
        rights=rights,
        description=description,
        isbn=isbn,
        collection=collection,
    )

    lang_value = lang or pdf.language or "pt-BR"
    if layout_mode == LAYOUT_FIXED:
        if source_pdf_path is None:
            raise RuntimeError("Modo fixed requer caminho do PDF de origem.")
        sections, chapters = build_fixed_sections(book, pdf, source_pdf_path, lang_value)
    else:
        book.add_metadata(None, "meta", "reflowable", {"property": "rendition:layout"})
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

    frontmatter_docs = _build_frontmatter_docs(
        book=book,
        lang=lang_value,
        title=title_value,
        author=author_value,
        publisher=publisher,
        rights=rights,
        description=description,
        isbn=isbn,
        collection=collection,
        source_pdf_path=source_pdf_path,
    )
    editorial_nav = _build_editorial_navigation(
        sections=sections,
        chapters=chapters,
        frontmatter=frontmatter_docs,
        lang=lang_value,
    )
    if editorial_nav is not None:
        book.add_item(editorial_nav)

    toc_items = frontmatter_docs + chapters
    book.toc = toc_items
    book.spine = (
        ["nav"]
        + frontmatter_docs
        + chapters
        + ([editorial_nav] if editorial_nav is not None else [])
    )
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(str(output_path), book, {})
    return sections
