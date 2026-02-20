# Arquitetura

## Pipeline

1. Extracao: PyMuPDF gera texto por pagina e imagens.
2. Conversao:
   - `auto`: escolhe entre `reflow` e `fixed` por heuristica (texto x imagens).
   - `reflow`: heuristica de titulo por pagina para formar capitulos.
   - `fixed`: renderiza cada pagina do PDF para imagem e gera EPUB pre-paginado.
   - frontmatter editorial automatico: capa, folha de rosto e creditos.
3. HTML/XHTML: gera ancoras `page-N` para QA.
4. EPUB: ebooklib empacota HTML, imagens e metadados.
5. QA: comparacao textual (tokens), cobertura por pagina e comparacao visual.
6. QA editorial:
   - estrutura semantica (headings, landmarks, page-list, links internos, alt text).
   - metadados editoriais (ISBN, editora, direitos, descricao e metadados de acessibilidade).
   - validacao formal com `epubcheck` (quando configurado).
   - gate de publicacao com:
     - aprovacao final (`<arquivo>.epub.approval.json`)
     - revisao por capitulo (`<arquivo>.epub.review.json`)
     - score editorial/checklist de preflight.
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
- editorial:
  - `structure`: problemas de navegacao e semantica.
  - `metadata`: completude editorial e acessibilidade.
  - `epubcheck`: validacao formal (quando habilitada).
  - `chapter_review`: status da revisao humana por capitulo.
  - `approval`: aprovacao humana.
  - `gate`: `release_ready`, `score`, checklist e bloqueios de publicacao.

## Extensoes futuras

- QA visual por pagina (renderizacao e comparacao).
- OCR e reconstituicao de layout.
- Integracao opcional com LLM para sugerir correcoes.
