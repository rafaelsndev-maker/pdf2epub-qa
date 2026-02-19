import asyncio
import io
import json
from pathlib import Path
from uuid import uuid4

import fitz
from fastapi import UploadFile

import pdf2epub_qa.api as api_module
from pdf2epub_qa.converter import convert_pdf_to_epub


def make_run_dir() -> Path:
    run_dir = Path("tests_runtime") / f"api-epub-upload-{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def create_sample_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    path.write_bytes(doc.tobytes())
    doc.close()


def test_epub_upload_endpoint(monkeypatch):
    run_dir = make_run_dir()
    monkeypatch.setattr(api_module, "OUTPUT_DIR", run_dir)

    pdf_path = run_dir / "sample.pdf"
    source_epub_path = run_dir / "source.epub"
    create_sample_pdf(pdf_path, "CAPITULO 1\nTexto para upload no leitor.")
    convert_pdf_to_epub(pdf_path=pdf_path, output_path=source_epub_path, layout_mode="reflow")

    upload = UploadFile(filename="meu-livro.epub", file=io.BytesIO(source_epub_path.read_bytes()))
    response = asyncio.run(api_module.epub_upload_endpoint(epub_file=upload))

    assert response.status_code == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["epub_name"].endswith(".epub")
    assert payload["epub_download_url"].startswith("/outputs/")
    assert run_dir.joinpath(payload["epub_name"]).exists()


def test_epub_upload_endpoint_rejects_invalid_extension(monkeypatch):
    run_dir = make_run_dir()
    monkeypatch.setattr(api_module, "OUTPUT_DIR", run_dir)

    upload = UploadFile(filename="arquivo.txt", file=io.BytesIO(b"not-epub"))
    response = asyncio.run(api_module.epub_upload_endpoint(epub_file=upload))

    assert response.status_code == 400
    payload = json.loads(response.body.decode("utf-8"))
    assert "arquivo .epub" in payload["error"]

