import asyncio
import io
import json
from pathlib import Path
from uuid import uuid4

import fitz
from fastapi import UploadFile

import pdf2epub_qa.api as api_module


def make_pdf_bytes(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def make_run_dir() -> Path:
    run_dir = Path("tests_runtime") / f"api-batch-{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def test_batch_convert_upload_endpoint(monkeypatch):
    run_dir = make_run_dir()
    monkeypatch.setattr(api_module, "OUTPUT_DIR", run_dir)

    uploads = [
        UploadFile(filename="ok-1.pdf", file=io.BytesIO(make_pdf_bytes("PDF 1"))),
        UploadFile(filename="ok-2.pdf", file=io.BytesIO(make_pdf_bytes("PDF 2"))),
        UploadFile(filename="nao-pdf.txt", file=io.BytesIO(b"invalido")),
    ]

    response = asyncio.run(
        api_module.batch_convert_upload_endpoint(
            pdfs=uploads,
            lang="pt-BR",
            layout="reflow",
            workers=2,
            author=None,
        )
    )

    assert response.status_code == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["summary"]["total"] == 2
    assert payload["summary"]["sucesso"] == 2
    assert payload["summary"]["erros"] == 0
    assert payload["files"]["report_download_url"].startswith("/outputs/")
