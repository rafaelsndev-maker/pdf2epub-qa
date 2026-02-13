from pdf2epub_qa.api import build_user_summary


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


def test_build_user_summary_revisar():
    report = {
        "coverage_text_percent": 88.0,
        "image_count_pdf": 4,
        "image_count_epub": 1,
        "issues": [{"page": 1, "status": "missing_page"}],
        "visual_qa": {"status": "differences_found", "coverage_visual_percent": 70.0},
    }
    summary = build_user_summary(report)
    assert summary["status_geral"] == "revisar"
    assert summary["imagens_preservadas"] is False
    assert summary["paginas_sem_ancora"] == [1]
