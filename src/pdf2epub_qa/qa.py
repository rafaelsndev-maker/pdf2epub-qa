from __future__ import annotations

import io
import os
import posixpath
import re
from difflib import SequenceMatcher
from pathlib import Path

import ebooklib
import fitz
from bs4 import BeautifulSoup
from ebooklib import epub

from .pdf_extractor import extract_pdf
from .utils import env_flag, limit_text, normalize_text, tokenize


def normalize_epub_path(path: str) -> str:
    return posixpath.normpath(path.replace("\\", "/"))


def is_rendered_page_asset(file_name: str) -> bool:
    return normalize_epub_path(file_name).startswith("fixed_pages/")


def extract_epub_text(epub_path: Path) -> tuple[str, dict[int, str], int]:
    book = epub.read_epub(str(epub_path))
    page_text_map: dict[int, str] = {}
    full_text_parts: list[str] = []

    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for anchor in soup.find_all(id=re.compile(r"^page-\d+$")):
            page_id = anchor.get("id") or ""
            number = page_id.split("-", 1)[-1]
            anchor.insert_before(f"[[PAGE_{number}]]")

        text = soup.get_text("\n")
        parts = re.split(r"\[\[PAGE_(\d+)\]\]", text)
        if len(parts) == 1:
            full_text_parts.append(text)
            continue
        if parts[0].strip():
            full_text_parts.append(parts[0])
        for idx in range(1, len(parts), 2):
            page_num = int(parts[idx])
            segment = parts[idx + 1]
            existing = page_text_map.get(page_num, "")
            page_text_map[page_num] = (existing + "\n" + segment).strip()
            full_text_parts.append(segment)

    full_text = "\n".join(full_text_parts)
    image_count = 0
    for item in book.get_items():
        if not item.media_type or not item.media_type.startswith("image/"):
            continue
        if is_rendered_page_asset(item.get_name()):
            continue
        image_count += 1
    return full_text, page_text_map, image_count


def build_page_token_ranges(pages) -> tuple[list[str], list[tuple[int, int, int]]]:
    all_tokens: list[str] = []
    ranges: list[tuple[int, int, int]] = []
    cursor = 0
    for page in pages:
        tokens = tokenize(page.text)
        start = cursor
        cursor += len(tokens)
        end = cursor
        ranges.append((page.index + 1, start, end))
        all_tokens.extend(tokens)
    return all_tokens, ranges


def page_for_index(ranges: list[tuple[int, int, int]], index: int) -> int | None:
    for page_num, start, end in ranges:
        if start <= index < end:
            return page_num
    return None


def make_segment(tokens: list[str], start: int, end: int) -> dict[str, str]:
    before = " ".join(tokens[max(0, start - 5) : start])
    snippet = " ".join(tokens[start:end])
    after = " ".join(tokens[end : end + 5])
    return {
        "snippet": limit_text(snippet, 200),
        "context_before": limit_text(before, 120),
        "context_after": limit_text(after, 120),
    }


def review_pdf_epub(
    pdf_path: Path,
    epub_path: Path,
    page_threshold: float = 0.9,
) -> dict:
    pdf = extract_pdf(pdf_path)
    epub_text, epub_page_map, image_count_epub = extract_epub_text(epub_path)

    pdf_tokens, ranges = build_page_token_ranges(pdf.pages)
    epub_tokens = tokenize(epub_text)

    matcher = SequenceMatcher(None, pdf_tokens, epub_tokens)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    coverage = (matched / max(len(pdf_tokens), 1)) * 100

    missing_segments: list[dict] = []
    extra_segments: list[dict] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("delete", "replace") and i2 > i1:
            seg = make_segment(pdf_tokens, i1, i2)
            seg["page"] = page_for_index(ranges, i1)
            seg["token_count"] = i2 - i1
            missing_segments.append(seg)
        if tag in ("insert", "replace") and j2 > j1:
            seg = make_segment(epub_tokens, j1, j2)
            seg["page"] = None
            seg["token_count"] = j2 - j1
            extra_segments.append(seg)

    issues: list[dict] = []
    for page in pdf.pages:
        page_num = page.index + 1
        pdf_text = normalize_text(page.text)
        epub_page_text = normalize_text(epub_page_map.get(page_num, ""))
        if not pdf_text:
            issues.append(
                {
                    "page": page_num,
                    "coverage": 0.0,
                    "status": "no_text",
                    "notes": "Pagina sem texto selecionavel.",
                }
            )
            continue
        if not epub_page_text:
            issues.append(
                {
                    "page": page_num,
                    "coverage": 0.0,
                    "status": "missing_page",
                    "notes": "Nao encontrou ancora correspondente no EPUB.",
                }
            )
            continue
        ratio = SequenceMatcher(None, pdf_text, epub_page_text).ratio()
        status = "ok" if ratio >= page_threshold else "low_coverage"
        issues.append(
            {
                "page": page_num,
                "coverage": round(ratio, 4),
                "status": status,
                "notes": "" if status == "ok" else "Baixa cobertura por pagina.",
            }
        )

    image_count_pdf = sum(len(page.images) for page in pdf.pages)

    report = {
        "coverage_text_percent": round(coverage, 2),
        "missing_segments": missing_segments,
        "extra_segments": extra_segments,
        "image_count_pdf": image_count_pdf,
        "image_count_epub": image_count_epub,
        "issues": issues,
        "visual_qa": build_visual_qa(pdf_path, epub_path),
    }
    return report


def collect_fixed_layout_images(book: epub.EpubBook) -> dict[int, bytes]:
    item_by_name = {normalize_epub_path(item.get_name()): item for item in book.get_items()}
    page_images: dict[int, bytes] = {}

    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        doc_name = normalize_epub_path(item.get_name())
        doc_dir = posixpath.dirname(doc_name)
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for img in soup.find_all("img"):
            page_attr = img.get("data-pdf-page")
            src = img.get("src")
            if not page_attr or not src:
                continue
            try:
                page_num = int(page_attr)
            except ValueError:
                continue
            resolved = normalize_epub_path(posixpath.join(doc_dir, src))
            img_item = item_by_name.get(resolved)
            if img_item and page_num not in page_images:
                page_images[page_num] = img_item.get_content()

    if page_images:
        return page_images

    for item in book.get_items():
        if not item.media_type or not item.media_type.startswith("image/"):
            continue
        name = normalize_epub_path(item.get_name())
        match = re.match(r"^fixed_pages/page_(\d+)\.png$", name)
        if not match:
            continue
        page_images[int(match.group(1))] = item.get_content()
    return page_images


def build_visual_qa(pdf_path: Path, epub_path: Path) -> dict:
    if not env_flag("PDF2EPUB_QA_VISUAL", False):
        return {
            "status": "not_implemented",
            "notes": "Defina PDF2EPUB_QA_VISUAL=1 para comparar visualmente PDF e EPUB.",
        }

    try:
        from PIL import Image, ImageChops, ImageStat
    except Exception:
        return {
            "status": "dependency_missing",
            "notes": "Instale Pillow para QA visual: pip install -e \".[ocr]\"",
        }

    threshold = float(os.getenv("PDF2EPUB_QA_VISUAL_THRESHOLD", "0.985"))
    max_pages = int(os.getenv("PDF2EPUB_QA_VISUAL_MAX_PAGES", "10"))
    dpi = int(os.getenv("PDF2EPUB_QA_VISUAL_DPI", "144"))

    book = epub.read_epub(str(epub_path))
    page_images = collect_fixed_layout_images(book)
    if not page_images:
        return {
            "status": "unsupported_layout",
            "notes": "Comparacao visual completa exige EPUB fixed-layout gerado pelo conversor.",
        }

    doc = fitz.open(pdf_path)
    page_diffs: list[dict] = []
    scores: list[float] = []
    for page_num in sorted(page_images):
        if page_num > len(doc):
            continue
        if page_num > max_pages:
            break

        pdf_page = doc.load_page(page_num - 1)
        pdf_pix = pdf_page.get_pixmap(dpi=dpi, alpha=False)
        pdf_bytes = pdf_pix.tobytes("png")

        with Image.open(io.BytesIO(pdf_bytes)) as pdf_img_raw:
            with Image.open(io.BytesIO(page_images[page_num])) as epub_img_raw:
                pdf_img = pdf_img_raw.convert("L")
                epub_img = epub_img_raw.convert("L")
                if epub_img.size != pdf_img.size:
                    epub_img = epub_img.resize(pdf_img.size, Image.Resampling.LANCZOS)
                diff = ImageChops.difference(pdf_img, epub_img)
                mean_error = ImageStat.Stat(diff).mean[0]

        score = max(0.0, 1.0 - (mean_error / 255.0))
        scores.append(score)
        page_diffs.append(
            {
                "page": page_num,
                "similarity": round(score, 6),
                "status": "ok" if score >= threshold else "different",
                "mean_error": round(mean_error, 4),
            }
        )

    doc.close()
    if not scores:
        return {
            "status": "no_pages",
            "notes": "Nao foi possivel comparar paginas no intervalo configurado.",
        }

    overall = sum(scores) / len(scores)
    status = "ok" if all(page["status"] == "ok" for page in page_diffs) else "differences_found"
    return {
        "status": status,
        "threshold": threshold,
        "compared_pages": len(scores),
        "coverage_visual_percent": round(overall * 100, 2),
        "page_diffs": page_diffs,
        "notes": "Comparacao visual por pagina entre render do PDF e imagem da pagina no EPUB.",
    }
