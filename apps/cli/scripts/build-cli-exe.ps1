# apps/cli/scripts/build-cli-exe.ps1
# Build a single-file Windows executable with Node.js SEA.
#
# The generated gen2vec_cli.exe contains the Node runtime and the bundled CLI.
# End users do not need Node.js installed.

param(
  [string]$OutputDir = "dist"
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CliRoot = Split-Path -Parent $ScriptDir

$DistDir = Join-Path $CliRoot $OutputDir
$BundlePath = Join-Path $DistDir "gen2vec_cli.bundle.cjs"
$BlobPath = Join-Path $DistDir "gen2vec_cli.blob"
$ExePath = Join-Path $DistDir "gen2vec_cli.exe"
$ConfigPath = Join-Path $DistDir "sea-config.json"

function Invoke-Step {
  param(
    [string]$Title,
    [scriptblock]$Body
  )
  Write-Host $Title -ForegroundColor Yellow
  & $Body
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Gen2Vec CLI Single-EXE Build" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Invoke-Step "[1/5] Preparing build directory..." {
  Remove-Item -Recurse -Force $DistDir -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Path $DistDir -Force | Out-Null
  Write-Host "       Output: $DistDir"
}

Invoke-Step "[2/5] Checking Node.js SEA support..." {
  $NodeCommand = Get-Command node -ErrorAction Stop
  $NodeExe = $NodeCommand.Source
  $NodeVersionRaw = (& node -p "process.versions.node")
  if ($LASTEXITCODE -ne 0) {
    throw "Unable to query Node.js version."
  }

  $NodeVersion = [version]$NodeVersionRaw
  if ($NodeVersion.Major -lt 20) {
    throw "Node.js 20+ is required to build a SEA executable. Current node is $NodeVersionRaw at $NodeExe."
  }

  Write-Host "       Node: $NodeVersionRaw"
  Write-Host "       Path: $NodeExe"
}

Invoke-Step "[3/5] Bundling CLI modules..." {
  Push-Location $CliRoot
  try {
    node .\scripts\bundle-cli.mjs
    if ($LASTEXITCODE -ne 0) {
      throw "CLI bundle failed."
    }
    node --check ".\$OutputDir\gen2vec_cli.bundle.cjs"
    if ($LASTEXITCODE -ne 0) {
      throw "CLI bundle syntax check failed."
    }
  } finally {
    Pop-Location
  }
}

Invoke-Step "[4/5] Creating SEA blob..." {
  $SeaConfig = @{
    main = "./$OutputDir/gen2vec_cli.bundle.cjs"
    output = "./$OutputDir/gen2vec_cli.blob"
    disableExperimentalSEAWarning = $true
    useCodeCache = $false
  } | ConvertTo-Json -Compress

  $Utf8NoBom = New-Object System.Text.UTF8Encoding $false
  [System.IO.File]::WriteAllText($ConfigPath, $SeaConfig, $Utf8NoBom)

  Push-Location $CliRoot
  try {
    node --experimental-sea-config ".\$OutputDir\sea-config.json"
    if ($LASTEXITCODE -ne 0) {
      throw "SEA blob creation failed."
    }
  } finally {
    Pop-Location
  }
}

Invoke-Step "[5/5] Injecting blob into node.exe..." {
  $NodeExe = (Get-Command node -ErrorAction Stop).Source
  Copy-Item $NodeExe $ExePath -Force

  Push-Location $CliRoot
  try {
    npx postject ".\$OutputDir\gen2vec_cli.exe" NODE_SEA_BLOB ".\$OutputDir\gen2vec_cli.blob" --sentinel-fuse NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2
    if ($LASTEXITCODE -ne 0) {
      throw "SEA blob injection failed. Run `npm install` in apps/cli if postject is missing."
    }
  } finally {
    Pop-Location
  }
}

$ExeSize = [math]::Round((Get-Item $ExePath).Length / 1MB, 1)

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Build completed!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  CLI executable: $ExePath"
Write-Host "  Size: $ExeSize MB"
Write-Host ""
Write-Host "  Smoke test:" -ForegroundColor Cyan
Write-Host "    .\apps\cli\dist\gen2vec_cli.exe --help"
