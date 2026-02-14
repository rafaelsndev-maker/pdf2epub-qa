# pdf2epub-qa

Conversor local de PDF para EPUB com QA textual e visual por pagina.

## Suporte

- Windows 10/11
- macOS (Intel e Apple Silicon)
- Linux (Python 3.11+)

CI roda em Linux, Windows e macOS.

## Inicio rapido

### Windows (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\activate_windows.bat
```

### macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[dev]"
chmod +x activate_macos.command activate_linux.sh
```

## Ativador por duplo clique

- Windows: `activate_windows.bat`
- macOS: `activate_macos.command`
- Linux: `activate_linux.sh`

Esses arquivos abrem um terminal com `.venv` ativado.

## Uso pela CLI

### 1) Converter PDF para EPUB

```bash
pdf2epub convert "input.pdf" -o "out.epub" --title "Meu Livro" --author "Autor" --lang "pt-BR"
```

### 2) Converter com layout visual parecido com PDF

```bash
pdf2epub convert "input.pdf" -o "out-fixed.epub" --layout fixed --title "Meu Livro" --lang "pt-BR"
```

### 3) Revisar QA

```bash
pdf2epub review "input.pdf" "out.epub" -o "report.json"
```

Arquivos gerados no `review`:
- `report.json`: relatorio tecnico completo.
- `report.leigo.json`: resumo em linguagem simples.

## Interface Web

Suba a API:

```bash
uvicorn pdf2epub_qa.api:app --reload
```

Abra:

```text
http://127.0.0.1:8000/
```

Fluxo:
- selecione o PDF
- escolha `fixed` ou `reflow`
- clique em `Converter e revisar`
- baixe EPUB e JSON
- leia o resumo simplificado na tela

Saidas ficam em `outputs/`.

## API

Endpoints:
- `POST /convert`
- `POST /review`
- `POST /convert-and-review`

Exemplos:

```bash
curl -F "pdf=@input.pdf" -F "layout=fixed" http://localhost:8000/convert --output out-fixed.epub
curl -F "pdf=@input.pdf" -F "epub=@out-fixed.epub" http://localhost:8000/review
```

## Interpretacao dos relatorios

Campos principais no tecnico (`report.json`):
- `coverage_text_percent`: quanto texto do PDF foi preservado.
- `missing_segments`: trechos do PDF que nao apareceram no EPUB.
- `extra_segments`: trechos extras encontrados no EPUB.
- `image_count_pdf` e `image_count_epub`: comparacao de imagens.
- `issues`: status por pagina (`ok`, `low_coverage`, `missing_page`, `no_text`).
- `visual_qa`: resultado da comparacao visual quando habilitada.

Campos principais no leigo (`report.leigo.json`):
- `status_geral`
- `mensagem`
- `explicacao_simples`
- `sinais_de_atencao`
- `recomendacoes`

## Recursos opcionais

OCR (PDF escaneado):

```bash
pip install -e ".[ocr]"
```

Depois, habilite variaveis:

```powershell
setx PDF2EPUB_QA_ENABLE_OCR 1
setx PDF2EPUB_QA_OCR_LANG por+eng
```

QA visual:

```powershell
setx PDF2EPUB_QA_VISUAL 1
setx PDF2EPUB_QA_VISUAL_MAX_PAGES 10
setx PDF2EPUB_QA_VISUAL_DPI 144
setx PDF2EPUB_QA_VISUAL_THRESHOLD 0.985
```

## Testes e qualidade

```bash
pytest
ruff check .
```

## Problemas comuns

- `Arquivo nao encontrado`: use caminho entre aspas se tiver espacos.
- `pip` pedindo `python -m pip`: use sempre `python -m pip`.
- OCR nao funciona: confirme `tesseract --list-langs` no terminal.

## Limitacoes MVP

- Reflow nunca fica 1:1 com PDF.
- OCR depende de Tesseract instalado no sistema.
- Deteccao de capitulos ainda e heuristica.

## Roadmap

- Melhorar segmentacao de capitulos.
- QA visual com regras por tipo de pagina.
- Historico de conversoes na interface web.
