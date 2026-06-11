@echo off
chcp 65001 >nul
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run-art-text-prompts.ps1" %*
set EXITCODE=%ERRORLEVEL%
if not "%GEN2VEC_NO_PAUSE%"=="1" pause
exit /b %EXITCODE%
