from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from .converter import convert_pdf_to_epub
from .epub_builder import LAYOUT_FIXED, LAYOUT_REFLOW


@dataclass
class BatchItemResult:
    input_pdf: str
    output_epub: str
    status: str
    error: str | None
    pages: int | None
    images: int | None
    sections: int | None


def discover_pdf_inputs(paths: list[Path], recursive: bool = True) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            if path.suffix.lower() == ".pdf":
                files.append(path)
            continue
        if path.is_dir():
            iterator = path.rglob("*") if recursive else path.glob("*")
            files.extend(p for p in iterator if p.is_file() and p.suffix.lower() == ".pdf")
    unique: dict[str, Path] = {}
    for file_path in files:
        unique[str(file_path.resolve())] = file_path
    return sorted(unique.values(), key=lambda item: str(item).lower())


def _build_output_map(input_files: list[Path], output_dir: Path) -> dict[Path, Path]:
    mapping: dict[Path, Path] = {}
    used_names: set[str] = set()
    for file_path in input_files:
        base_name = file_path.stem
        output_name = f"{base_name}.epub"
        counter = 1
        while output_name.lower() in used_names:
            output_name = f"{base_name}-{counter}.epub"
            counter += 1
        used_names.add(output_name.lower())
        mapping[file_path] = output_dir / output_name
    return mapping


def _convert_one(
    pdf_path: Path,
    output_path: Path,
    title_from_filename: bool,
    author: str | None,
    lang: str,
    layout_mode: str,
) -> BatchItemResult:
    title = pdf_path.stem if title_from_filename else None
    try:
        result = convert_pdf_to_epub(
            pdf_path=pdf_path,
            output_path=output_path,
            title=title,
            author=author,
            lang=lang,
            layout_mode=layout_mode,
        )
        return BatchItemResult(
            input_pdf=str(pdf_path),
            output_epub=str(output_path),
            status="ok",
            error=None,
            pages=result.pages,
            images=result.images,
            sections=result.sections,
        )
    except Exception as exc:
        return BatchItemResult(
            input_pdf=str(pdf_path),
            output_epub=str(output_path),
            status="error",
            error=str(exc),
            pages=None,
            images=None,
            sections=None,
        )


def convert_pdfs_batch(
    input_paths: list[Path],
    output_dir: Path,
    workers: int = 2,
    recursive: bool = True,
    lang: str = "pt-BR",
    layout_mode: str = LAYOUT_REFLOW,
    author: str | None = None,
    title_from_filename: bool = True,
    on_item_done: Callable[[BatchItemResult, int, int], None] | None = None,
) -> dict:
    if layout_mode not in {LAYOUT_REFLOW, LAYOUT_FIXED}:
        raise RuntimeError("layout invalido. Use reflow ou fixed.")

    files = discover_pdf_inputs(input_paths, recursive=recursive)
    if not files:
        raise RuntimeError("Nenhum PDF encontrado nas entradas informadas.")

    output_dir.mkdir(parents=True, exist_ok=True)
    workers = max(1, workers)
    output_map = _build_output_map(files, output_dir)

    started_at = datetime.now(UTC)
    results: list[BatchItemResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _convert_one,
                pdf_path,
                output_map[pdf_path],
                title_from_filename,
                author,
                lang,
                layout_mode,
            ): pdf_path
            for pdf_path in files
        }
        for future in as_completed(futures):
            item = future.result()
            results.append(item)
            if on_item_done is not None:
                on_item_done(item, len(results), len(files))

    results.sort(key=lambda item: item.input_pdf.lower())
    failed = [item for item in results if item.status == "error"]
    success = [item for item in results if item.status == "ok"]

    finished_at = datetime.now(UTC)
    duration_s = (finished_at - started_at).total_seconds()

    return {
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round(duration_s, 3),
        "workers": workers,
        "layout": layout_mode,
        "lang": lang,
        "output_dir": str(output_dir),
        "input_count": len(files),
        "success_count": len(success),
        "failed_count": len(failed),
        "failed_pdfs": [item.input_pdf for item in failed],
        "results": [asdict(item) for item in results],
        "retry_hint": {
            "message": "Rode novamente apenas os arquivos em failed_pdfs.",
            "example": "pdf2epub batch-convert <pdfs_com_erro> -o <pasta_saida> --layout reflow",
        },
    }
