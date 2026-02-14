from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .batch import convert_pdfs_batch
from .converter import convert_pdf_to_epub
from .qa import review_pdf_epub
from .reporting import build_user_summary

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


def _output_url(path: Path) -> str:
    rel = path.resolve().relative_to(OUTPUT_DIR.resolve())
    return "/outputs/" + "/".join(rel.parts)


def _save_batch_uploads(
    pdfs: list[UploadFile], input_dir: Path
) -> tuple[list[Path], dict[str, str]]:
    input_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[Path] = []
    original_name_by_saved: dict[str, str] = {}
    used_names: set[str] = set()

    for upload in pdfs:
        original_name = upload.filename or "input.pdf"
        if not original_name.lower().endswith(".pdf"):
            continue
        safe_stem = _safe_stem(original_name)
        candidate = f"{safe_stem}.pdf"
        idx = 1
        while candidate.lower() in used_names:
            candidate = f"{safe_stem}-{idx}.pdf"
            idx += 1
        used_names.add(candidate.lower())

        target = input_dir / candidate
        _save_upload(upload, target)
        saved_paths.append(target)
        original_name_by_saved[str(target)] = original_name

    return saved_paths, original_name_by_saved


def _batch_status(success_count: int, failed_count: int) -> str:
    if failed_count == 0:
        return "ok"
    if success_count > 0:
        return "parcial"
    return "erro"


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
        max-width: 980px;
        margin: 28px auto;
        padding: 0 16px 24px;
      }
      .card {
        background: var(--card);
        border: 1px solid #e4e7ec;
        border-radius: 14px;
        padding: 18px;
        box-shadow: 0 8px 24px rgba(16, 24, 40, 0.06);
        margin-bottom: 14px;
      }
      h1 {
        margin: 0 0 6px;
        font-size: 26px;
      }
      h2 {
        margin: 0 0 6px;
        font-size: 20px;
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
        <p class="sub">
          Agora voce pode converter 1 PDF ou varios PDFs em massa, direto no navegador.
        </p>
      </div>

      <div class="card">
        <h2>Conversao unica + QA</h2>
        <p class="sub">Converte um PDF, roda QA e mostra o resumo leigo.</p>
        <form id="singleForm" class="grid">
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
            <button id="singleBtn" type="submit">Converter e revisar</button>
          </div>
        </form>
        <div id="singleStatus" class="status"></div>
        <div id="singleResult" class="result">
          <div class="links">
            <a id="epubLink" href="#" target="_blank" rel="noopener">Baixar EPUB</a>
            <a id="reportLink" href="#" target="_blank" rel="noopener">Baixar relatorio JSON</a>
          </div>
          <div id="singleChips" class="chips"></div>
          <pre id="singleSummary"></pre>
        </div>
      </div>

      <div class="card">
        <h2>Conversao em massa (lote)</h2>
        <p class="sub">Selecione varios PDFs ou uma pasta e converta tudo de uma vez.</p>
        <form id="batchForm" class="grid">
          <div class="full">
            <label for="batchPdfs">PDFs (multiplos ou pasta)</label>
            <input
              id="batchPdfs"
              name="pdfs"
              type="file"
              multiple
              webkitdirectory
              directory
              accept=".pdf,application/pdf"
              required
            />
          </div>
          <div>
            <label for="batchLang">Idioma</label>
            <select id="batchLang" name="lang">
              <option value="pt-BR">pt-BR</option>
              <option value="en">en</option>
            </select>
          </div>
          <div>
            <label for="batchLayout">Layout</label>
            <select id="batchLayout" name="layout">
              <option value="reflow" selected>reflow (mais leve)</option>
              <option value="fixed">fixed (visual igual ao PDF)</option>
            </select>
          </div>
          <div>
            <label for="batchWorkers">Workers paralelos</label>
            <input id="batchWorkers" name="workers" type="number" min="1" max="8" value="2" />
          </div>
          <div>
            <label for="batchAuthor">Autor padrao (opcional)</label>
            <input id="batchAuthor" name="author" type="text" placeholder="Autor para todos" />
          </div>
          <div class="full">
            <button id="batchBtn" type="submit">Converter em massa</button>
          </div>
        </form>
        <div id="batchStatus" class="status"></div>
        <div id="batchResult" class="result">
          <div class="links">
            <a id="batchZipLink" href="#" target="_blank" rel="noopener">Baixar EPUBs (.zip)</a>
            <a id="batchReportLink" href="#" target="_blank" rel="noopener">
              Baixar relatorio do lote
            </a>
            <a id="batchRetryLink" href="#" target="_blank" rel="noopener">
              Baixar relatorio de retry
            </a>
          </div>
          <div id="batchChips" class="chips"></div>
          <pre id="batchSummary"></pre>
        </div>
      </div>
    </div>

    <script>
      const singleForm = document.getElementById("singleForm");
      const singleStatus = document.getElementById("singleStatus");
      const singleResult = document.getElementById("singleResult");
      const singleBtn = document.getElementById("singleBtn");
      const singleChips = document.getElementById("singleChips");
      const singleSummary = document.getElementById("singleSummary");
      const epubLink = document.getElementById("epubLink");
      const reportLink = document.getElementById("reportLink");

      const batchForm = document.getElementById("batchForm");
      const batchStatus = document.getElementById("batchStatus");
      const batchResult = document.getElementById("batchResult");
      const batchBtn = document.getElementById("batchBtn");
      const batchChips = document.getElementById("batchChips");
      const batchSummary = document.getElementById("batchSummary");
      const batchZipLink = document.getElementById("batchZipLink");
      const batchReportLink = document.getElementById("batchReportLink");
      const batchRetryLink = document.getElementById("batchRetryLink");

      function showStatus(el, message, background = "#eff6ff", color = "#1849a9") {
        el.style.display = "block";
        el.style.background = background;
        el.style.color = color;
        el.textContent = message;
      }

      function chipClass(status) {
        if (status === "excelente" || status === "ok") return "chip ok";
        if (status === "bom" || status === "parcial") return "chip warn";
        return "chip bad";
      }

      function renderSimpleSummary(summary) {
        const lines = [];
        lines.push(`Status: ${summary.status_geral}`);
        lines.push(`Mensagem: ${summary.mensagem}`);
        lines.push("");
        lines.push("O que este resultado significa:");
        for (const item of (summary.explicacao_simples || [])) lines.push(`- ${item}`);
        lines.push("");
        lines.push("Pontos de atencao:");
        for (const item of (summary.sinais_de_atencao || [])) lines.push(`- ${item}`);
        lines.push("");
        lines.push("O que fazer agora:");
        for (const item of (summary.recomendacoes || [])) lines.push(`- ${item}`);
        return lines.join("\\n");
      }

      function renderBatchSummary(summary) {
        const lines = [];
        lines.push(`Status: ${summary.status_geral}`);
        lines.push(`Mensagem: ${summary.mensagem}`);
        lines.push("");
        lines.push(`Total de PDFs: ${summary.total}`);
        lines.push(`Sucesso: ${summary.sucesso}`);
        lines.push(`Erros: ${summary.erros}`);
        lines.push(`Workers: ${summary.workers}`);
        if ((summary.falhas || []).length > 0) {
          lines.push("");
          lines.push("Arquivos com erro:");
          for (const item of summary.falhas.slice(0, 20)) lines.push(`- ${item}`);
          if (summary.falhas.length > 20) lines.push(`- e mais ${summary.falhas.length - 20}`);
        }
        lines.push("");
        lines.push("Dica: baixe o relatorio de retry e reenvie somente os PDFs com erro.");
        return lines.join("\\n");
      }

      singleForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const data = new FormData(singleForm);
        singleResult.style.display = "none";
        singleBtn.disabled = true;
        showStatus(singleStatus, "Processando arquivo. Isso pode levar alguns segundos...");

        try {
          const response = await fetch("/convert-and-review", { method: "POST", body: data });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Falha na conversao.");

          showStatus(singleStatus, "Conversao concluida com sucesso.", "#ecfdf3", "#067647");
          epubLink.href = payload.files.epub_download_url;
          reportLink.href = payload.files.report_download_url;

          const s = payload.summary;
          const visual = s.visual_qa_percent == null ? "n/a" : `${s.visual_qa_percent}%`;
          singleChips.innerHTML = `
            <span class="${chipClass(s.status_geral)}">status: ${s.status_geral}</span>
            <span class="chip">texto: ${s.texto_preservado_percent}%</span>
            <span class="chip">paginas com alerta: ${s.paginas_com_alerta}</span>
            <span class="chip">visual: ${visual}</span>
            <span class="chip">imagens: ${s.imagens_pdf}/${s.imagens_epub}</span>
          `;

          singleSummary.textContent = renderSimpleSummary(payload.client_report);
          singleResult.style.display = "block";
        } catch (err) {
          showStatus(singleStatus, err.message || "Erro inesperado.", "#fef3f2", "#b42318");
        } finally {
          singleBtn.disabled = false;
        }
      });

      batchForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const filesInput = document.getElementById("batchPdfs");
        if (!filesInput.files || filesInput.files.length === 0) {
          showStatus(batchStatus, "Selecione pelo menos 1 PDF.", "#fef3f2", "#b42318");
          return;
        }

        const data = new FormData(batchForm);
        batchResult.style.display = "none";
        batchBtn.disabled = true;
        showStatus(batchStatus, "Processando lote. Nao feche esta pagina...");

        try {
          const response = await fetch("/batch-convert-upload", { method: "POST", body: data });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Falha na conversao em massa.");

          showStatus(batchStatus, "Lote finalizado.", "#ecfdf3", "#067647");
          if (payload.files.zip_download_url) {
            batchZipLink.href = payload.files.zip_download_url;
            batchZipLink.style.display = "inline-block";
          } else {
            batchZipLink.style.display = "none";
          }
          batchReportLink.href = payload.files.report_download_url;
          batchRetryLink.href = payload.files.retry_download_url;

          const s = payload.summary;
          batchChips.innerHTML = `
            <span class="${chipClass(s.status_geral)}">status: ${s.status_geral}</span>
            <span class="chip">total: ${s.total}</span>
            <span class="chip">sucesso: ${s.sucesso}</span>
            <span class="chip">erros: ${s.erros}</span>
            <span class="chip">workers: ${s.workers}</span>
          `;

          batchSummary.textContent = renderBatchSummary(s);
          batchResult.style.display = "block";
        } catch (err) {
          showStatus(batchStatus, err.message || "Erro inesperado.", "#fef3f2", "#b42318");
        } finally {
          batchBtn.disabled = false;
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
            "epub_download_url": _output_url(epub_path),
            "report_download_url": _output_url(report_path),
        },
        "summary": client_report,
        "client_report": client_report,
    }
    return JSONResponse(content=response)


@app.post("/batch-convert-upload")
async def batch_convert_upload_endpoint(
    pdfs: list[UploadFile] = File(...),
    lang: str = Form("pt-BR"),
    layout: str = Form("reflow"),
    workers: int = Form(2),
    author: str | None = Form(None),
) -> JSONResponse:
    if layout not in {"reflow", "fixed"}:
        return JSONResponse(
            status_code=400, content={"error": "layout invalido. Use reflow ou fixed."}
        )

    max_workers = max(1, min(8, os.cpu_count() or 2))
    workers = max(1, min(int(workers), max_workers))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    token = uuid4().hex[:8]
    run_dir = OUTPUT_DIR / f"batch-{stamp}-{token}"
    input_dir = run_dir / "inputs"
    epub_dir = run_dir / "epubs"
    report_path = run_dir / "batch-report.json"
    retry_path = run_dir / "batch-report.retry.json"
    zip_path = run_dir / "batch-epubs.zip"

    try:
        saved_paths, original_name_by_saved = _save_batch_uploads(pdfs, input_dir)
        if not saved_paths:
            return JSONResponse(
                status_code=400,
                content={"error": "Nenhum PDF valido enviado. Selecione arquivos .pdf."},
            )

        report = convert_pdfs_batch(
            input_paths=saved_paths,
            output_dir=epub_dir,
            workers=workers,
            recursive=False,
            lang=lang,
            layout_mode=layout,
            author=author,
        )

        result_items: list[dict] = []
        failed_names: list[str] = []
        for item in report["results"]:
            original_name = original_name_by_saved.get(
                item["input_pdf"], Path(item["input_pdf"]).name
            )
            ok = item["status"] == "ok"
            row = {
                "input_name": original_name,
                "status": item["status"],
                "error": item["error"],
                "pages": item["pages"],
                "images": item["images"],
                "sections": item["sections"],
                "output_epub_name": Path(item["output_epub"]).name if ok else None,
                "output_epub_url": _output_url(Path(item["output_epub"])) if ok else None,
            }
            result_items.append(row)
            if not ok:
                failed_names.append(original_name)

        api_report = {
            "started_at": report["started_at"],
            "finished_at": report["finished_at"],
            "duration_seconds": report["duration_seconds"],
            "workers": report["workers"],
            "layout": report["layout"],
            "lang": report["lang"],
            "output_dir": report["output_dir"],
            "input_count": report["input_count"],
            "success_count": report["success_count"],
            "failed_count": report["failed_count"],
            "failed_input_names": failed_names,
            "results": result_items,
        }
        report_path.write_text(
            json.dumps(api_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        retry_data = {
            "failed_input_names": failed_names,
            "failed_count": len(failed_names),
            "message": "Reenvie apenas estes PDFs no modo de lote para tentar novamente.",
        }
        retry_path.write_text(
            json.dumps(retry_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        epub_files = sorted(epub_dir.glob("*.epub"))
        zip_url = None
        if epub_files:
            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for epub_file in epub_files:
                    zf.write(epub_file, arcname=epub_file.name)
            zip_url = _output_url(zip_path)

        summary = {
            "status_geral": _batch_status(report["success_count"], report["failed_count"]),
            "mensagem": (
                "Todos os PDFs foram convertidos com sucesso."
                if report["failed_count"] == 0
                else "Lote finalizado com falhas. Reenvie os PDFs com erro."
            ),
            "total": report["input_count"],
            "sucesso": report["success_count"],
            "erros": report["failed_count"],
            "workers": report["workers"],
            "duracao_segundos": report["duration_seconds"],
            "falhas": failed_names,
        }

        response = {
            "ok": True,
            "summary": summary,
            "files": {
                "run_dir": str(run_dir),
                "zip_name": zip_path.name if zip_url else None,
                "zip_download_url": zip_url,
                "report_name": report_path.name,
                "report_download_url": _output_url(report_path),
                "retry_name": retry_path.name,
                "retry_download_url": _output_url(retry_path),
            },
        }
        return JSONResponse(content=response)

    except RuntimeError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": f"Falha interna: {exc}"})


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
