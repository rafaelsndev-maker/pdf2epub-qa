@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%\..\..") do set "ROOT_DIR=%%~fI"
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
  "Write-Host 'Ambiente local ativado.' -ForegroundColor Green;" ^
  "Write-Host 'Abrindo o navegador em http://127.0.0.1:8000 ...' -ForegroundColor Cyan;" ^
  "Start-Process 'http://127.0.0.1:8000/';" ^
  "python -m uvicorn pdf2epub_qa.api:app --host 127.0.0.1 --port 8000 --reload"

endlocal
