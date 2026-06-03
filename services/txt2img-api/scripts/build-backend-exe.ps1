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
  [string]$Toolchain = "uv"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if ($Toolchain -eq "uv") {
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is not on PATH. Install it (https://docs.astral.sh/uv/) or re-run with -Toolchain python."
  }
  $pipArgs = @("pip", "install", "--upgrade", "pyinstaller")
  $pyRunArgs = @("run", "python", "-m", "PyInstaller")
} else {
  $PythonExe = (Get-Command python).Source
  $pipArgs = @("-m", "pip", "install", "--upgrade", "pyinstaller")
  $pyRunArgs = @($PythonExe, "-m", "PyInstaller")
}

Write-Host "[1/4] Installing build dependencies via $Toolchain..."
& $Toolchain @pipArgs

Write-Host "[2/4] Cleaning previous build outputs..."
if (Test-Path "build") { Remove-Item -LiteralPath "build" -Recurse -Force }
if (Test-Path "dist") { Remove-Item -LiteralPath "dist" -Recurse -Force }
if (Test-Path "txt2img-backend.spec") {
  Remove-Item -LiteralPath "txt2img-backend.spec" -Force
}

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

Write-Host "[3/4] Building txt2img-backend.exe with PyInstaller..."
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

Write-Host "[4/4] Done."
Write-Host "EXE output: $root\dist\txt2img-backend.exe"
Write-Host ""
Write-Host "Distribution layout (ComfyUI bundle is NOT bundled into the EXE):"
Write-Host "    dist\txt2img-backend.exe"
Write-Host "    ComfyUI_windows_portable_nvidia\   <-- place this folder next to the EXE"
