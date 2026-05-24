param(
  [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "[1/4] Installing build dependencies..."
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r requirements.txt
& $PythonExe -m pip install pyinstaller

Write-Host "[2/4] Cleaning previous build outputs..."
if (Test-Path "build") { Remove-Item -LiteralPath "build" -Recurse -Force }
if (Test-Path "dist") { Remove-Item -LiteralPath "dist" -Recurse -Force }
if (Test-Path "backend_entry.spec") { Remove-Item -LiteralPath "backend_entry.spec" -Force }

Write-Host "[3/4] Building backend.exe with PyInstaller..."
& $PythonExe -m PyInstaller `
  --noconfirm `
  --clean `
  --name vectorizer-backend `
  --onefile `
  --console `
  --collect-all skimage `
  --collect-all cairosvg `
  --collect-all cssselect2 `
  --collect-all tinycss2 `
  --collect-all cv2 `
  --collect-all vtracer `
  --hidden-import uvicorn.logging `
  --hidden-import uvicorn.loops.auto `
  --hidden-import uvicorn.protocols.http.auto `
  --hidden-import uvicorn.protocols.websockets.auto `
  --hidden-import uvicorn.lifespan.on `
  backend_entry.py

Write-Host "[4/4] Done."
Write-Host "EXE output: $root\\dist\\vectorizer-backend.exe"

