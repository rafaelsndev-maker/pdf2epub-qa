from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from .batch import BatchItemResult, convert_pdfs_batch
from .converter import convert_pdf_to_epub
from .editorial import (
    create_chapter_review_template,
    mark_chapter_review,
    write_editorial_approval,
)
from .epub_builder import LAYOUT_AUTO, LAYOUT_FIXED, LAYOUT_REFLOW
from .qa import review_pdf_epub
from .reporting import build_user_summary, format_user_summary

app = typer.Typer(add_completion=False, help="PDF para EPUB com QA pagina por pagina")


def _ensure_pdf(path: Path) -> None:
    if not path.exists():
        raise typer.BadParameter("Arquivo nao encontrado.")
    if path.suffix.lower() != ".pdf":
        raise typer.BadParameter("Arquivo precisa ser .pdf.")


def _ensure_epub(path: Path) -> None:
    if not path.exists():
        raise typer.BadParameter("Arquivo nao encontrado.")
    if path.suffix.lower() != ".epub":
        raise typer.BadParameter("Arquivo precisa ser .epub.")


@app.command()
def convert(
    input_pdf: Path = typer.Argument(..., help="Caminho do PDF de entrada"),
    output: Path | None = typer.Option(None, "-o", "--output", help="Arquivo EPUB de saida"),
    title: str | None = typer.Option(None, "--title", help="Titulo do livro"),
    author: str | None = typer.Option(None, "--author", help="Autor do livro"),
    lang: str = typer.Option("pt-BR", "--lang", help="Idioma (pt-BR/en)"),
    publisher: str | None = typer.Option(None, "--publisher", help="Editora"),
    rights: str | None = typer.Option(None, "--rights", help="Direitos autorais"),
    description: str | None = typer.Option(None, "--description", help="Descricao editorial"),
    isbn: str | None = typer.Option(None, "--isbn", help="ISBN (opcional)"),
    collection: str | None = typer.Option(None, "--collection", help="Colecao/serie editorial"),
    layout: str = typer.Option(
        LAYOUT_AUTO,
        "--layout",
        help="Modo de layout: auto, reflow (texto fluido) ou fixed (igual ao PDF).",
    ),
) -> None:
    _ensure_pdf(input_pdf)
    if layout not in {LAYOUT_REFLOW, LAYOUT_FIXED, LAYOUT_AUTO}:
        raise typer.BadParameter("layout invalido. Use reflow, fixed ou auto.")
    output_path = output or input_pdf.with_suffix(".epub")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    typer.echo(f"Iniciando conversao: {input_pdf} -> {output_path}")
    try:
        result = convert_pdf_to_epub(
            pdf_path=input_pdf,
            output_path=output_path,
            title=title,
            author=author,
            lang=lang,
            publisher=publisher,
            rights=rights,
            description=description,
            isbn=isbn,
            collection=collection,
            layout_mode=layout,
        )
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    typer.secho(
        (
            f"Concluido: {result.output_path} (layout={result.layout_mode}, "
            f"paginas={result.pages}, imagens={result.images}, secoes={result.sections})"
        ),
        fg=typer.colors.GREEN,
    )


@app.command()
def review(
    input_pdf: Path = typer.Argument(..., help="Caminho do PDF"),
    input_epub: Path = typer.Argument(..., help="Caminho do EPUB"),
    output: Path = typer.Option("report.json", "-o", "--output", help="JSON de saida"),
    resumo_output: Path | None = typer.Option(
        None,
        "--resumo-output",
        "--human-output",
        help="Arquivo JSON simplificado para nao-tecnicos.",
    ),
    strict_epubcheck: bool = typer.Option(
        False,
        "--strict-epubcheck/--no-strict-epubcheck",
        help="Exige epubcheck aprovado no gate editorial.",
    ),
) -> None:
    _ensure_pdf(input_pdf)
    _ensure_epub(input_epub)
    output.parent.mkdir(parents=True, exist_ok=True)

    typer.echo("Rodando QA textual...")
    try:
        report = review_pdf_epub(input_pdf, input_epub, strict_epubcheck=strict_epubcheck)
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = build_user_summary(report)
    resumo_path = resumo_output or output.with_suffix(".leigo.json")
    resumo_path.parent.mkdir(parents=True, exist_ok=True)
    resumo_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    typer.secho(f"Relatorio salvo em {output}", fg=typer.colors.GREEN)
    typer.secho(f"Resumo leigo salvo em {resumo_path}", fg=typer.colors.GREEN)
    typer.echo("")
    typer.echo(format_user_summary(summary))


@app.command()
def approve(
    input_epub: Path = typer.Argument(..., help="Caminho do EPUB"),
    approver: str = typer.Option(..., "--approver", help="Responsavel pela aprovacao humana"),
    notes: str | None = typer.Option(None, "--notes", help="Observacoes da aprovacao"),
    output: Path | None = typer.Option(
        None, "-o", "--output", help="Arquivo JSON de aprovacao (padrao: <epub>.approval.json)"
    ),
) -> None:
    _ensure_epub(input_epub)
    target = output
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = write_editorial_approval(
            epub_path=input_epub,
            approver=approver,
            notes=notes,
            output_path=target,
        )
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho("Aprovacao editorial registrada.", fg=typer.colors.GREEN)
    typer.echo(f"Arquivo: {data['approval_file']}")


@app.command("chapter-review-init")
def chapter_review_init(
    input_epub: Path = typer.Argument(..., help="Caminho do EPUB"),
    reviewer: str | None = typer.Option(
        None, "--reviewer", help="Responsavel pela revisao por capitulo"
    ),
    output: Path | None = typer.Option(
        None, "-o", "--output", help="Arquivo de revisao (padrao: <epub>.review.json)"
    ),
) -> None:
    _ensure_epub(input_epub)
    target = output
    if target is not None:
        target.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = create_chapter_review_template(
            epub_path=input_epub,
            reviewer=reviewer,
            output_path=target,
        )
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho("Checklist de revisao por capitulo criado.", fg=typer.colors.GREEN)
    typer.echo(f"Arquivo: {data['review_file']}")
    typer.echo(f"Capitulos: {data['chapter_count']}")


@app.command("chapter-review-mark")
def chapter_review_mark(
    input_epub: Path = typer.Argument(..., help="Caminho do EPUB"),
    chapter: int = typer.Option(..., "--chapter", min=1, help="Numero do capitulo"),
    status: str = typer.Option(
        ...,
        "--status",
        help="Status: approved, rejected ou pending",
    ),
    reviewer: str | None = typer.Option(
        None, "--reviewer", help="Responsavel pela revisao por capitulo"
    ),
    notes: str | None = typer.Option(None, "--notes", help="Observacoes do capitulo"),
) -> None:
    _ensure_epub(input_epub)
    try:
        review = mark_chapter_review(
            epub_path=input_epub,
            chapter_index=chapter,
            status=status,
            reviewer=reviewer,
            notes=notes,
        )
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    typer.secho("Checklist por capitulo atualizado.", fg=typer.colors.GREEN)
    typer.echo(
        (
            f"Aprovados={review['approved_count']}, "
            f"Pendentes={review['pending_count']}, "
            f"Reprovados={review['rejected_count']}, "
            f"Total={review['total_count']}"
        )
    )


@app.command("release-check")
def release_check(
    input_pdf: Path = typer.Argument(..., help="Caminho do PDF"),
    input_epub: Path = typer.Argument(..., help="Caminho do EPUB"),
    output: Path = typer.Option(
        "editorial-report.json",
        "-o",
        "--output",
        help="Relatorio editorial de saida",
    ),
    strict_epubcheck: bool = typer.Option(
        True,
        "--strict-epubcheck/--no-strict-epubcheck",
        help="Exige epubcheck aprovado para liberar publicacao.",
    ),
) -> None:
    _ensure_pdf(input_pdf)
    _ensure_epub(input_epub)
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        report = review_pdf_epub(
            pdf_path=input_pdf,
            epub_path=input_epub,
            strict_epubcheck=strict_epubcheck,
        )
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    gate = report.get("editorial", {}).get("gate", {})
    release_ready = bool(gate.get("release_ready", False))
    blockers = [str(item) for item in gate.get("blockers", [])]
    score = float(gate.get("score", 0.0))

    if release_ready:
        typer.secho(
            "Gate editorial aprovado. Arquivo pronto para publicacao.",
            fg=typer.colors.GREEN,
        )
        typer.echo(f"Score editorial: {score:.2f}")
        typer.echo(f"Relatorio: {output}")
        return

    typer.secho("Gate editorial reprovado.", fg=typer.colors.RED)
    typer.echo(f"Score editorial: {score:.2f}")
    for blocker in blockers:
        typer.echo(f"- {blocker}")
    typer.echo(f"Relatorio: {output}")
    raise typer.Exit(code=1)


@app.command("batch-convert")
def batch_convert(
    inputs: list[Path] = typer.Argument(
        ...,
        help="Lista de PDFs e/ou pastas contendo PDFs.",
    ),
    output_dir: Path = typer.Option(
        Path("outputs") / "batch_epubs",
        "-o",
        "--output-dir",
        help="Pasta onde os EPUBs serao salvos.",
    ),
    report_output: Path = typer.Option(
        "batch-report.json",
        "-r",
        "--report",
        help="Relatorio JSON do lote (inclui arquivos com erro para retry).",
    ),
    layout: str = typer.Option(
        LAYOUT_AUTO,
        "--layout",
        help="Modo de layout: auto, reflow (texto fluido) ou fixed (igual ao PDF).",
    ),
    lang: str = typer.Option("pt-BR", "--lang", help="Idioma (pt-BR/en)"),
    author: str | None = typer.Option(None, "--author", help="Autor padrao do lote"),
    publisher: str | None = typer.Option(None, "--publisher", help="Editora padrao do lote"),
    rights: str | None = typer.Option(None, "--rights", help="Direitos padrao do lote"),
    description: str | None = typer.Option(
        None, "--description", help="Descricao editorial padrao do lote"
    ),
    isbn: str | None = typer.Option(None, "--isbn", help="ISBN padrao do lote"),
    collection: str | None = typer.Option(None, "--collection", help="Colecao padrao do lote"),
    workers: int = typer.Option(
        max(1, min(4, (os.cpu_count() or 2) - 1)),
        "--workers",
        min=1,
        help="Quantidade de conversoes em paralelo para evitar travamentos.",
    ),
    recursive: bool = typer.Option(
        True,
        "--recursive/--no-recursive",
        help="Buscar PDFs recursivamente ao informar pastas.",
    ),
) -> None:
    if layout not in {LAYOUT_REFLOW, LAYOUT_FIXED, LAYOUT_AUTO}:
        raise typer.BadParameter("layout invalido. Use reflow, fixed ou auto.")

    report_output.parent.mkdir(parents=True, exist_ok=True)

    def _progress(item: BatchItemResult, done: int, total: int) -> None:
        if item.status == "ok":
            typer.secho(
                f"[{done}/{total}] OK: {item.input_pdf} -> {item.output_epub}",
                fg=typer.colors.GREEN,
            )
        else:
            typer.secho(
                f"[{done}/{total}] ERRO: {item.input_pdf} ({item.error})",
                fg=typer.colors.YELLOW,
            )

    typer.echo("Iniciando conversao em lote...")
    try:
        report = convert_pdfs_batch(
            input_paths=inputs,
            output_dir=output_dir,
            workers=workers,
            recursive=recursive,
            lang=lang,
            layout_mode=layout,
            author=author,
            publisher=publisher,
            rights=rights,
            description=description,
            isbn=isbn,
            collection=collection,
            on_item_done=_progress,
        )
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc

    report_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    retry_output = report_output.with_suffix(".retry.json")
    retry_data = {
        "failed_pdfs": report["failed_pdfs"],
        "failed_count": report["failed_count"],
        "report_path": str(report_output),
        "retry_hint": report["retry_hint"],
    }
    retry_output.write_text(json.dumps(retry_data, ensure_ascii=False, indent=2), encoding="utf-8")

    success_count = int(report["success_count"])
    failed_count = int(report["failed_count"])
    total_count = int(report["input_count"])
    typer.secho(
        (
            f"Lote finalizado: total={total_count}, sucesso={success_count}, "
            f"erros={failed_count}, workers={workers}"
        ),
        fg=typer.colors.GREEN if failed_count == 0 else typer.colors.YELLOW,
    )
    typer.echo(f"Relatorio completo: {report_output}")
    typer.echo(f"Relatorio de retry: {retry_output}")

    if failed_count > 0:
        typer.secho(
            "Alguns arquivos falharam. Use failed_pdfs no JSON de retry para reconverter.",
            fg=typer.colors.YELLOW,
        )
