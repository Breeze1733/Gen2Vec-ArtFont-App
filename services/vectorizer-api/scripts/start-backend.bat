@echo off
setlocal

set EXE_NAME=vectorizer-backend.exe
set EXE_PATH=%~dp0..\dist\%EXE_NAME%

if not exist "%EXE_PATH%" (
  echo [ERROR] Backend EXE not found: %EXE_PATH%
  echo Please run build-backend-exe.ps1 first.
  pause
  exit /b 1
)

echo Starting %EXE_NAME% on http://127.0.0.1:8000 ...
"%EXE_PATH%" --host 127.0.0.1 --port 8000 --log-level info

endlocal

