#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -f ".venv/bin/activate" ]]; then
  echo "[ERRO] Nao encontrei o ambiente virtual em .venv."
  echo
  echo "Rode uma vez:"
  echo "  python3 -m venv .venv"
  echo "  .venv/bin/python -m pip install -U pip"
  echo "  .venv/bin/python -m pip install -e '.[dev]'"
  echo
  read -r -p "Pressione Enter para fechar..."
  exit 1
fi

# shellcheck disable=SC1091
source ".venv/bin/activate"
echo "Ambiente ativado com sucesso."
echo "Comandos uteis:"
echo "  pdf2epub --help"
echo "  uvicorn pdf2epub_qa.api:app --reload"
exec "${SHELL:-/bin/bash}" -i
