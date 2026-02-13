# Arquitetura

## Pipeline

1. Extracao: PyMuPDF gera texto por pagina e imagens.
2. Conversao:
   - `reflow`: heuristica de titulo por pagina para formar capitulos.
   - `fixed`: renderiza cada pagina do PDF para imagem e gera EPUB pre-paginado.
3. HTML/XHTML: gera ancoras `page-N` para QA.
4. EPUB: ebooklib empacota HTML, imagens e metadados.
5. QA: comparacao textual (tokens), cobertura por pagina e comparacao visual.
6. UI/API:
   - `POST /convert-and-review`: converte, revisa e salva saida em `outputs/`.
   - `GET /`: interface simples para upload e leitura do resumo de QA.

## QA

- coverage_text_percent: proporcao de tokens do PDF encontrados no EPUB.
- missing_segments/extra_segments: trechos derivados de diffs.
- issues por pagina: similaridade entre texto da pagina e o trecho ancorado.
- visual_qa:
  - `fixed-layout`: compara render da pagina do PDF com imagem da pagina no EPUB.
  - `reflow`: retorna `unsupported_layout` para comparacao visual 1:1.

## Extensoes futuras

- QA visual por pagina (renderizacao e comparacao).
- OCR e reconstituicao de layout.
- Integracao opcional com LLM para sugerir correcoes.
