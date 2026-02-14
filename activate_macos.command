#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec /bin/bash "$ROOT_DIR/scripts/macos/start_pdf2epub_qa.command"
