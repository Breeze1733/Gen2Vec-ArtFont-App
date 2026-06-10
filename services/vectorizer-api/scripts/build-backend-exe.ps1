<#
.SYNOPSIS
  Build a single-file `vectorizer-backend.exe` for the vectorizer-api service.

.DESCRIPTION
  Mirrors `services/txt2img-api/scripts/build-backend-exe.ps1` with shared
  structure.  Supports two toolchains:

    uv (default) — resolves dependencies via the project's own .venv;
                   recommended when a uv-managed venv exists in the repo.
    python       — uses the system/global Python; use this if you manage
                   your own venv manually or uv is not installed.

.PARAMETER Toolchain
  Either "uv" (default) or "python".  See description above.

.EXAMPLE
  .\scripts\build-backend-exe.ps1
  .\scripts\build-backend-exe.ps1 -Toolchain python
#>
param(
  [ValidateSet("uv", "python")]
  [string]$Toolchain = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 自动检测：uv 优先，找不到则回退 python
if (-not $Toolchain) {
  if (Get-Command uv -ErrorAction SilentlyContinue) {
    $Toolchain = "uv"
    Write-Host "auto-detect: uv found, using uv"
  } else {
    $Toolchain = "python"
    Write-Host "auto-detect: uv not found, falling back to python"
  }
}

if ($Toolchain -eq "uv") {
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is not on PATH. Install it (https://docs.astral.sh/uv/) or re-run with -Toolchain python."
  }
  $pipArgs = @("pip", "install", "--upgrade", "pyinstaller")
  $pyRunArgs = @("run", "python", "-m", "PyInstaller")
} else {
  $pipArgs = @("-m", "pip", "install", "--upgrade", "pip", "pyinstaller")
  $pyRunArgs = @("-m", "PyInstaller")
}

Write-Host "[1/5] Installing build dependencies via $Toolchain..."
& $Toolchain @pipArgs

Write-Host "[2/5] Cleaning previous build outputs..."
# Only remove PyInstaller artifacts; preserve other dist/ files.
if (Test-Path "build") { Remove-Item -LiteralPath "build" -Recurse -Force }
if (Test-Path "vectorizer-backend.spec") {
  Remove-Item -LiteralPath "vectorizer-backend.spec" -Force
}
$oldExe = Join-Path "dist" "vectorizer-backend.exe"
if (Test-Path $oldExe) { Remove-Item -LiteralPath $oldExe -Force }

Write-Host "[3/5] Building vectorizer-backend.exe with PyInstaller..."
& $Toolchain @pyRunArgs @(
  "--noconfirm"
  "--clean"
  "--name", "vectorizer-backend"
  "--onefile"
  "--console"
  "--collect-all", "skimage"
  "--collect-all", "cairosvg"
  "--collect-all", "cssselect2"
  "--collect-all", "tinycss2"
  "--collect-all", "cv2"
  "--collect-all", "rembg"
  "--collect-all", "onnxruntime"
  "--collect-all", "jsonschema"
  "--collect-all", "jsonschema_specifications"
  "--collect-all", "referencing"
  "--collect-all", "rpds"
  "--collect-all", "lark"
  "--collect-all", "rfc3987_syntax"
  "--collect-all", "vtracer"
  "--hidden-import", "uvicorn.logging"
  "--hidden-import", "uvicorn.loops.auto"
  "--hidden-import", "uvicorn.protocols.http.auto"
  "--hidden-import", "uvicorn.protocols.websockets.auto"
  "--hidden-import", "uvicorn.lifespan.on"
  "backend_entry.py"
)

Write-Host "[4/5] Copying distribution files to dist/..."
if (Test-Path "models") {
  Copy-Item -LiteralPath "models" -Destination "dist\models" -Recurse -Force
  Write-Host "  OK  models/"
}

Write-Host "[5/5] Done."
Write-Host ""
Write-Host "EXE output: $root\dist\vectorizer-backend.exe"
Write-Host ""
Write-Host "Distribution layout:"
Get-ChildItem (Join-Path $root "dist") | ForEach-Object {
  $size = if ($_.Length -gt 1GB) {
    "{0:N1} GB" -f ($_.Length / 1GB)
  } elseif ($_.Length -gt 1MB) {
    "{0:N0} MB" -f ($_.Length / 1MB)
  } else {
    "{0:N0} KB" -f ($_.Length / 1KB)
  }
  Write-Host "    $($_.Name)  ($size)"
}
Write-Host ""
Write-Host "The dist/ directory is the final distribution package."
