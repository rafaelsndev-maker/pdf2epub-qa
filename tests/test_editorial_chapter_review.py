from pathlib import Path
from uuid import uuid4

import fitz

from pdf2epub_qa.converter import convert_pdf_to_epub
from pdf2epub_qa.editorial import (
    create_chapter_review_template,
    load_chapter_review,
    mark_chapter_review,
)


def create_sample_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    path.write_bytes(doc.tobytes())
    doc.close()


def make_run_dir() -> Path:
    run_dir = Path("tests_runtime") / f"chapter-review-{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def test_chapter_review_template_and_mark_flow():
    run_dir = make_run_dir()
    pdf_path = run_dir / "sample.pdf"
    epub_path = run_dir / "sample.epub"
    create_sample_pdf(pdf_path, "CAPITULO 1\nTexto para revisao por capitulo.")
    convert_pdf_to_epub(pdf_path=pdf_path, output_path=epub_path, layout_mode="reflow")

    created = create_chapter_review_template(epub_path=epub_path, reviewer="QA")
    assert created["chapter_count"] >= 1

    mark_chapter_review(
        epub_path=epub_path,
        chapter_index=1,
        status="approved",
        reviewer="QA",
        notes="ok",
    )
    review = load_chapter_review(epub_path=epub_path)
    assert review["approved_count"] >= 1
    assert review["total_count"] >= 1
