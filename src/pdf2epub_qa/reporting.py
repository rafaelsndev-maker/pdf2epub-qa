from __future__ import annotations

from .utils import limit_text


def _compact_page_list(pages: list[int], max_items: int = 10) -> str:
    clean_pages = sorted({int(p) for p in pages if isinstance(p, int)})
    if not clean_pages:
        return "nenhuma"
    shown = clean_pages[:max_items]
    text = ", ".join(str(page) for page in shown)
    remaining = len(clean_pages) - len(shown)
    if remaining > 0:
        text += f" e mais {remaining}"
    return text


def _segment_examples(segments: list[dict], max_items: int = 3) -> list[str]:
    examples: list[str] = []
    for seg in segments[:max_items]:
        snippet = limit_text(str(seg.get("snippet", "")).strip(), 100)
        if not snippet:
            continue
        page = seg.get("page")
        if isinstance(page, int):
            examples.append(f"Pagina {page}: \"{snippet}\"")
        else:
            examples.append(f"Trecho: \"{snippet}\"")
    return examples


def build_user_summary(report: dict) -> dict:
    issues = report.get("issues", [])
    non_ok = [item for item in issues if item.get("status") != "ok"]
    no_text_pages = [item.get("page") for item in issues if item.get("status") == "no_text"]
    low_coverage_pages = [
        item.get("page") for item in issues if item.get("status") == "low_coverage"
    ]
    missing_page_pages = [
        item.get("page") for item in issues if item.get("status") == "missing_page"
    ]

    coverage = float(report.get("coverage_text_percent", 0.0))
    image_pdf = int(report.get("image_count_pdf", 0))
    image_epub = int(report.get("image_count_epub", 0))
    image_match = image_pdf == image_epub
    missing_segments = report.get("missing_segments", [])
    extra_segments = report.get("extra_segments", [])

    visual_qa = report.get("visual_qa", {})
    visual_status = visual_qa.get("status", "not_implemented")
    visual_percent = visual_qa.get("coverage_visual_percent")

    if coverage >= 98 and len(non_ok) == 0 and image_match:
        status = "excelente"
        message = "Conversao muito fiel ao arquivo original."
    elif coverage >= 95 and image_match:
        status = "bom"
        message = "Conversao boa, com pequenas diferencas em algumas paginas."
    else:
        status = "revisar"
        message = "Conversao concluida, mas recomenda-se revisar paginas sinalizadas."

    visual_label = "nao executado"
    if visual_status == "ok":
        visual_label = f"aprovado ({visual_percent}%)"
    elif visual_status == "differences_found":
        visual_label = f"diferencas detectadas ({visual_percent}%)"
    elif visual_status == "unsupported_layout":
        visual_label = "nao suportado para este tipo de EPUB"

    explicacao = [
        f"Texto aproveitado: {coverage:.2f}% do conteudo do PDF apareceu no EPUB.",
        f"Imagens: {image_epub} no EPUB para {image_pdf} no PDF.",
        f"Paginas com alerta: {len(non_ok)} de {len(issues)}.",
        (
            "Diferencas de texto detectadas: "
            f"{len(missing_segments)} trechos possivelmente faltando "
            f"e {len(extra_segments)} trechos extras."
        ),
        f"Comparacao visual: {visual_label}.",
    ]

    sinais_de_atencao: list[str] = []
    if no_text_pages:
        sinais_de_atencao.append(
            f"Paginas sem texto selecionavel no PDF: {_compact_page_list(no_text_pages)}."
        )
    if low_coverage_pages:
        sinais_de_atencao.append(
            f"Paginas com baixa cobertura textual: {_compact_page_list(low_coverage_pages)}."
        )
    if missing_page_pages:
        sinais_de_atencao.append(
            f"Paginas sem ancora mapeada no EPUB: {_compact_page_list(missing_page_pages)}."
        )
    if not image_match:
        sinais_de_atencao.append(
            f"Quantidade de imagens diferente: PDF={image_pdf} vs EPUB={image_epub}."
        )
    if visual_status == "differences_found":
        sinais_de_atencao.append(
            "Comparacao visual encontrou paginas com diferenca perceptivel."
        )
    if not sinais_de_atencao:
        sinais_de_atencao.append("Nenhum alerta relevante encontrado.")

    recomendacoes: list[str] = []
    if status == "excelente":
        recomendacoes.append("Arquivo pronto para publicacao.")
    else:
        recomendacoes.append(
            "Abra o EPUB final e revise as paginas sinalizadas antes de publicar."
        )
    if low_coverage_pages:
        pages_text = _compact_page_list(low_coverage_pages, max_items=8)
        recomendacoes.append(
            f"Priorize a revisao das paginas: {pages_text}."
        )
    if visual_status != "ok":
        recomendacoes.append(
            "Para manter visual mais proximo do PDF no leitor, prefira --layout fixed."
        )
    recomendacoes.append("Se encontrar falhas recorrentes, rode a conversao com OCR habilitado.")

    return {
        "status_geral": status,
        "mensagem": message,
        "texto_preservado_percent": round(coverage, 2),
        "imagens_preservadas": image_match,
        "imagens_pdf": image_pdf,
        "imagens_epub": image_epub,
        "paginas_total": len(issues),
        "paginas_com_alerta": len(non_ok),
        "paginas_sem_texto": no_text_pages[:20],
        "paginas_baixa_cobertura": low_coverage_pages[:20],
        "paginas_sem_ancora": missing_page_pages[:20],
        "visual_qa_status": visual_status,
        "visual_qa_percent": visual_percent,
        "diferencas_texto": {
            "trechos_faltando": len(missing_segments),
            "trechos_extras": len(extra_segments),
            "exemplos_faltando": _segment_examples(missing_segments),
            "exemplos_extras": _segment_examples(extra_segments),
        },
        "explicacao_simples": explicacao,
        "sinais_de_atencao": sinais_de_atencao,
        "recomendacoes": recomendacoes,
    }


def format_user_summary(summary: dict) -> str:
    lines = [
        f"Status geral: {summary.get('status_geral', 'desconhecido')}",
        f"Mensagem: {summary.get('mensagem', '')}",
        "",
        "Resumo simples:",
    ]
    for item in summary.get("explicacao_simples", []):
        lines.append(f"- {item}")

    lines.append("")
    lines.append("Pontos de atencao:")
    for item in summary.get("sinais_de_atencao", []):
        lines.append(f"- {item}")

    lines.append("")
    lines.append("Recomendacoes:")
    for item in summary.get("recomendacoes", []):
        lines.append(f"- {item}")

    diff = summary.get("diferencas_texto", {})
    examples_missing = diff.get("exemplos_faltando", [])
    examples_extra = diff.get("exemplos_extras", [])

    if examples_missing or examples_extra:
        lines.append("")
        lines.append("Exemplos de diferencas de texto:")
        for item in examples_missing:
            lines.append(f"- Faltando: {item}")
        for item in examples_extra:
            lines.append(f"- Extra: {item}")

    return "\n".join(lines).strip()
