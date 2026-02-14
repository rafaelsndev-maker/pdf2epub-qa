@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "LAUNCHER=%ROOT_DIR%scripts\windows\start_pdf2epub_qa.bat"

if not exist "%LAUNCHER%" (
  echo [ERRO] Ativador nao encontrado em scripts\windows\start_pdf2epub_qa.bat
  pause
  exit /b 1
)

call "%LAUNCHER%"

endlocal
