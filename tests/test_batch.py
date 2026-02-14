from pathlib import Path
from uuid import uuid4

import fitz
from typer.testing import CliRunner

from pdf2epub_qa.batch import convert_pdfs_batch
from pdf2epub_qa.cli import app


def create_sample_pdf(path: Path, text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    path.write_bytes(doc.tobytes())
    doc.close()


def make_run_dir() -> Path:
    run_dir = Path("tests_runtime") / f"batch-{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def test_batch_convert_with_failure_report():
    run_dir = make_run_dir()
    output_dir = run_dir / "epubs"

    create_sample_pdf(run_dir / "ok-1.pdf", "Primeiro PDF")
    create_sample_pdf(run_dir / "ok-2.pdf", "Segundo PDF")
    (run_dir / "quebrado.pdf").write_text("nao e um pdf valido", encoding="utf-8")

    report = convert_pdfs_batch(
        input_paths=[run_dir],
        output_dir=output_dir,
        workers=2,
        recursive=True,
    )

    assert report["input_count"] == 3
    assert report["success_count"] == 2
    assert report["failed_count"] == 1
    assert len(report["failed_pdfs"]) == 1
    assert output_dir.joinpath("ok-1.epub").exists()
    assert output_dir.joinpath("ok-2.epub").exists()


def test_batch_convert_cli_writes_retry_json():
    run_dir = make_run_dir()
    output_dir = run_dir / "epubs"
    report_path = run_dir / "batch-report.json"

    create_sample_pdf(run_dir / "ok.pdf", "PDF de teste")
    (run_dir / "erro.pdf").write_text("invalido", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "batch-convert",
            str(run_dir),
            "--output-dir",
            str(output_dir),
            "--report",
            str(report_path),
            "--workers",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert report_path.exists()
    assert report_path.with_suffix(".retry.json").exists()
