import asyncio
import json
from pathlib import Path
from uuid import uuid4

import fitz

import pdf2epub_qa.api as api_module
from pdf2epub_qa.converter import convert_pdf_to_epub


def make_run_dir() -> Path:
    run_dir = Path("tests_runtime") / f"api-editorial-approve-{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def create_sample_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    path.write_bytes(doc.tobytes())
    doc.close()


def test_editorial_approve_endpoint(monkeypatch):
    run_dir = make_run_dir()
    monkeypatch.setattr(api_module, "OUTPUT_DIR", run_dir)

    pdf_path = run_dir / "sample.pdf"
    epub_path = run_dir / "sample.epub"
    create_sample_pdf(pdf_path, "CAPITULO 1\nAprovacao via endpoint.")
    convert_pdf_to_epub(pdf_path=pdf_path, output_path=epub_path, layout_mode="reflow")

    response = asyncio.run(
        api_module.editorial_approve_endpoint(
            epub="/outputs/sample.epub",
            approver="Revisor API",
            notes="Aprovado",
        )
    )
    assert response.status_code == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["status"] == "approved"
    assert run_dir.joinpath("sample.epub.approval.json").exists()
