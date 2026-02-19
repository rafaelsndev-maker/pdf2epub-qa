from pdf2epub_qa.converter import choose_layout_mode
from pdf2epub_qa.epub_builder import LAYOUT_FIXED, LAYOUT_REFLOW
from pdf2epub_qa.pdf_extractor import ImageData, PageData, PdfContent


def _make_page(index: int, word_count: int, with_image: bool = False) -> PageData:
    text = ("palavra " * word_count).strip()
    images: list[ImageData] = []
    if with_image:
        images.append(
            ImageData(
                id=f"p{index + 1}_img1",
                page_index=index,
                ext="png",
                bytes=b"fake-image",
            )
        )
    return PageData(index=index, text=text, images=images)


def _make_pdf(pages: list[PageData]) -> PdfContent:
    return PdfContent(pages=pages, title=None, author=None, language="pt-BR")


def test_auto_layout_prefers_reflow_for_dense_text():
    pdf = _make_pdf(
        [
            _make_page(0, 220),
            _make_page(1, 180),
            _make_page(2, 160),
        ]
    )

    assert choose_layout_mode(pdf) == LAYOUT_REFLOW


def test_auto_layout_prefers_fixed_for_image_heavy_content():
    pdf = _make_pdf(
        [
            _make_page(0, 8, with_image=True),
            _make_page(1, 0, with_image=True),
            _make_page(2, 10, with_image=True),
        ]
    )

    assert choose_layout_mode(pdf) == LAYOUT_FIXED


def test_auto_layout_prefers_fixed_when_no_text_is_extracted():
    pdf = _make_pdf(
        [
            _make_page(0, 0),
            _make_page(1, 0),
        ]
    )

    assert choose_layout_mode(pdf) == LAYOUT_FIXED
