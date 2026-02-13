from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .converter import convert_pdf_to_epub
from .qa import review_pdf_epub

OUTPUT_DIR = Path(os.getenv("PDF2EPUB_QA_OUTPUT_DIR", str(Path.cwd() / "outputs")))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="pdf2epub-qa")
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")


def _save_upload(upload: UploadFile, target: Path) -> None:
    with target.open("wb") as f:
        f.write(upload.file.read())


def _safe_stem(file_name: str) -> str:
    stem = Path(file_name).stem
    stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", stem).strip("-")
    return stem or "arquivo"


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
    }


@app.get("/", response_class=HTMLResponse)
async def ui() -> HTMLResponse:
    html = """
<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>pdf2epub-qa</title>
    <style>
      :root {
        --bg: #f4f7fb;
        --card: #ffffff;
        --text: #1b2430;
        --muted: #667085;
        --ok: #0f9d58;
        --warn: #f59e0b;
        --bad: #d92d20;
        --primary: #0b63ce;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
        color: var(--text);
        background: radial-gradient(circle at top right, #dbeafe, #f4f7fb 35%);
      }
      .wrap {
        max-width: 920px;
        margin: 28px auto;
        padding: 0 16px 24px;
      }
      .card {
        background: var(--card);
        border: 1px solid #e4e7ec;
        border-radius: 14px;
        padding: 18px;
        box-shadow: 0 8px 24px rgba(16, 24, 40, 0.06);
      }
      h1 {
        margin: 0 0 6px;
        font-size: 26px;
      }
      .sub {
        margin: 0 0 14px;
        color: var(--muted);
      }
      .grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 12px;
      }
      label {
        font-size: 13px;
        color: #344054;
        display: block;
        margin-bottom: 4px;
      }
      input, select, button {
        width: 100%;
        border-radius: 10px;
        border: 1px solid #d0d5dd;
        padding: 10px 12px;
        font-size: 14px;
      }
      button {
        background: var(--primary);
        color: white;
        border: none;
        font-weight: 600;
        cursor: pointer;
      }
      button:disabled {
        background: #98a2b3;
        cursor: wait;
      }
      .full { grid-column: 1 / -1; }
      .status {
        margin-top: 12px;
        padding: 10px 12px;
        border-radius: 10px;
        background: #eff6ff;
        color: #1849a9;
        font-size: 14px;
        display: none;
      }
      .result {
        margin-top: 16px;
        display: none;
      }
      .chips {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin: 10px 0 4px;
      }
      .chip {
        font-size: 12px;
        padding: 6px 10px;
        border-radius: 999px;
        background: #f2f4f7;
      }
      .chip.ok { background: #dcfce7; color: #166534; }
      .chip.warn { background: #fef3c7; color: #92400e; }
      .chip.bad { background: #fee2e2; color: #991b1b; }
      .links a {
        display: inline-block;
        margin-right: 10px;
        color: var(--primary);
        font-weight: 600;
        text-decoration: none;
      }
      pre {
        background: #0f172a;
        color: #e2e8f0;
        padding: 12px;
        border-radius: 10px;
        overflow: auto;
        font-size: 12px;
      }
      @media (max-width: 760px) {
        .grid { grid-template-columns: 1fr; }
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <h1>Conversor PDF para EPUB</h1>
        <p class="sub">Selecione o PDF, converta e veja o resumo do QA em linguagem simples.</p>
        <form id="form" class="grid">
          <div class="full">
            <label for="pdf">Arquivo PDF</label>
            <input id="pdf" name="pdf" type="file" accept=".pdf,application/pdf" required />
          </div>
          <div>
            <label for="title">Titulo (opcional)</label>
            <input id="title" name="title" type="text" placeholder="Nome do livro" />
          </div>
          <div>
            <label for="author">Autor (opcional)</label>
            <input id="author" name="author" type="text" placeholder="Nome do autor" />
          </div>
          <div>
            <label for="lang">Idioma</label>
            <select id="lang" name="lang">
              <option value="pt-BR">pt-BR</option>
              <option value="en">en</option>
            </select>
          </div>
          <div>
            <label for="layout">Layout</label>
            <select id="layout" name="layout">
              <option value="fixed" selected>fixed (visual igual ao PDF)</option>
              <option value="reflow">reflow (texto fluido)</option>
            </select>
          </div>
          <div class="full">
            <button id="submitBtn" type="submit">Converter e revisar</button>
          </div>
        </form>
        <div id="status" class="status"></div>
        <div id="result" class="result">
          <div class="links">
            <a id="epubLink" href="#" target="_blank" rel="noopener">Baixar EPUB</a>
            <a id="reportLink" href="#" target="_blank" rel="noopener">Baixar relatorio JSON</a>
          </div>
          <div id="chips" class="chips"></div>
          <pre id="summary"></pre>
        </div>
      </div>
    </div>
    <script>
      const form = document.getElementById("form");
      const statusBox = document.getElementById("status");
      const resultBox = document.getElementById("result");
      const summaryEl = document.getElementById("summary");
      const chipsEl = document.getElementById("chips");
      const submitBtn = document.getElementById("submitBtn");
      const epubLink = document.getElementById("epubLink");
      const reportLink = document.getElementById("reportLink");

      function showStatus(message, background = "#eff6ff", color = "#1849a9") {
        statusBox.style.display = "block";
        statusBox.style.background = background;
        statusBox.style.color = color;
        statusBox.textContent = message;
      }

      function chipClass(status) {
        if (status === "excelente") return "chip ok";
        if (status === "bom") return "chip warn";
        return "chip bad";
      }

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = new FormData(form);
        resultBox.style.display = "none";
        submitBtn.disabled = true;
        showStatus("Processando arquivo. Isso pode levar alguns segundos...");

        try {
          const response = await fetch("/convert-and-review", { method: "POST", body: data });
          const payload = await response.json();
          if (!response.ok) {
            throw new Error(payload.error || "Falha na conversao.");
          }

          showStatus("Conversao concluida com sucesso.", "#ecfdf3", "#067647");
          epubLink.href = payload.files.epub_download_url;
          reportLink.href = payload.files.report_download_url;

          const s = payload.summary;
          const visual = s.visual_qa_percent == null ? "n/a" : `${s.visual_qa_percent}%`;
          chipsEl.innerHTML = `
            <span class="${chipClass(s.status_geral)}">status: ${s.status_geral}</span>
            <span class="chip">texto: ${s.texto_preservado_percent}%</span>
            <span class="chip">paginas com alerta: ${s.paginas_com_alerta}</span>
            <span class="chip">visual: ${visual}</span>
            <span class="chip">imagens: ${s.imagens_pdf}/${s.imagens_epub}</span>
          `;

          summaryEl.textContent = JSON.stringify(payload.client_report, null, 2);
          resultBox.style.display = "block";
        } catch (err) {
          showStatus(err.message || "Erro inesperado.", "#fef3f2", "#b42318");
        } finally {
          submitBtn.disabled = false;
        }
      });
    </script>
  </body>
</html>
"""
    return HTMLResponse(content=html)


@app.post("/convert-and-review")
async def convert_and_review_endpoint(
    pdf: UploadFile = File(...),
    title: str | None = Form(None),
    author: str | None = Form(None),
    lang: str = Form("pt-BR"),
    layout: str = Form("fixed"),
) -> JSONResponse:
    input_name = pdf.filename or "input.pdf"
    if not input_name.lower().endswith(".pdf"):
        return JSONResponse(status_code=400, content={"error": "Envie um arquivo .pdf valido."})

    base_name = _safe_stem(input_name)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    token = uuid4().hex[:8]
    prefix = f"{base_name}-{stamp}-{token}"

    pdf_path = OUTPUT_DIR / f"{prefix}.pdf"
    epub_path = OUTPUT_DIR / f"{prefix}.epub"
    report_path = OUTPUT_DIR / f"{prefix}.report.json"

    try:
        _save_upload(pdf, pdf_path)
        convert_pdf_to_epub(
            pdf_path=pdf_path,
            output_path=epub_path,
            title=title,
            author=author,
            lang=lang,
            layout_mode=layout,
        )
        report = review_pdf_epub(pdf_path, epub_path)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": f"Falha interna: {exc}"})

    client_report = build_user_summary(report)
    response = {
        "ok": True,
        "files": {
            "output_dir": str(OUTPUT_DIR),
            "pdf_name": pdf_path.name,
            "epub_name": epub_path.name,
            "report_name": report_path.name,
            "epub_download_url": f"/outputs/{epub_path.name}",
            "report_download_url": f"/outputs/{report_path.name}",
        },
        "summary": client_report,
        "client_report": {
            "status_geral": client_report["status_geral"],
            "mensagem": client_report["mensagem"],
            "texto_preservado_percent": client_report["texto_preservado_percent"],
            "imagens_preservadas": client_report["imagens_preservadas"],
            "paginas_total": client_report["paginas_total"],
            "paginas_com_alerta": client_report["paginas_com_alerta"],
            "paginas_sem_texto": client_report["paginas_sem_texto"],
            "paginas_baixa_cobertura": client_report["paginas_baixa_cobertura"],
            "paginas_sem_ancora": client_report["paginas_sem_ancora"],
            "visual_qa_status": client_report["visual_qa_status"],
            "visual_qa_percent": client_report["visual_qa_percent"],
        },
    }
    return JSONResponse(content=response)


@app.post("/convert")
async def convert_endpoint(
    background_tasks: BackgroundTasks,
    pdf: UploadFile = File(...),
    title: str | None = Form(None),
    author: str | None = Form(None),
    lang: str = Form("pt-BR"),
    layout: str = Form("reflow"),
):
    tmpdir = Path(tempfile.mkdtemp())
    pdf_path = tmpdir / "input.pdf"
    epub_path = tmpdir / "output.epub"
    _save_upload(pdf, pdf_path)

    try:
        convert_pdf_to_epub(
            pdf_path,
            epub_path,
            title=title,
            author=author,
            lang=lang,
            layout_mode=layout,
        )
    except RuntimeError as exc:
        background_tasks.add_task(shutil.rmtree, tmpdir, ignore_errors=True)
        return JSONResponse(status_code=400, content={"error": str(exc)})
    background_tasks.add_task(shutil.rmtree, tmpdir, ignore_errors=True)
    return FileResponse(
        epub_path,
        media_type="application/epub+zip",
        filename="output.epub",
        background=background_tasks,
    )


@app.post("/review")
async def review_endpoint(
    background_tasks: BackgroundTasks,
    pdf: UploadFile = File(...),
    epub_file: UploadFile = File(..., alias="epub"),
):
    tmpdir = Path(tempfile.mkdtemp())
    pdf_path = tmpdir / "input.pdf"
    epub_path = tmpdir / "input.epub"
    _save_upload(pdf, pdf_path)
    _save_upload(epub_file, epub_path)

    try:
        report = review_pdf_epub(pdf_path, epub_path)
    except RuntimeError as exc:
        background_tasks.add_task(shutil.rmtree, tmpdir, ignore_errors=True)
        return JSONResponse(status_code=400, content={"error": str(exc)})
    background_tasks.add_task(shutil.rmtree, tmpdir, ignore_errors=True)
    return JSONResponse(content=report, background=background_tasks)
