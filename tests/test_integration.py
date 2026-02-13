import fitz

from pdf2epub_qa.converter import convert_pdf_to_epub
from pdf2epub_qa.qa import review_pdf_epub


def create_sample_pdf(path):
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "CAPITULO 1\nOla mundo\nLinha 2")
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Continuacao do texto.\nFim.")
    doc.save(path)
    doc.close()


def test_convert_and_review(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    epub_path = tmp_path / "sample.epub"

    create_sample_pdf(pdf_path)
    result = convert_pdf_to_epub(pdf_path, epub_path, title="Teste", author="Autor", lang="pt-BR")

    assert epub_path.exists()

    report = review_pdf_epub(pdf_path, epub_path)

    assert report["image_count_pdf"] == 0
    assert report["image_count_epub"] == 0
    assert report["coverage_text_percent"] >= 50
    assert len(report["issues"]) == result.pages


def test_convert_fixed_layout_and_review(tmp_path):
    pdf_path = tmp_path / "sample_fixed.pdf"
    epub_path = tmp_path / "sample_fixed.epub"

    create_sample_pdf(pdf_path)
    result = convert_pdf_to_epub(
        pdf_path,
        epub_path,
        title="Teste Fixed",
        author="Autor",
        lang="pt-BR",
        layout_mode="fixed",
    )

    assert epub_path.exists()
    assert result.layout_mode == "fixed"

    report = review_pdf_epub(pdf_path, epub_path)
    assert report["coverage_text_percent"] >= 50
