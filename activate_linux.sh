#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec /usr/bin/env bash "$ROOT_DIR/scripts/linux/start_pdf2epub_qa.sh"
