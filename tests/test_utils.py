from pdf2epub_qa.utils import detect_heading, text_to_paragraphs


def test_text_to_paragraphs():
    text = "Linha 1\nLinha 2\n\nParagrafo 2"
    paragraphs = text_to_paragraphs(text)
    assert paragraphs == ["Linha 1 Linha 2", "Paragrafo 2"]


def test_detect_heading():
    text = "CAPITULO 1\nTexto"
    assert detect_heading(text) == "CAPITULO 1"


def test_detect_heading_non_first_line():
    text = "\n\nCAPITULO 2\nTexto"
    assert detect_heading(text) == "CAPITULO 2"
