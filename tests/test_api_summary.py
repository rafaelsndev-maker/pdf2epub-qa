from pdf2epub_qa.reporting import build_user_summary, format_user_summary


def test_build_user_summary_bom():
    report = {
        "coverage_text_percent": 96.2,
        "image_count_pdf": 2,
        "image_count_epub": 2,
        "issues": [
            {"page": 1, "status": "ok"},
            {"page": 2, "status": "low_coverage"},
            {"page": 3, "status": "no_text"},
        ],
        "visual_qa": {"status": "ok", "coverage_visual_percent": 99.1},
    }
    summary = build_user_summary(report)
    assert summary["status_geral"] == "bom"
    assert summary["paginas_com_alerta"] == 2
    assert summary["paginas_sem_texto"] == [3]
    assert summary["paginas_baixa_cobertura"] == [2]
    assert "explicacao_simples" in summary
    assert len(summary["explicacao_simples"]) >= 3


def test_build_user_summary_revisar():
    report = {
        "coverage_text_percent": 88.0,
        "image_count_pdf": 4,
        "image_count_epub": 1,
        "issues": [{"page": 1, "status": "missing_page"}],
        "missing_segments": [{"page": 1, "snippet": "trecho faltando"}],
        "extra_segments": [{"snippet": "trecho extra"}],
        "visual_qa": {"status": "differences_found", "coverage_visual_percent": 70.0},
    }
    summary = build_user_summary(report)
    assert summary["status_geral"] == "revisar"
    assert summary["imagens_preservadas"] is False
    assert summary["paginas_sem_ancora"] == [1]
    assert summary["diferencas_texto"]["trechos_faltando"] == 1
    assert summary["diferencas_texto"]["trechos_extras"] == 1
    assert summary["sinais_de_atencao"]


def test_format_user_summary_text():
    summary = {
        "status_geral": "bom",
        "mensagem": "Conversao boa",
        "explicacao_simples": ["Texto: 97%", "Imagens: 2/2"],
        "sinais_de_atencao": ["Pagina 10 com alerta."],
        "recomendacoes": ["Revisar pagina 10."],
        "diferencas_texto": {"exemplos_faltando": ["Pagina 10: \"abc\""], "exemplos_extras": []},
    }
    rendered = format_user_summary(summary)
    assert "Status geral: bom" in rendered
    assert "O que fazer agora" not in rendered
    assert "Recomendacoes:" in rendered
    assert "Faltando: Pagina 10: \"abc\"" in rendered
