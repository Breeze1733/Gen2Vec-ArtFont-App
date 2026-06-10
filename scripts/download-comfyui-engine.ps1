# download-comfyui-engine.ps1 - download and prepare ComfyUI portable runtime.
<#
.SYNOPSIS
Downloads 7za.exe, ComfyUI Windows portable, extracts it, removes the archive,
then downloads and installs the ComfyUI-GGUF custom node.

.PARAMETER DestDir
Target backend directory. Defaults to the script directory.

.PARAMETER Electron
Electron integration mode: prints ENGINEDL: structured progress lines.

.PARAMETER NoMirror
Use github.com directly instead of trying the mirror first.

.PARAMETER MaxRetries
Maximum retries per download. Default: 3.
#>

param(
    [string]$DestDir = $PSScriptRoot,
    [switch]$Electron,
    [switch]$NoMirror,
    [int]$MaxRetries = 3
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$PREFIX = if ($Electron) { "ENGINEDL:" } else { "" }

$SevenZipExe = Join-Path $DestDir "7za.exe"
$SevenZipZip = Join-Path $DestDir "7za920.zip"
$SevenZipUrl = "https://www.7-zip.org/a/7za920.zip"

$ComfyArchive = Join-Path $DestDir "ComfyUI_windows_portable_nvidia.7z"
$ComfyArchiveComplete = "$ComfyArchive.complete"
$ComfyGithubUrl = "https://github.com/Comfy-Org/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z"
$ComfyMirrorUrls = @(
    "https://gh-proxy.com/$ComfyGithubUrl",
    "https://gh.llkk.cc/$ComfyGithubUrl",
    "https://ghproxy.net/$ComfyGithubUrl",
    "https://ghfast.top/$ComfyGithubUrl",
    "https://hub.gitmirror.com/$ComfyGithubUrl"
)
$EnvComfyUrls = @()
if ($env:COMFYUI_ENGINE_URLS) {
    $EnvComfyUrls = @($env:COMFYUI_ENGINE_URLS -split "[;,]" | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}
$ComfyUrls = if ($EnvComfyUrls.Count -gt 0) {
    $EnvComfyUrls
} elseif ($NoMirror) {
    @($ComfyGithubUrl)
} else {
    @($ComfyMirrorUrls + $ComfyGithubUrl)
}
$ComfyRoot = Join-Path $DestDir "ComfyUI_windows_portable_nvidia"
$ComfyPortable = Join-Path $ComfyRoot "ComfyUI_windows_portable"
$ComfyMain = Join-Path $ComfyPortable "ComfyUI\main.py"

$GgufZip = Join-Path $DestDir "ComfyUI-GGUF.zip"
$GgufUrl = "https://github.com/city96/ComfyUI-GGUF/archive/refs/heads/main.zip"
$CustomNodesDir = Join-Path $ComfyPortable "ComfyUI\custom_nodes"
$GgufNodeDir = Join-Path $CustomNodesDir "ComfyUI-GGUF"
$GgufSentinel = Join-Path $GgufNodeDir "nodes.py"

function Emit {
    param([string]$Type, [string]$Message = "")
    if ($Electron) {
        if ($Message) { Write-Output "${PREFIX}${Type}|${Message}" }
        else { Write-Output "${PREFIX}${Type}" }
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
    return "$Bytes B"
}

function Get-RemoteFileSize {
    param([string]$Url)
    try {
        $req = [System.Net.HttpWebRequest]::Create($Url)
        $req.Method = "HEAD"
        $req.Timeout = 30000
        $req.AllowAutoRedirect = $true
        $req.UserAgent = "Gen2Vec-ArtFont-EngineDownloader/1.0"
        $resp = $req.GetResponse()
        if ($resp.ContentLength -ge 0) {
            $size = [long]$resp.ContentLength
            $resp.Close()
            return $size
        }
        $resp.Close()
    } catch {}
    return -1
}

function Invoke-RangeDownload {
    param(
        [string]$Url,
        [string]$OutputPath
    )

    $existing = if (Test-Path $OutputPath) { [long](Get-Item $OutputPath).Length } else { 0 }
    $request = [System.Net.HttpWebRequest]::Create($Url)
    $request.Method = "GET"
    $request.Timeout = 30000
    $request.ReadWriteTimeout = 30000
    $request.AllowAutoRedirect = $true
    $request.UserAgent = "Gen2Vec-ArtFont-EngineDownloader/1.0"
    if ($existing -gt 0) {
        $request.AddRange($existing)
    }

    try {
        $response = $request.GetResponse()
    } catch [System.Net.WebException] {
        $resp = $_.Exception.Response
        if ($resp -and [int]$resp.StatusCode -eq 416) {
            Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
            $request = [System.Net.HttpWebRequest]::Create($Url)
            $request.Method = "GET"
            $request.Timeout = 30000
            $request.ReadWriteTimeout = 30000
            $request.AllowAutoRedirect = $true
            $request.UserAgent = "Gen2Vec-ArtFont-EngineDownloader/1.0"
            $response = $request.GetResponse()
            $existing = 0
        } else {
            throw
        }
    }

    try {
        $status = [int]$response.StatusCode
        if ($existing -gt 0 -and $status -eq 200) {
            $fileMode = [System.IO.FileMode]::Create
            $existing = 0
        } else {
            $fileMode = [System.IO.FileMode]::OpenOrCreate
        }

        $inputStream = $response.GetResponseStream()
        $outputStream = [System.IO.File]::Open($OutputPath, $fileMode, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
        if ($existing -gt 0) {
            [void]$outputStream.Seek($existing, [System.IO.SeekOrigin]::Begin)
        } else {
            $outputStream.SetLength(0)
        }

        $buffer = New-Object byte[] (1024 * 1024)
        while (($read = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $outputStream.Write($buffer, 0, $read)
        }
    } finally {
        if ($outputStream) { $outputStream.Dispose() }
        if ($inputStream) { $inputStream.Dispose() }
        if ($response) { $response.Close() }
    }
}

function Invoke-DownloadWithRetry {
    param(
        [string]$Name,
        [string]$Url,
        [string]$OutputPath,
        [string]$SizeText
    )

    for ($i = 0; $i -lt $MaxRetries; $i++) {
        try {
            Invoke-RangeDownload -Url $Url -OutputPath $OutputPath
            return
        } catch {
            $lastError = $_.Exception.Message
            if ($i -ge $MaxRetries - 1) {
                throw "${Name}: ${lastError}"
            }
            Start-Sleep -Seconds 3
        }
    }
}

function Invoke-DownloadWithFallback {
    param(
        [string]$Name,
        [string[]]$Urls,
        [string]$OutputPath,
        [string]$SizeText
    )

    $errors = @()
    for ($u = 0; $u -lt $Urls.Count; $u++) {
        $url = $Urls[$u]
        $label = $url
        try { $label = ([System.Uri]$url).Host } catch {}
        Write-Color "  source: $label" DarkGray
        try {
            Invoke-DownloadWithRetry -Name $Name -Url $url -OutputPath $OutputPath -SizeText $SizeText
            return
        } catch {
            $errors += "${label}: $($_.Exception.Message)"
        }
    }

    throw "${Name}: all sources failed ($($errors -join '; '))"
}

function Get-RemoteFileSizeFromFallback {
    param([string[]]$Urls)

    foreach ($url in $Urls) {
        $size = Get-RemoteFileSize -Url $url
        if ($size -gt 0) { return $size }
    }
    return -1
}

function Test-SevenZipArchive {
    param(
        [string]$ArchivePath,
        [string]$SevenZipPath
    )

    if (-not (Test-Path $ArchivePath) -or -not (Test-Path $SevenZipPath)) {
        return $false
    }

    try {
        $archiveDir = Split-Path $ArchivePath -Parent
        $archiveName = Split-Path $ArchivePath -Leaf
        $p = Start-Process -FilePath $SevenZipPath -WorkingDirectory $archiveDir -ArgumentList @(
            't',
            $archiveName
        ) -NoNewWindow -Wait -PassThru
        return $p.ExitCode -eq 0
    } catch {
        return $false
    }
}

function Ensure-ZipAssembly {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
}

function Expand-ZipToDirectory {
    param([string]$ZipPath, [string]$Destination)
    Ensure-ZipAssembly
    if (Test-Path $Destination) {
        Remove-Item -LiteralPath $Destination -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    [System.IO.Compression.ZipFile]::ExtractToDirectory($ZipPath, $Destination)
}

function Finish-Ok {
    param([string]$Name, [string]$Size = "")
    if ($Size) { Emit "DONE" "${Name}|${Size}" }
    else { Emit "DONE" $Name }
    Write-Color "OK $Name" Green
}

function Finish-Skip {
    param([string]$Name, [string]$Size = "")
    if ($Size) { Emit "SKIP" "${Name}|${Size}" }
    else { Emit "SKIP" $Name }
    Write-Color "Skip $Name" DarkGray
}

New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

if (-not $Electron) {
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  ComfyUI engine downloader" -ForegroundColor White
    Write-Host "  Target: $DestDir" -ForegroundColor White
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
}

Emit "READY"
Emit "TOTAL" 4

$okCount = 0
$skipCount = 0
$failCount = 0

try {
    # 1. Download 7za.exe.
    $sevenZipReady = Test-Path $SevenZipExe
    if ($sevenZipReady) {
        $sz = Format-FileSize -Bytes (Get-Item $SevenZipExe).Length
        Finish-Skip "7za.exe" $sz
        $skipCount++
    } else {
        $sizeText = "1.10 MB"
        Emit "START" "7za.exe|$sizeText"
        Write-Color "Download 7za.exe ($sizeText)" Yellow
        Invoke-DownloadWithRetry -Name "7za.exe" -Url $SevenZipUrl -OutputPath $SevenZipZip -SizeText $sizeText

        $tmp7z = Join-Path $DestDir "_7za_extract"
        Expand-ZipToDirectory -ZipPath $SevenZipZip -Destination $tmp7z
        $extracted = Get-ChildItem -LiteralPath $tmp7z -Recurse -Filter "7za.exe" -File | Select-Object -First 1
        if (-not $extracted) { throw "7za.exe not found inside downloaded archive" }
        Copy-Item -LiteralPath $extracted.FullName -Destination $SevenZipExe -Force
        Remove-Item -LiteralPath $tmp7z -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $SevenZipZip -Force -ErrorAction SilentlyContinue
        $sz = Format-FileSize -Bytes (Get-Item $SevenZipExe).Length
        Finish-Ok "7za.exe" $sz
        $okCount++
    }

    # 2. Download ComfyUI portable archive.
    if (Test-Path $ComfyMain) {
        Finish-Skip "ComfyUI_portable" "installed"
        $skipCount++
    } elseif ((Test-Path $ComfyArchive) -and ((Test-Path $ComfyArchiveComplete) -or (Test-SevenZipArchive -ArchivePath $ComfyArchive -SevenZipPath $SevenZipExe))) {
        if (-not (Test-Path $ComfyArchiveComplete)) {
            [void](New-Item -ItemType File -Force -Path $ComfyArchiveComplete)
        }
        $sz = Format-FileSize -Bytes (Get-Item $ComfyArchive).Length
        Finish-Skip "ComfyUI_portable" $sz
        $skipCount++
    } else {
        $sizeText = "2 GB"
        Emit "START" "ComfyUI_portable|$sizeText"
        Write-Color "Download ComfyUI portable ($sizeText)" Yellow

        $existingSize = if (Test-Path $ComfyArchive) { [long](Get-Item $ComfyArchive).Length } else { 0 }
        if ($existingSize -gt 0) {
            $localStr = Format-FileSize -Bytes $existingSize
            Emit "RESUME" "ComfyUI_portable|$localStr"
            Write-Color "Resume ComfyUI portable (existing $localStr)" Yellow

            $remoteBytes = Get-RemoteFileSizeFromFallback -Urls $ComfyUrls
            if ($remoteBytes -gt 0) {
                $remoteStr = Format-FileSize -Bytes $remoteBytes
                Emit "CHECK" "ComfyUI_portable|$localStr|$remoteStr"
                Write-Color "Check ComfyUI portable - local ${localStr} / remote ${remoteStr}" Cyan
            }
        }

        Invoke-DownloadWithFallback -Name "ComfyUI_portable" -Urls $ComfyUrls -OutputPath $ComfyArchive -SizeText $sizeText
        if (-not (Test-SevenZipArchive -ArchivePath $ComfyArchive -SevenZipPath $SevenZipExe)) {
            throw "ComfyUI archive failed integrity test: $ComfyArchive"
        }
        [void](New-Item -ItemType File -Force -Path $ComfyArchiveComplete)
        $sz = Format-FileSize -Bytes (Get-Item $ComfyArchive).Length
        Finish-Ok "ComfyUI_portable" $sz
        $okCount++
    }

    # 3. Extract ComfyUI archive and delete it after success.
    if (Test-Path $ComfyMain) {
        Finish-Skip "Extract_ComfyUI" "installed"
        $skipCount++
    } else {
        if (-not (Test-Path $ComfyArchive)) { throw "ComfyUI archive missing: $ComfyArchive" }
        Emit "START" "Extract_ComfyUI|local"
        Write-Color "Extract ComfyUI portable" Yellow
        if (Test-Path $ComfyRoot) {
            Remove-Item -LiteralPath $ComfyRoot -Recurse -Force
        }
        $p = Start-Process -FilePath $SevenZipExe -WorkingDirectory $DestDir -ArgumentList @(
            'x',
            '-y',
            '-o.',
            (Split-Path $ComfyArchive -Leaf)
        ) -NoNewWindow -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw "7za extract failed with exit code $($p.ExitCode)" }
        if (-not (Test-Path $ComfyMain)) { throw "ComfyUI/main.py not found after extraction" }
        Remove-Item -LiteralPath $ComfyArchive -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $ComfyArchiveComplete -Force -ErrorAction SilentlyContinue
        Finish-Ok "Extract_ComfyUI" "ready"
        $okCount++
    }

    # 4. Download and install ComfyUI-GGUF custom node.
    if (Test-Path $GgufSentinel) {
        Finish-Skip "ComfyUI-GGUF" "installed"
        $skipCount++
    } else {
        New-Item -ItemType Directory -Force -Path $CustomNodesDir | Out-Null
        $needsDownload = $true
        if (Test-Path $GgufZip) {
            $needsDownload = $false
        }

        if ($needsDownload) {
            $sizeText = "200 KB"
            Emit "START" "ComfyUI-GGUF|$sizeText"
            Write-Color "Download ComfyUI-GGUF ($sizeText)" Yellow
            Invoke-DownloadWithRetry -Name "ComfyUI-GGUF" -Url $GgufUrl -OutputPath $GgufZip -SizeText $sizeText
        } else {
            $sizeText = Format-FileSize -Bytes (Get-Item $GgufZip).Length
            Emit "START" "ComfyUI-GGUF|$sizeText"
            Write-Color "Use bundled ComfyUI-GGUF.zip ($sizeText)" Yellow
        }

        $tmpGguf = Join-Path $DestDir "_ComfyUI-GGUF_extract"
        Expand-ZipToDirectory -ZipPath $GgufZip -Destination $tmpGguf
        $sourceDir = Get-ChildItem -LiteralPath $tmpGguf -Directory | Select-Object -First 1
        if (-not $sourceDir) { throw "ComfyUI-GGUF source directory not found after extraction" }
        if (Test-Path $GgufNodeDir) {
            Remove-Item -LiteralPath $GgufNodeDir -Recurse -Force
        }
        Move-Item -LiteralPath $sourceDir.FullName -Destination $GgufNodeDir -Force
        Remove-Item -LiteralPath $tmpGguf -Recurse -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path $GgufSentinel)) { throw "ComfyUI-GGUF nodes.py not found after install" }
        $sz = Format-FileSize -Bytes (Get-Item $GgufZip).Length
        Finish-Ok "ComfyUI-GGUF" $sz
        $okCount++
    }
} catch {
    $failCount++
    $msg = $_.Exception.Message -replace "\|", ":"
    $name = if ($_.InvocationInfo -and $_.InvocationInfo.MyCommand) { $_.InvocationInfo.MyCommand.Name } else { "script" }
    Emit "ERROR" "${name}|1|$msg"
    Write-Color "Error: $msg" Red
}

Emit "COMPLETE" "${okCount}|${skipCount}|${failCount}"

if (-not $Electron) {
    Write-Host ""
    if ($failCount -gt 0) {
        Write-Host "Finished with failures: $okCount ok, $skipCount skipped, $failCount failed" -ForegroundColor Yellow
    } else {
        Write-Host "All done: $okCount ok, $skipCount skipped" -ForegroundColor Green
    }
}

if ($failCount -gt 0) { exit 1 } else { exit 0 }
