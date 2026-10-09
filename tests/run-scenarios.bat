@echo off
rem ── 四场景验收脚本 · 双击入口 ──
rem 评审装完所有东西后，双击本文件即可跑完四个场景并产出报告。
rem 后端没在运行的话，脚本会自己拉起（含 ComfyUI）。
chcp 65001 >nul
setlocal

set "SCRIPT=%~dp0run-scenarios.py"
set "ROOT=%~dp0.."
set "PY="

rem 1) 开发环境：vectorizer 的 venv（确定带 cairosvg，可做渲染级 SVG 校验）
if not defined PY if exist "%ROOT%\services\vectorizer-api\.venv\Scripts\python.exe" set "PY=%ROOT%\services\vectorizer-api\.venv\Scripts\python.exe"

rem 2) 开发环境：仓库根 venv
if not defined PY if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"

rem 3) 交付环境：ComfyUI 便携包自带的 python_embeded
if not defined PY if exist "%ROOT%\resources\backend\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\python_embeded\python.exe" set "PY=%ROOT%\resources\backend\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\python_embeded\python.exe"

rem 4) 开发环境的 ComfyUI 便携包（引擎放在服务目录下时）
if not defined PY if exist "%ROOT%\services\txt2img-api\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\python_embeded\python.exe" set "PY=%ROOT%\services\txt2img-api\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\python_embeded\python.exe"

rem 5) 系统 Python
if not defined PY (
  where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)

if not defined PY (
  echo.
  echo [错误] 找不到可用的 Python。
  echo        请安装 Python 3 后重试，或手动运行：
  echo          ^<某个python^> "%~dp0run-scenarios.py"
  echo.
  if not "%GEN2VEC_NO_PAUSE%"=="1" pause
  exit /b 2
)

echo [环境] Python: %PY%
echo.
%PY% "%SCRIPT%" %*
set EXITCODE=%ERRORLEVEL%

echo.
if "%EXITCODE%"=="0" (echo 结果：全部通过) else (echo 结果：有失败项，退出码 %EXITCODE%)
if not "%GEN2VEC_NO_PAUSE%"=="1" pause
exit /b %EXITCODE%
