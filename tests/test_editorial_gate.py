from pathlib import Path
from uuid import uuid4

import fitz

from pdf2epub_qa.converter import convert_pdf_to_epub
from pdf2epub_qa.editorial import (
    create_chapter_review_template,
    mark_chapter_review,
    write_editorial_approval,
)
from pdf2epub_qa.qa import review_pdf_epub


def create_sample_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    path.write_bytes(doc.tobytes())
    doc.close()


def make_run_dir() -> Path:
    run_dir = Path("tests_runtime") / f"editorial-{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def test_editorial_gate_requires_human_approval(monkeypatch):
    run_dir = make_run_dir()
    pdf_path = run_dir / "sample.pdf"
    epub_path = run_dir / "sample.epub"
    create_sample_pdf(pdf_path, "CAPITULO 1\nTexto editorial de teste.")

    monkeypatch.setenv("PDF2EPUB_QA_PUBLISHER", "Editora Teste")
    monkeypatch.setenv("PDF2EPUB_QA_RIGHTS", "Todos os direitos reservados")
    monkeypatch.setenv("PDF2EPUB_QA_DESCRIPTION", "Descricao editorial de teste")
    monkeypatch.setenv("PDF2EPUB_QA_REQUIRE_CHAPTER_REVIEW", "1")
    monkeypatch.delenv("PDF2EPUB_QA_EPUBCHECK_JAR", raising=False)

    convert_pdf_to_epub(pdf_path=pdf_path, output_path=epub_path, layout_mode="reflow")
    report = review_pdf_epub(pdf_path=pdf_path, epub_path=epub_path)

    gate = report["editorial"]["gate"]
    assert gate["release_ready"] is False
    assert any("Aprovacao humana" in item for item in gate["blockers"])


def test_editorial_gate_can_pass_after_approval(monkeypatch):
    run_dir = make_run_dir()
    pdf_path = run_dir / "sample-approved.pdf"
    epub_path = run_dir / "sample-approved.epub"
    create_sample_pdf(pdf_path, "CAPITULO 1\nTexto editorial aprovado.")

    monkeypatch.setenv("PDF2EPUB_QA_PUBLISHER", "Editora Teste")
    monkeypatch.setenv("PDF2EPUB_QA_RIGHTS", "Todos os direitos reservados")
    monkeypatch.setenv("PDF2EPUB_QA_DESCRIPTION", "Descricao editorial de teste")
    monkeypatch.setenv("PDF2EPUB_QA_REQUIRE_CHAPTER_REVIEW", "1")
    monkeypatch.delenv("PDF2EPUB_QA_EPUBCHECK_JAR", raising=False)

    convert_pdf_to_epub(pdf_path=pdf_path, output_path=epub_path, layout_mode="reflow")
    create_chapter_review_template(epub_path=epub_path, reviewer="Revisor QA")
    mark_chapter_review(
        epub_path=epub_path,
        chapter_index=1,
        status="approved",
        reviewer="Revisor QA",
        notes="Capitulo revisado",
    )
    write_editorial_approval(epub_path=epub_path, approver="Revisor QA", notes="Aprovado")

    report = review_pdf_epub(pdf_path=pdf_path, epub_path=epub_path)
    gate = report["editorial"]["gate"]
    assert gate["release_ready"] is True
    assert gate["blockers"] == []
