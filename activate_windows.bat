@echo off
setlocal

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

if not exist ".venv\Scripts\Activate.ps1" (
  echo [ERRO] Nao encontrei o ambiente virtual em ".venv".
  echo.
  echo Rode uma vez:
  echo   py -3.11 -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -U pip
  echo   .venv\Scripts\python.exe -m pip install -e ".[dev]"
  echo.
  pause
  exit /b 1
)

powershell -NoExit -ExecutionPolicy Bypass -Command ^
  "Set-Location -LiteralPath '%ROOT_DIR%';" ^
  ". '.\.venv\Scripts\Activate.ps1';" ^
  "Write-Host 'Ambiente ativado com sucesso.' -ForegroundColor Green;" ^
  "Write-Host 'Comandos uteis:' -ForegroundColor Cyan;" ^
  "Write-Host '  pdf2epub --help';" ^
  "Write-Host '  uvicorn pdf2epub_qa.api:app --reload';"

endlocal
