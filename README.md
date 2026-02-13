# pdf2epub-qa

Conversor local de PDF (texto selecionavel) para EPUB com revisao automatica (QA) pagina por pagina.

## Instalacao

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -U pip
pip install -e ".[dev]"
```

## CLI

Conversao:

```bash
pdf2epub convert input.pdf -o out.epub --title "Meu Livro" --author "Autor" --lang "pt-BR"
```

Conversao com layout visualmente igual ao PDF (fixed-layout):

```bash
pdf2epub convert input.pdf -o out-fixed.epub --layout fixed --title "Meu Livro" --author "Autor" --lang "pt-BR"
```

Revisao:

```bash
pdf2epub review input.pdf out.epub -o report.json
```

O relatorio JSON inclui:
- coverage_text_percent
- missing_segments
- extra_segments
- image_count_pdf vs image_count_epub
- issues por pagina (simulacao por ancoras)

## API (opcional)

```bash
uvicorn pdf2epub_qa.api:app --reload
```

Exemplo de chamada:

```bash
curl -F "pdf=@input.pdf" -F "title=Meu Livro" http://localhost:8000/convert --output out.epub
curl -F "pdf=@input.pdf" -F "layout=fixed" http://localhost:8000/convert --output out-fixed.epub
curl -F "pdf=@input.pdf" -F "epub=@out.epub" http://localhost:8000/review
```

## Interface Web (simples)

Inicie a API:

```bash
uvicorn pdf2epub_qa.api:app --reload
```

Abra no navegador:

```text
http://127.0.0.1:8000/
```

Fluxo:
- selecione o PDF
- escolha layout `fixed` ou `reflow`
- clique em `Converter e revisar`
- baixe o `.epub` e o `.report.json`
- veja um resumo simplificado do QA na tela

Saida dos arquivos:
- pasta `outputs/` dentro da pasta do projeto `conversor`

## Testes

```bash
pytest
```

## Recursos opcionais

OCR (para PDFs sem texto selecionavel):

```bash
pip install -e ".[ocr]"
```

Habilitar OCR:

```bash
setx PDF2EPUB_QA_ENABLE_OCR 1
setx PDF2EPUB_QA_OCR_LANG por+eng
```

QA visual (gera hashes de render do PDF para comparacao futura):

```bash
setx PDF2EPUB_QA_VISUAL 1
setx PDF2EPUB_QA_VISUAL_MAX_PAGES 10
setx PDF2EPUB_QA_VISUAL_DPI 144
setx PDF2EPUB_QA_VISUAL_THRESHOLD 0.985
```

## Limitacoes do MVP

- OCR e opcional e requer instalacao do Tesseract.
- Deteccao de capitulos e heuristica simples.
- EPUB reflow nao fica 1:1 com PDF por natureza.
- Para equivalencia visual, use `--layout fixed`.

## Roadmap

- OCR (Tesseract ou similar).
- Melhorias no QA visual por pagina (threshold por tipo de pagina).
- Evoluir UI Web (historico, filtros e preview por pagina).
- Melhorias de segmentacao de capitulos e metadados.
