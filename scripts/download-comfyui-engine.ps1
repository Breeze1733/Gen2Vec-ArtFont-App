# -- download-comfyui-engine.ps1 -- ComfyUI engine + GGUF download script --
<#
.SYNOPSIS
Downloads ComfyUI Windows portable engine and ComfyUI-GGUF custom node.

.PARAMETER DestDir
Target directory (default: script directory). Engine extracts to {DestDir}/ComfyUI_windows_portable_nvidia/.

.PARAMETER Electron
Electron integration mode: outputs ENGINEDL: structured lines.

.PARAMETER NoMirror
Use github.com directly without trying domestic mirrors.

.PARAMETER MaxRetries
Max retries per download (default 3).

.PARAMETER ComfyUIVersion
ComfyUI version tag (default "latest").
#>

param(
    [string]$DestDir = $PSScriptRoot,
    [switch]$Electron,
    [switch]$NoMirror,
    [int]$MaxRetries = 3,
    [string]$ComfyUIVersion = "latest"
)

$ErrorActionPreference = "Stop"
$PREFIX = if ($Electron) { "ENGINEDL:" } else { "" }

# -- Paths --
$PortableParent = Join-Path $DestDir "ComfyUI_windows_portable_nvidia"
$PortableDir    = Join-Path $PortableParent "ComfyUI_windows_portable"
$ComfyUIDir     = Join-Path $PortableDir "ComfyUI"
$CustomNodesDir = Join-Path $ComfyUIDir "custom_nodes"
$GGUFDir        = Join-Path $CustomNodesDir "ComfyUI-GGUF"

# -- Sentinel files --
$ComfyUISentinel = Join-Path $ComfyUIDir "main.py"
$GGUFSentinel    = Join-Path $GGUFDir "nodes.py"

# -- Detect aria2c --
$UseAria2c = $null -ne (Get-Command "aria2c" -ErrorAction SilentlyContinue)

# -- Download sources (ordered: domestic mirrors first, github.com fallback) --
# ghproxy.com pattern: https://ghproxy.com/{full-github-url}
# The Mirror prefix is just the base; Get-ComfyUIDownloadUrl appends the repo path.
$GithubBase    = "https://github.com"
$GhProxyBase   = "https://ghproxy.com/https://github.com"
$MirrorSources = if ($NoMirror) { @($GithubBase) }
                 else { @($GhProxyBase, $GithubBase) }

# ====================================================================
# Helper functions
# ====================================================================

function Emit {
    param([string]$Type, [string]$Message = "")
    if ($Electron) {
        if ($Message) { Write-Output ($PREFIX + $Type + "|" + $Message) }
        else { Write-Output ($PREFIX + $Type) }
    }
}

function Write-Color {
    param([string]$Text, [string]$Color = "White")
    if (-not $Electron) { Write-Host $Text -ForegroundColor $Color }
}

function Format-FileSize {
    param([long]$Bytes)
    if ($Bytes -lt 0) { return "?" }
    if ($Bytes -ge 1TB) { return "{0:N2} TB" -f ($Bytes / 1TB) }
    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    return ($Bytes.ToString() + " B")
}

function Find-7zExe {
    $candidates = @(
        (Get-Command "7z.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        (Get-Command "7z" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
        (Join-Path $env:ProgramFiles "7-Zip\7z.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "7-Zip\7z.exe")
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return $c }
    }
    $local7z = Join-Path $DestDir "_7za.exe"
    if (Test-Path $local7z) { return $local7z }
    return $null
}

function Ensure-7zExe {
    $existing = Find-7zExe
    if ($existing) { return $existing }

    Write-Color "  downloading portable 7za.exe (~600 KB)..." DarkGray
    $local7z = Join-Path $DestDir "_7za.exe"
    $urls = @(
        "https://www.7-zip.org/a/7za920.zip",
        "https://github.com/ip7z/7zip/releases/download/24.09/7za.exe"
    )
    foreach ($u in $urls) {
        try {
            Write-Color ("  trying: " + $u) DarkGray
            if ($u.EndsWith(".zip")) {
                $zipPath = Join-Path $DestDir "_7za_temp.zip"
                $dlResult = Invoke-FileDownload -Url $u -OutputPath $zipPath
                if ($dlResult.Success) {
                    Expand-Archive -Path $zipPath -DestinationPath $DestDir -Force
                    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
                    if (Test-Path $local7z) { return $local7z }
                }
            } else {
                $dlResult = Invoke-FileDownload -Url $u -OutputPath $local7z
                if ($dlResult.Success -and (Test-Path $local7z)) { return $local7z }
            }
        } catch {
            continue
        }
    }
    return $null
}

function Invoke-FileDownload {
    param(
        [string]$Url,
        [string]$OutputPath
    )

    $outDir = Split-Path $OutputPath -Parent
    if (-not (Test-Path $outDir)) {
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
    }

    for ($attempt = 0; $attempt -lt $MaxRetries; $attempt++) {
        try {
            if ($UseAria2c) {
                $outNameArg = Split-Path $OutputPath -Leaf
                if (Test-Path $OutputPath) {
                    Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
                }
                $ariaArgs = @(
                    "--continue=false", "--auto-file-renaming=false",
                    "--allow-overwrite=true", "--split=16", "--min-split-size=1M",
                    "--max-connection-per-server=16", "--file-allocation=none",
                    "--console-log-level=error",
                    "--connect-timeout=10", "--timeout=30",
                    ("--dir=" + $outDir), ("--out=" + $outNameArg), $Url
                )
                $p = Start-Process -FilePath "aria2c" -ArgumentList $ariaArgs -NoNewWindow -Wait -PassThru
                if ($p.ExitCode -eq 0 -and (Test-Path $OutputPath)) {
                    return @{ Success = $true; Size = (Get-Item $OutputPath).Length }
                }
                throw ("aria2c exited with code " + $p.ExitCode)
            } else {
                $request = [System.Net.HttpWebRequest]::Create($Url)
                $request.Method = "GET"
                $request.Timeout = 30000
                $request.ReadWriteTimeout = 60000
                $request.UserAgent = "Gen2Vec-ArtFont-EngineDownloader/1.0"

                $response = $null
                $inputStream = $null
                $outputStream = $null
                try {
                    $response = $request.GetResponse()
                    $status = [int]$response.StatusCode
                    if ($status -ge 300) {
                        throw ("HTTP " + $status)
                    }

                    $fileMode = [System.IO.FileMode]::Create
                    $inputStream = $response.GetResponseStream()
                    $outputStream = [System.IO.File]::Open($OutputPath, $fileMode, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)

                    $buffer = New-Object byte[] (1024 * 1024)
                    while (($read = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                        $outputStream.Write($buffer, 0, $read)
                    }
                } finally {
                    if ($outputStream) { $outputStream.Dispose() }
                    if ($inputStream) { $inputStream.Dispose() }
                    if ($response) { $response.Close() }
                }

                if (Test-Path $OutputPath) {
                    $fileSize = (Get-Item $OutputPath).Length
                    return @{ Success = $true; Size = $fileSize }
                }
                throw ("Download completed but file not found: " + $OutputPath)
            }
        } catch {
            if ($attempt -ge ($MaxRetries - 1)) {
                return @{ Success = $false; Message = $_.Exception.Message }
            }
            Write-Color ("  retry " + ($attempt + 1) + "/" + $MaxRetries + " ...") Yellow
            Start-Sleep -Seconds 3
        }
    }
    return @{ Success = $false; Message = "Max retries exceeded" }
}

function Get-ComfyUIDownloadUrl {
    param([string]$Mirror, [string]$Version)
    if ($Version -eq "latest") {
        return ($Mirror + "/Comfy-Org/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z")
    }
    return ($Mirror + "/Comfy-Org/ComfyUI/releases/download/v" + $Version + "/ComfyUI_windows_portable_nvidia.7z")
}

function Get-GGUFSDownloadUrl {
    param([string]$Mirror)
    return ($Mirror + "/city96/ComfyUI-GGUF/archive/refs/heads/main.zip")
}

# -- Try a download mirror; on failure, try fallbacks --
function Try-DownloadWithFallback {
    param(
        [string]$Component,         # "ComfyUI_portable" or "ComfyUI-GGUF"
        [string[]]$FallbackUrls,    # ordered list of URLs to try
        [string]$OutputPath,        # where to save
        [long]$MinBytes = 1024      # minimum valid file size
    )

    for ($i = 0; $i -lt $FallbackUrls.Count; $i++) {
        $url = $FallbackUrls[$i]
        $label = if ($i -eq 0) { "primary" } else { "fallback #" + $i }
        Write-Color ("  [" + $label + "] " + $url) DarkGray

        $result = Invoke-FileDownload -Url $url -OutputPath $OutputPath
        if (-not $result.Success) {
            Write-Color ("  download failed: " + $result.Message) Yellow
            Remove-Item $OutputPath -Force -ErrorAction SilentlyContinue
            continue
        }

        if ($result.Size -lt $MinBytes) {
            Write-Color ("  file too small (" + $result.Size + " bytes), likely bad response") Yellow
            Remove-Item $OutputPath -Force -ErrorAction SilentlyContinue
            continue
        }

        return @{ Success = $true; Size = $result.Size; Url = $url }
    }

    return @{ Success = $false; Size = 0 }
}

# -- Download and install ComfyUI engine --
function Install-ComfyUIEngine {
    Emit "START" "ComfyUI_portable|~2 GB"

    # Build ordered URL list: pmirror sources, then github.com fallback
    $urls = ($MirrorSources | ForEach-Object { Get-ComfyUIDownloadUrl -Mirror $_ -Version $ComfyUIVersion } | Select-Object -Unique)

    $zipPath = Join-Path $DestDir "ComfyUI_windows_portable_nvidia.7z"
    $dl = Try-DownloadWithFallback -Component "ComfyUI_portable" -FallbackUrls $urls -OutputPath $zipPath -MinBytes (1024 * 1024)

    if (-not $dl.Success) {
        Emit "ERROR" "ComfyUI_portable|download|all sources failed"
        Write-Color "  all download sources failed." Red
        return $false
    }

    $sz = Format-FileSize -Bytes $dl.Size
    Write-Color ("  download complete (" + $sz + "), extracting...") Green

    # -- Extract --
    $sevenZip = Ensure-7zExe
    if ($sevenZip) {
        Write-Color ("  using 7z: " + $sevenZip) DarkGray
        New-Item -ItemType Directory -Force -Path $PortableParent | Out-Null
        $extractArgs = @("x", $zipPath, ("-o" + $PortableParent), "-y", "-mmt=on")
        $extractProc = Start-Process -FilePath $sevenZip -ArgumentList $extractArgs -NoNewWindow -Wait -PassThru
        if ($extractProc.ExitCode -ne 0) {
            Emit "ERROR" ("ComfyUI_portable|extract|7z exit code " + $extractProc.ExitCode)
            Write-Color ("  7z extraction failed (exit code " + $extractProc.ExitCode + ")") Red
            Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
            return $false
        }
    } else {
        Write-Color "  failed to obtain 7z.exe (system not found + download failed)" Red
        Emit "ERROR" "ComfyUI_portable|extract|7z not found"
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        return $false
    }

    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue

    # -- Verify --
    if (-not (Test-Path $ComfyUISentinel)) {
        Emit "ERROR" ("ComfyUI_portable|verify|sentinel not found: " + $ComfyUISentinel)
        Write-Color "  ComfyUI/main.py not found after extraction, check file structure" Red
        return $false
    }

    Emit "DONE" ("ComfyUI_portable|" + $sz)
    Write-Color ("  ComfyUI engine ready (" + $sz + ")") Green
    return $true
}

# -- Download and install ComfyUI-GGUF --
function Install-ComfyUIGGUF {
    Emit "START" "ComfyUI-GGUF|~50 KB"

    $urls = ($MirrorSources | ForEach-Object { Get-GGUFSDownloadUrl -Mirror $_ } | Select-Object -Unique)

    $zipPath = Join-Path $DestDir "ComfyUI-GGUF.zip"
    $dl = Try-DownloadWithFallback -Component "ComfyUI-GGUF" -FallbackUrls $urls -OutputPath $zipPath -MinBytes 1024

    if (-not $dl.Success) {
        Emit "ERROR" "ComfyUI-GGUF|download|all sources failed"
        Write-Color "  all download sources failed." Red
        return $false
    }

    $sz = Format-FileSize -Bytes $dl.Size
    Write-Color ("  download complete (" + $sz + "), installing to custom_nodes...") Green

    New-Item -ItemType Directory -Force -Path $CustomNodesDir | Out-Null

    try {
        $tempExtract = Join-Path $DestDir "_gguf_extract_temp"
        if (Test-Path $tempExtract) {
            Remove-Item -Recurse -Force $tempExtract -ErrorAction SilentlyContinue
        }

        Expand-Archive -Path $zipPath -DestinationPath $tempExtract -Force

        $extractedDir = Get-ChildItem -Path $tempExtract -Directory | Select-Object -First 1
        if (-not $extractedDir) {
            throw "No directory found in zip"
        }

        if (Test-Path $GGUFDir) {
            Remove-Item -Recurse -Force $GGUFDir -ErrorAction SilentlyContinue
        }
        Move-Item -Path $extractedDir.FullName -Destination $GGUFDir -Force

        Remove-Item -Recurse -Force $tempExtract -ErrorAction SilentlyContinue
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
    } catch {
        $errMsg = $_.Exception.Message
        Remove-Item -Recurse -Force $tempExtract -ErrorAction SilentlyContinue
        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        Emit "ERROR" ("ComfyUI-GGUF|extract|" + $errMsg)
        Write-Color ("  GGUF install failed: " + $errMsg) Red
        return $false
    }

    if (-not (Test-Path $GGUFSentinel)) {
        Emit "ERROR" ("ComfyUI-GGUF|verify|sentinel not found: " + $GGUFSentinel)
        Write-Color "  custom_nodes/ComfyUI-GGUF/nodes.py not found after install" Red
        return $false
    }

    Emit "DONE" ("ComfyUI-GGUF|" + $sz)
    Write-Color ("  ComfyUI-GGUF ready (" + $sz + ")") Green
    return $true
}

# ====================================================================
# Main
# ====================================================================

if (-not $Electron) {
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  ComfyUI Engine + GGUF Downloader" -ForegroundColor White
    Write-Host ("  Target: " + $DestDir) -ForegroundColor White
    $toolName = if ($UseAria2c) { "aria2c" } else { "PowerShell Range HTTP" }
    Write-Host ("  Tool:   " + $toolName) -ForegroundColor White
    $srcLabel = if ($NoMirror) { "github.com" } else { "ghproxy.com -> github.com" }
    Write-Host ("  Source: " + $srcLabel) -ForegroundColor White
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
}

Emit "READY"

$components = @()
if (-not (Test-Path $ComfyUISentinel)) { $components += "ComfyUI" }
if (-not (Test-Path $GGUFSentinel))    { $components += "GGUF" }

$totalCount = $components.Count
Emit "TOTAL" ($totalCount.ToString())

if ($totalCount -eq 0) {
    Write-Color "All components ready, nothing to download." Green
    Emit "COMPLETE" "0|0|0"
    if (-not $Electron) { Read-Host "Press Enter to exit" }
    exit 0
}

$okCount = 0
$failCount = 0

if (-not (Test-Path $ComfyUISentinel)) {
    Write-Color "`n[1/2] Downloading ComfyUI engine..." Yellow
    if (Install-ComfyUIEngine) { $okCount++ } else { $failCount++ }
} else {
    Write-Color "`n[1/2] ComfyUI engine already exists, skip." DarkGray
    Emit "SKIP" "ComfyUI_portable"
    $okCount++
}

if (-not (Test-Path $GGUFSentinel)) {
    Write-Color "`n[2/2] Downloading ComfyUI-GGUF..." Yellow
    if (Install-ComfyUIGGUF) { $okCount++ } else { $failCount++ }
} else {
    Write-Color "`n[2/2] ComfyUI-GGUF already exists, skip." DarkGray
    Emit "SKIP" "ComfyUI-GGUF"
    $okCount++
}

$skipCount = $totalCount - $okCount - $failCount
if ($skipCount -lt 0) { $skipCount = 0 }
Emit "COMPLETE" ($okCount.ToString() + "|" + $skipCount.ToString() + "|" + $failCount.ToString())

if (-not $Electron) {
    Write-Host ""
    if ($failCount -gt 0) {
        Write-Host ("Done: " + $okCount + " ok, " + $skipCount + " skip, " + $failCount + " fail") -ForegroundColor Yellow
    } else {
        Write-Host ("Done! " + $okCount + " downloaded, " + $skipCount + " skipped.") -ForegroundColor Green
    }
    Read-Host "Press Enter to exit"
}

if ($failCount -gt 0) { exit 1 } else { exit 0 }
