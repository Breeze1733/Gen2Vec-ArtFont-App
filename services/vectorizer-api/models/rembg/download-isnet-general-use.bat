@echo off
setlocal

set "MODEL_NAME=isnet-general-use.onnx"
set "MODEL_URL=https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx"
set "MODEL_MD5=FC16EBD8B0C10D971D3513D564D01E29"
set "MODEL_PATH=%~dp0%MODEL_NAME%"

echo Downloading %MODEL_NAME%...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; Invoke-WebRequest -Uri '%MODEL_URL%' -OutFile '%MODEL_PATH%'"
if errorlevel 1 (
  echo Download failed.
  exit /b 1
)

for /f "usebackq tokens=1" %%H in (`powershell -NoProfile -Command "(Get-FileHash -Algorithm MD5 -LiteralPath '%MODEL_PATH%').Hash"`) do set "ACTUAL_MD5=%%H"

if /I not "%ACTUAL_MD5%"=="%MODEL_MD5%" (
  echo Checksum mismatch.
  echo Expected: %MODEL_MD5%
  echo Actual:   %ACTUAL_MD5%
  exit /b 1
)

echo Model ready: %MODEL_PATH%
endlocal
