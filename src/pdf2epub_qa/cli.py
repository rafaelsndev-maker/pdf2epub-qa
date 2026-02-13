from __future__ import annotations

import json
from pathlib import Path

import typer

from .converter import convert_pdf_to_epub
from .epub_builder import LAYOUT_FIXED, LAYOUT_REFLOW
from .qa import review_pdf_epub

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
    layout: str = typer.Option(
        LAYOUT_REFLOW,
        "--layout",
        help="Modo de layout: reflow (texto fluido) ou fixed (igual ao PDF).",
    ),
) -> None:
    _ensure_pdf(input_pdf)
    if layout not in {LAYOUT_REFLOW, LAYOUT_FIXED}:
        raise typer.BadParameter("layout invalido. Use reflow ou fixed.")
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
) -> None:
    _ensure_pdf(input_pdf)
    _ensure_epub(input_epub)
    output.parent.mkdir(parents=True, exist_ok=True)

    typer.echo("Rodando QA textual...")
    try:
        report = review_pdf_epub(input_pdf, input_epub)
    except RuntimeError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.secho(f"Relatorio salvo em {output}", fg=typer.colors.GREEN)
