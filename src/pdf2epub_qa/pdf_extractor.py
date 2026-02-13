from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path

import fitz

from .utils import env_flag


@dataclass
class ImageData:
    id: str
    page_index: int
    ext: str
    bytes: bytes


@dataclass
class PageData:
    index: int
    text: str
    images: list[ImageData]


@dataclass
class PdfContent:
    pages: list[PageData]
    title: str | None
    author: str | None
    language: str | None


def extract_pdf(pdf_path: Path) -> PdfContent:
    enable_ocr = env_flag("PDF2EPUB_QA_ENABLE_OCR", False)
    ocr_lang = os.getenv("PDF2EPUB_QA_OCR_LANG", "por+eng")

    doc = fitz.open(pdf_path)
    metadata = doc.metadata or {}
    pages: list[PageData] = []

    for i, page in enumerate(doc):
        text = page.get_text("text") or ""
        if enable_ocr and not text.strip():
            text = _ocr_page(page, ocr_lang) or text
        page_images: list[ImageData] = []
        for img_index, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            base = doc.extract_image(xref)
            image_bytes = base.get("image")
            ext = (base.get("ext") or "png").lower()
            if not image_bytes:
                continue
            image_id = f"p{i + 1}_img{img_index + 1}"
            page_images.append(ImageData(image_id, i, ext, image_bytes))
        pages.append(PageData(i, text, page_images))

    doc.close()

    return PdfContent(
        pages=pages,
        title=metadata.get("title") or None,
        author=metadata.get("author") or None,
        language=metadata.get("language") or None,
    )


def _ocr_page(page: fitz.Page, lang: str) -> str:
    try:
        import pytesseract
        from PIL import Image
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "OCR habilitado, mas dependencias opcionais nao estao instaladas. "
            "Instale com: pip install .[ocr] e garanta o Tesseract no sistema."
        ) from exc

    pix = page.get_pixmap(dpi=200, alpha=False)
    image = Image.open(io.BytesIO(pix.tobytes("png")))
    return pytesseract.image_to_string(image, lang=lang)
