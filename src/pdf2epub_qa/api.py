from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote
from uuid import uuid4
from xml.etree import ElementTree as ET

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .batch import convert_pdfs_batch
from .converter import convert_pdf_to_epub
from .epub_builder import LAYOUT_AUTO, LAYOUT_FIXED, LAYOUT_REFLOW
from .qa import review_pdf_epub
from .reporting import build_user_summary

OUTPUT_DIR = Path(os.getenv("PDF2EPUB_QA_OUTPUT_DIR", str(Path.cwd() / "outputs")))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="pdf2epub-qa")
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")

ALLOWED_LAYOUTS = {LAYOUT_REFLOW, LAYOUT_FIXED, LAYOUT_AUTO}


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


_EPUB_MEDIA_TYPES = {
    ".css": "text/css",
    ".gif": "image/gif",
    ".htm": "text/html",
    ".html": "text/html",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".js": "application/javascript",
    ".ncx": "application/x-dtbncx+xml",
    ".otf": "font/otf",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ttf": "font/ttf",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".xhtml": "application/xhtml+xml",
    ".xml": "application/xml",
}


def _normalize_epub_path(path_value: str) -> str:
    raw = (path_value or "").replace("\\", "/")
    parts: list[str] = []
    for part in raw.split("/"):
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                raise HTTPException(status_code=400, detail="Caminho interno invalido no EPUB.")
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        raise HTTPException(status_code=400, detail="Caminho interno vazio no EPUB.")
    return "/".join(parts)


def _resolve_output_epub(path_ref: str) -> Path:
    raw = unquote(path_ref or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Informe o caminho do EPUB.")

    rel = raw
    if rel.startswith("/outputs/"):
        rel = rel[len("/outputs/") :]
    rel = rel.replace("\\", "/").lstrip("/")
    if not rel:
        raise HTTPException(status_code=400, detail="Caminho do EPUB invalido.")

    candidate = (OUTPUT_DIR / rel).resolve()
    base_dir = OUTPUT_DIR.resolve()
    try:
        candidate.relative_to(base_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Caminho fora de outputs/.") from exc

    if candidate.suffix.lower() != ".epub":
        raise HTTPException(status_code=400, detail="Arquivo precisa ter extensao .epub.")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="EPUB nao encontrado.")
    return candidate


def _encode_epub_token(epub_path: Path) -> str:
    rel = epub_path.resolve().relative_to(OUTPUT_DIR.resolve()).as_posix()
    encoded = base64.urlsafe_b64encode(rel.encode("utf-8")).decode("ascii")
    return encoded.rstrip("=")


def _decode_epub_token(token: str) -> Path:
    padded = token + ("=" * (-len(token) % 4))
    try:
        rel = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Token de EPUB invalido.") from exc
    return _resolve_output_epub(rel)


def _read_epub_package(epub_path: Path) -> dict[str, object]:
    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            try:
                container_xml = zf.read("META-INF/container.xml")
            except KeyError as exc:
                raise HTTPException(
                    status_code=400, detail="EPUB invalido: container.xml ausente."
                ) from exc

            try:
                container_root = ET.fromstring(container_xml)
            except ET.ParseError as exc:
                raise HTTPException(
                    status_code=400, detail="EPUB invalido: container.xml malformado."
                ) from exc

            rootfile = container_root.find(".//{*}rootfile")
            if rootfile is None:
                raise HTTPException(status_code=400, detail="EPUB invalido: rootfile ausente.")

            opf_raw = (rootfile.attrib.get("full-path") or "").strip()
            if not opf_raw:
                raise HTTPException(
                    status_code=400, detail="EPUB invalido: caminho OPF nao informado."
                )

            opf_path = _normalize_epub_path(opf_raw)
            try:
                opf_xml = zf.read(opf_path)
            except KeyError as exc:
                raise HTTPException(
                    status_code=400, detail="EPUB invalido: pacote OPF nao encontrado."
                ) from exc

            try:
                opf_root = ET.fromstring(opf_xml)
            except ET.ParseError as exc:
                raise HTTPException(
                    status_code=400, detail="EPUB invalido: OPF malformado."
                ) from exc

            opf_dir = PurePosixPath(opf_path).parent
            manifest_by_id: dict[str, str] = {}
            for item in opf_root.findall(".//{*}manifest/{*}item"):
                item_id = (item.attrib.get("id") or "").strip()
                href = (item.attrib.get("href") or "").strip()
                if not item_id or not href:
                    continue
                full_path = _normalize_epub_path(str(opf_dir / PurePosixPath(href)))
                manifest_by_id[item_id] = full_path

            spine_paths: list[str] = []
            for itemref in opf_root.findall(".//{*}spine/{*}itemref"):
                idref = (itemref.attrib.get("idref") or "").strip()
                path = manifest_by_id.get(idref)
                if path and path not in spine_paths:
                    spine_paths.append(path)

            title_el = opf_root.find(".//{*}metadata/{*}title")
            if title_el is None:
                title_el = opf_root.find(".//{*}title")
            title = (title_el.text or "").strip() if title_el is not None else ""
            return {"title": title or epub_path.stem, "spine": spine_paths}
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=400, detail="Arquivo EPUB invalido (zip corrompido)."
        ) from exc


def _media_type_for_epub_item(item_path: str) -> str:
    suffix = Path(item_path).suffix.lower()
    custom = _EPUB_MEDIA_TYPES.get(suffix)
    if custom:
        return custom
    guessed, _ = mimetypes.guess_type(item_path)
    return guessed or "application/octet-stream"


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
              <option value="auto" selected>auto (escolha automatica)</option>
              <option value="fixed">fixed (visual igual ao PDF)</option>
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
            <a id="readerLink" href="#" target="_blank" rel="noopener">Abrir no leitor EPUB</a>
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
              <option value="auto" selected>auto por arquivo (recomendado)</option>
              <option value="reflow">reflow para todos (mais leve)</option>
              <option value="fixed">fixed para todos (visual igual ao PDF)</option>
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

      <div class="card">
        <h2>Leitor EPUB (upload rapido)</h2>
        <p class="sub">Envie um arquivo EPUB e abra direto no leitor.</p>
        <form id="quickReaderForm" class="grid">
          <div class="full">
            <label for="quickEpub">Arquivo EPUB</label>
            <input
              id="quickEpub"
              name="epub"
              type="file"
              accept=".epub,application/epub+zip"
              required
            />
          </div>
          <div class="full">
            <button id="quickReaderBtn" type="submit">Enviar e abrir leitor</button>
          </div>
        </form>
        <div id="quickReaderStatus" class="status"></div>
        <div id="quickReaderResult" class="result">
          <div class="links">
            <a id="quickReaderOpenLink" href="#" target="_blank" rel="noopener">
              Abrir no leitor EPUB
            </a>
            <a id="quickReaderDownloadLink" href="#" target="_blank" rel="noopener">
              Baixar EPUB
            </a>
          </div>
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
      const readerLink = document.getElementById("readerLink");
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

      const quickReaderForm = document.getElementById("quickReaderForm");
      const quickReaderStatus = document.getElementById("quickReaderStatus");
      const quickReaderResult = document.getElementById("quickReaderResult");
      const quickReaderBtn = document.getElementById("quickReaderBtn");
      const quickReaderOpenLink = document.getElementById("quickReaderOpenLink");
      const quickReaderDownloadLink = document.getElementById("quickReaderDownloadLink");

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
        if (summary.layout_solicitado) {
          lines.push(`Layout solicitado: ${summary.layout_solicitado}`);
        }
        if (summary.layout_contagem) {
          lines.push(
            `Layout escolhido por arquivo: reflow=${summary.layout_contagem.reflow || 0}, `
            + `fixed=${summary.layout_contagem.fixed || 0}`
          );
        }
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
          readerLink.href =
            `/epub-reader?epub=${encodeURIComponent(payload.files.epub_download_url)}`;
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

      quickReaderForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const epubInput = document.getElementById("quickEpub");
        const file = epubInput.files && epubInput.files[0];
        if (!file) {
          showStatus(quickReaderStatus, "Selecione um arquivo .epub.", "#fef3f2", "#b42318");
          return;
        }

        const data = new FormData();
        data.append("epub", file);
        quickReaderResult.style.display = "none";
        quickReaderBtn.disabled = true;
        showStatus(quickReaderStatus, "Enviando EPUB para o leitor...");

        try {
          const response = await fetch("/epub-upload", { method: "POST", body: data });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Falha ao enviar EPUB.");

          quickReaderOpenLink.href = payload.epub_reader_url;
          quickReaderDownloadLink.href = payload.epub_download_url;
          quickReaderResult.style.display = "block";
          showStatus(quickReaderStatus, "EPUB pronto para leitura.", "#ecfdf3", "#067647");
        } catch (err) {
          showStatus(
            quickReaderStatus,
            err.message || "Erro ao enviar EPUB.",
            "#fef3f2",
            "#b42318"
          );
        } finally {
          quickReaderBtn.disabled = false;
        }
      });
    </script>
  </body>
</html>
"""
    return HTMLResponse(content=html)


@app.get("/epub-reader", response_class=HTMLResponse)
async def epub_reader_ui(epub: str | None = None) -> HTMLResponse:
    html = """
<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Leitor EPUB</title>
    <style>
      :root {
        --bg: #f4f7fb;
        --card: #ffffff;
        --text: #1b2430;
        --muted: #667085;
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
        max-width: 1200px;
        margin: 20px auto;
        padding: 0 16px 20px;
      }
      .card {
        background: var(--card);
        border: 1px solid #e4e7ec;
        border-radius: 14px;
        padding: 14px;
        box-shadow: 0 8px 24px rgba(16, 24, 40, 0.06);
        margin-bottom: 12px;
      }
      h1 {
        margin: 0 0 4px;
        font-size: 24px;
      }
      .sub {
        margin: 0 0 12px;
        color: var(--muted);
      }
      .row {
        display: grid;
        grid-template-columns: 1fr auto;
        gap: 10px;
      }
      .row + .row {
        margin-top: 8px;
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
      .status {
        margin-top: 10px;
        padding: 10px 12px;
        border-radius: 10px;
        background: #eff6ff;
        color: #1849a9;
        font-size: 14px;
      }
      .toolbar {
        margin-top: 10px;
        display: none;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
      }
      .toolbar button {
        width: auto;
        min-width: 90px;
      }
      .toolbar select {
        width: min(420px, 100%);
      }
      .toolbar a {
        color: var(--primary);
        font-weight: 600;
        text-decoration: none;
      }
      #viewer {
        width: 100%;
        min-height: 75vh;
        border: 1px solid #d0d5dd;
        border-radius: 12px;
        background: white;
      }
      @media (max-width: 760px) {
        .row { grid-template-columns: 1fr; }
      }
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <h1>Leitor EPUB</h1>
        <p class="sub">Abra o EPUB gerado, envie um novo EPUB e navegue pelos capitulos.</p>
        <form id="loadForm" class="row">
          <input
            id="epubPath"
            type="text"
            placeholder="/outputs/seu-arquivo.epub"
            aria-label="Caminho do EPUB"
          />
          <button type="submit">Carregar</button>
        </form>
        <form id="uploadForm" class="row">
          <input
            id="epubUpload"
            type="file"
            accept=".epub,application/epub+zip"
            aria-label="Upload de EPUB"
          />
          <button id="uploadBtn" type="submit">Upload rapido</button>
        </form>
        <div id="status" class="status">Informe um EPUB para iniciar.</div>
        <div id="toolbar" class="toolbar">
          <button id="prevBtn" type="button">Anterior</button>
          <select id="chapterSelect" aria-label="Capitulos"></select>
          <button id="nextBtn" type="button">Proximo</button>
          <a id="downloadLink" href="#" target="_blank" rel="noopener">Baixar EPUB</a>
        </div>
      </div>
      <iframe id="viewer" title="Visualizador EPUB"></iframe>
    </div>

    <script>
      const INITIAL_EPUB = __INITIAL_EPUB__;

      const loadForm = document.getElementById("loadForm");
      const uploadForm = document.getElementById("uploadForm");
      const epubPath = document.getElementById("epubPath");
      const epubUpload = document.getElementById("epubUpload");
      const uploadBtn = document.getElementById("uploadBtn");
      const statusEl = document.getElementById("status");
      const toolbar = document.getElementById("toolbar");
      const chapterSelect = document.getElementById("chapterSelect");
      const prevBtn = document.getElementById("prevBtn");
      const nextBtn = document.getElementById("nextBtn");
      const downloadLink = document.getElementById("downloadLink");
      const viewer = document.getElementById("viewer");

      let chapters = [];
      let currentIndex = 0;

      function showStatus(message, background = "#eff6ff", color = "#1849a9") {
        statusEl.style.background = background;
        statusEl.style.color = color;
        statusEl.textContent = message;
      }

      function updateViewer() {
        if (chapters.length === 0) {
          viewer.removeAttribute("src");
          return;
        }
        const chapter = chapters[currentIndex];
        chapterSelect.value = String(currentIndex);
        prevBtn.disabled = currentIndex <= 0;
        nextBtn.disabled = currentIndex >= chapters.length - 1;
        viewer.src = chapter.url;
      }

      async function loadEpub(pathValue) {
        const value = (pathValue || "").trim();
        if (!value) {
          showStatus("Informe o caminho do EPUB.", "#fef3f2", "#b42318");
          return;
        }

        toolbar.style.display = "none";
        chapters = [];
        viewer.removeAttribute("src");
        showStatus("Carregando EPUB...");

        try {
          const response = await fetch(`/epub-meta?epub=${encodeURIComponent(value)}`);
          const payload = await response.json();
          if (!response.ok) {
            throw new Error(payload.error || "Nao foi possivel carregar o EPUB.");
          }

          chapters = payload.chapters || [];
          if (chapters.length === 0) {
            throw new Error("EPUB sem capitulos legiveis.");
          }

          chapterSelect.innerHTML = "";
          chapters.forEach((item, index) => {
            const option = document.createElement("option");
            option.value = String(index);
            option.textContent = `${index + 1}. ${item.label}`;
            chapterSelect.appendChild(option);
          });

          currentIndex = 0;
          downloadLink.href = payload.download_url;
          toolbar.style.display = "flex";
          updateViewer();
          showStatus(
            `Leitor carregado: ${payload.title} (${chapters.length} capitulos).`,
            "#ecfdf3",
            "#067647"
          );
        } catch (err) {
          showStatus(err.message || "Erro ao carregar EPUB.", "#fef3f2", "#b42318");
        }
      }

      loadForm.addEventListener("submit", (event) => {
        event.preventDefault();
        loadEpub(epubPath.value);
      });

      uploadForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const file = epubUpload.files && epubUpload.files[0];
        if (!file) {
          showStatus("Selecione um arquivo .epub.", "#fef3f2", "#b42318");
          return;
        }

        uploadBtn.disabled = true;
        showStatus("Enviando EPUB...");

        try {
          const data = new FormData();
          data.append("epub", file);
          const response = await fetch("/epub-upload", { method: "POST", body: data });
          const payload = await response.json();
          if (!response.ok) {
            throw new Error(payload.error || "Falha no upload do EPUB.");
          }

          epubPath.value = payload.epub_download_url;
          await loadEpub(payload.epub_download_url);
        } catch (err) {
          showStatus(err.message || "Erro ao enviar EPUB.", "#fef3f2", "#b42318");
        } finally {
          uploadBtn.disabled = false;
        }
      });

      chapterSelect.addEventListener("change", () => {
        currentIndex = Number(chapterSelect.value) || 0;
        updateViewer();
      });

      prevBtn.addEventListener("click", () => {
        currentIndex = Math.max(0, currentIndex - 1);
        updateViewer();
      });

      nextBtn.addEventListener("click", () => {
        currentIndex = Math.min(chapters.length - 1, currentIndex + 1);
        updateViewer();
      });

      if (INITIAL_EPUB) {
        epubPath.value = INITIAL_EPUB;
        loadEpub(INITIAL_EPUB);
      }
    </script>
  </body>
</html>
"""
    html = html.replace("__INITIAL_EPUB__", json.dumps(epub or "", ensure_ascii=False))
    return HTMLResponse(content=html)


@app.get("/epub-meta")
async def epub_meta_endpoint(epub: str) -> JSONResponse:
    try:
        epub_path = _resolve_output_epub(epub)
        package = _read_epub_package(epub_path)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})

    token = _encode_epub_token(epub_path)
    chapters: list[dict[str, str]] = []
    for item_path in package["spine"]:
        if not item_path.lower().endswith((".xhtml", ".html", ".htm")):
            continue
        chapters.append(
            {
                "path": item_path,
                "label": PurePosixPath(item_path).name or item_path,
                "url": f"/epub-resource/{token}/{quote(item_path, safe='/')}",
            }
        )

    if not chapters:
        return JSONResponse(
            status_code=400, content={"error": "EPUB nao possui capitulos XHTML no spine."}
        )

    return JSONResponse(
        content={
            "title": package["title"],
            "download_url": _output_url(epub_path),
            "epub_url": _output_url(epub_path),
            "chapters": chapters,
        }
    )


@app.get("/epub-resource/{epub_token}/{item_path:path}")
async def epub_resource_endpoint(epub_token: str, item_path: str):
    try:
        epub_path = _decode_epub_token(epub_token)
        normalized_item = _normalize_epub_path(item_path)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})

    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            try:
                content = zf.read(normalized_item)
            except KeyError:
                return JSONResponse(
                    status_code=404, content={"error": "Recurso nao encontrado dentro do EPUB."}
                )
    except zipfile.BadZipFile:
        return JSONResponse(status_code=400, content={"error": "Arquivo EPUB invalido."})

    return Response(content=content, media_type=_media_type_for_epub_item(normalized_item))


@app.post("/epub-upload")
async def epub_upload_endpoint(epub_file: UploadFile = File(..., alias="epub")) -> JSONResponse:
    input_name = epub_file.filename or "input.epub"
    if not input_name.lower().endswith(".epub"):
        return JSONResponse(status_code=400, content={"error": "Envie um arquivo .epub valido."})

    base_name = _safe_stem(input_name)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    token = uuid4().hex[:8]
    epub_path = OUTPUT_DIR / f"{base_name}-{stamp}-{token}.epub"

    try:
        _save_upload(epub_file, epub_path)
        _read_epub_package(epub_path)
    except HTTPException as exc:
        epub_path.unlink(missing_ok=True)
        return JSONResponse(status_code=400, content={"error": str(exc.detail)})
    except Exception as exc:
        epub_path.unlink(missing_ok=True)
        return JSONResponse(status_code=500, content={"error": f"Falha interna: {exc}"})

    epub_url = _output_url(epub_path)
    return JSONResponse(
        content={
            "ok": True,
            "epub_name": epub_path.name,
            "epub_download_url": epub_url,
            "epub_reader_url": f"/epub-reader?epub={quote(epub_url, safe='')}",
        }
    )


@app.post("/convert-and-review")
async def convert_and_review_endpoint(
    pdf: UploadFile = File(...),
    title: str | None = Form(None),
    author: str | None = Form(None),
    lang: str = Form("pt-BR"),
    layout: str = Form(LAYOUT_AUTO),
) -> JSONResponse:
    input_name = pdf.filename or "input.pdf"
    if not input_name.lower().endswith(".pdf"):
        return JSONResponse(status_code=400, content={"error": "Envie um arquivo .pdf valido."})
    if layout not in ALLOWED_LAYOUTS:
        return JSONResponse(
            status_code=400, content={"error": "layout invalido. Use reflow, fixed ou auto."}
        )

    base_name = _safe_stem(input_name)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    token = uuid4().hex[:8]
    prefix = f"{base_name}-{stamp}-{token}"

    pdf_path = OUTPUT_DIR / f"{prefix}.pdf"
    epub_path = OUTPUT_DIR / f"{prefix}.epub"
    report_path = OUTPUT_DIR / f"{prefix}.report.json"

    try:
        _save_upload(pdf, pdf_path)
        conversion_result = convert_pdf_to_epub(
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
        "conversion": {
            "layout_requested": layout,
            "layout_selected": conversion_result.layout_mode,
        },
        "files": {
            "output_dir": str(OUTPUT_DIR),
            "pdf_name": pdf_path.name,
            "epub_name": epub_path.name,
            "report_name": report_path.name,
            "epub_download_url": _output_url(epub_path),
            "epub_reader_url": f"/epub-reader?epub={quote(_output_url(epub_path), safe='')}",
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
    layout: str = Form(LAYOUT_AUTO),
    workers: int = Form(2),
    author: str | None = Form(None),
) -> JSONResponse:
    if layout not in ALLOWED_LAYOUTS:
        return JSONResponse(
            status_code=400, content={"error": "layout invalido. Use reflow, fixed ou auto."}
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
                "layout_mode": item["layout_mode"],
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
            "layout_distribution": report["layout_distribution"],
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
            "layout_solicitado": layout,
            "layout_contagem": report["layout_distribution"],
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
    layout: str = Form(LAYOUT_AUTO),
):
    tmpdir = Path(tempfile.mkdtemp())
    pdf_path = tmpdir / "input.pdf"
    epub_path = tmpdir / "output.epub"
    _save_upload(pdf, pdf_path)
    if layout not in ALLOWED_LAYOUTS:
        background_tasks.add_task(shutil.rmtree, tmpdir, ignore_errors=True)
        return JSONResponse(
            status_code=400, content={"error": "layout invalido. Use reflow, fixed ou auto."}
        )

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
