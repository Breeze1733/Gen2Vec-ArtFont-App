<#
.SYNOPSIS
  Build a single-file `txt2img-backend.exe` for the txt2img-api service.

.DESCRIPTION
  Mirrors `services/vectorizer-api/scripts/build-backend-exe.ps1`, but is
  tailored to the txt2img-api layout:

    * Workflow JSON files are bundled via `--add-data`.
    * The ComfyUI portable bundle (~60 GB) is intentionally NOT bundled
      and must live next to the EXE at runtime. See README.
    * `torch` is NOT a dependency of this service (ComfyUI provides it).
    * Uses `uv` (rather than bare `python`) so the build runs against the
      service's own `.venv` even when a different venv is on PATH.

.PARAMETER Toolchain
  Either "uv" (default) or "python". "uv" is recommended because it always
  resolves to the txt2img-api project's .venv and brings its own
  pip/PyInstaller. Use "python" only if you maintain a global venv.

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
# Only remove PyInstaller artifacts; preserve other dist/ files (e.g. ComfyUI-Engine.exe).
if (Test-Path "build") { Remove-Item -LiteralPath "build" -Recurse -Force }
if (Test-Path "txt2img-backend.spec") {
  Remove-Item -LiteralPath "txt2img-backend.spec" -Force
}
# Remove old EXE so PyInstaller does a clean rebuild.
$oldExe = Join-Path "dist" "txt2img-backend.exe"
if (Test-Path $oldExe) { Remove-Item -LiteralPath $oldExe -Force }

# Resolve the workflows directory (create it if a file is missing so
# PyInstaller does not fail the `--add-data` glob at build time).
$workflowsDir = Join-Path $root "workflows"
if (-not (Test-Path $workflowsDir)) {
  New-Item -ItemType Directory -Path $workflowsDir | Out-Null
}
$workflowFiles = Get-ChildItem -Path $workflowsDir -Filter "*.json" -ErrorAction SilentlyContinue
$addDataArgs = @()
foreach ($f in $workflowFiles) {
  $addDataArgs += "--add-data"
  # Windows uses ';' as the separator between source and dest in --add-data.
  $addDataArgs += "$($f.FullName);workflows"
}

Write-Host "[3/5] Building txt2img-backend.exe with PyInstaller..."
$pyinstallerArgs = @(
  "--noconfirm"
  "--clean"
  "--name", "txt2img-backend"
  "--onefile"
  "--console"
  "--paths", "app"
) + $addDataArgs + @(
  "--collect-all", "fastapi"
  "--collect-all", "uvicorn"
  "--collect-all", "httpx"
  "--collect-all", "PIL"
  "--collect-all", "anyio"
  "--hidden-import", "uvicorn.logging"
  "--hidden-import", "uvicorn.loops.auto"
  "--hidden-import", "uvicorn.protocols.http.auto"
  "--hidden-import", "uvicorn.protocols.websockets.auto"
  "--hidden-import", "uvicorn.lifespan.on"
  "txt2img_entry.py"
)

& $Toolchain @pyRunArgs @pyinstallerArgs

Write-Host "[4/5] Copying distribution files to dist/..."

$distDir = Join-Path $root "dist"
$scriptsDir = Join-Path $root "scripts"

$distFiles = @(
    "download-models.ps1"
)

foreach ($file in $distFiles) {
    $src = Join-Path $scriptsDir $file
    $dst = Join-Path $distDir $file
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $dst -Force
        Write-Host "  OK  $file"
    }
    else {
        Write-Host "  --  $file not found, skipping"
    }
}

Write-Host "[5/5] Done."
Write-Host ""
Write-Host "EXE output: $distDir\txt2img-backend.exe"
Write-Host ""
Write-Host "Distribution layout (place ComfyUI-Engine.exe in dist/ to complete):"
Get-ChildItem $distDir | ForEach-Object {
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
Write-Host "The dist/ directory is the final distribution package. Distribute all files in it to end users."
