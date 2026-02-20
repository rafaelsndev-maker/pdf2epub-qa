import asyncio
import json
from pathlib import Path
from uuid import uuid4

import fitz

import pdf2epub_qa.api as api_module
from pdf2epub_qa.converter import convert_pdf_to_epub


def make_run_dir() -> Path:
    run_dir = Path("tests_runtime") / f"api-editorial-chapter-review-{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def create_sample_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    path.write_bytes(doc.tobytes())
    doc.close()


def test_editorial_chapter_review_endpoints(monkeypatch):
    run_dir = make_run_dir()
    monkeypatch.setattr(api_module, "OUTPUT_DIR", run_dir)

    pdf_path = run_dir / "sample.pdf"
    epub_path = run_dir / "sample.epub"
    create_sample_pdf(pdf_path, "CAPITULO 1\nChecklist por capitulo via API.")
    convert_pdf_to_epub(pdf_path=pdf_path, output_path=epub_path, layout_mode="reflow")

    init_response = asyncio.run(
        api_module.editorial_chapter_review_init_endpoint(
            epub="/outputs/sample.epub",
            reviewer="Revisor API",
        )
    )
    assert init_response.status_code == 200
    init_payload = json.loads(init_response.body.decode("utf-8"))
    assert init_payload["ok"] is True
    assert init_payload["chapter_count"] >= 1

    mark_response = asyncio.run(
        api_module.editorial_chapter_review_mark_endpoint(
            epub="/outputs/sample.epub",
            chapter=1,
            status="approved",
            reviewer="Revisor API",
            notes="ok",
        )
    )
    assert mark_response.status_code == 200
    mark_payload = json.loads(mark_response.body.decode("utf-8"))
    assert mark_payload["ok"] is True
    assert mark_payload["review"]["approved_count"] >= 1
