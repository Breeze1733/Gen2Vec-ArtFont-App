# download-models.ps1 — AI 模型下载脚本
<#
.SYNOPSIS
  下载 10 个 AI 模型文件到 ComfyUI 便携版的 models/ 目录。

.DESCRIPTION
  用于手动部署和 Electron 自动调用两种场景。
  默认使用 hf-mirror.com 国内镜像。

  手动模式：PowerShell 右键运行，显示人类可读的彩色输出。

  Electron 模式（-Electron）：
  输出结构化文本行，供 Electron 主进程解析并渲染为启动画面进度条：
    READY           — 脚本就绪，开始工作
    ENGINE_OK       — ComfyUI 引擎检测通过
    TOTAL:10        — 共需下载 N 个文件
    SKIP:filename:subdir:size        — 文件已存在，跳过
    START:filename:subdir:size       — 开始下载
    PROGRESS:filename:subdir:pct     — 当前文件下载百分比 (0-100)
    SPEED:filename:subdir:rate       — 实时下载速度 (MB/s)
    ETA:filename:subdir:seconds      — 预计剩余秒数
    CHECK:filename:subdir:local:remote — 远程尺寸比对，本地已有部分文件
    RESUME:filename:subdir:size      — 续传已有部分文件
    DONE:filename:subdir:size        — 下载完成
    ERROR:filename:subdir:code:msg   — 下载失败（含 HTTP 状态码）
    COMPLETE:ok:skip:fail            — 全部完成（ok=成功, skip=跳过, fail=失败）
    ENGINE_MISSING:path              — 引擎目录不存在（退出码 2）

  所有状态行以 "MODELDL:" 为前缀，便于 Electron 过滤。

.PARAMETER DestDir
  目标目录（默认：脚本所在目录）。Electron 传入 extraResources 的 backend/ 路径。

.PARAMETER Electron
  Electron 集成模式：输出 MODELDL: 结构化行，抑制人类可读输出。

.PARAMETER NoMirror
  直接使用 huggingface.co 而非 hf-mirror.com 镜像。

.PARAMETER MaxRetries
  每个文件的最大重试次数（默认 3）。

.PARAMETER Parallel
  并行下载文件数（默认 3，最大建议不超过 5）。

.EXAMPLE
  # 手动使用
  .\download-models.ps1

.EXAMPLE
  # Electron 调用
  .\download-models.ps1 -Electron -DestDir "C:\Program Files\Gen2Vec\resources\backend"
#>

param(
    [string]$DestDir = $PSScriptRoot,
    [switch]$Electron,
    [switch]$NoMirror,
    [int]$MaxRetries = 3,
    [int]$Parallel = 3
)

$ErrorActionPreference = "Stop"

# ── 输出前缀（Electron 模式统一前缀）─────────────────────
$PREFIX = if ($Electron) { "MODELDL:" } else { "" }

# ── 路径 ──────────────────────────────────────────────────
$ComfyUIDir = Join-Path $DestDir "ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable"
$ModelsDir  = Join-Path $ComfyUIDir "ComfyUI\models"

# ── 检测 aria2c ───────────────────────────────────────────
$UseAria2c = $null -ne (Get-Command "aria2c" -ErrorAction SilentlyContinue)

# ── Emit 函数 ─────────────────────────────────────────────
function Emit {
    param(
        [string]$Type,
        [string]$Message = ""
    )
    if ($Electron) {
        if ($Message) {
            Write-Output "${PREFIX}${Type}:${Message}"
        } else {
            Write-Output "${PREFIX}${Type}"
        }
    }
}

# ── 手动模式彩色输出 ──────────────────────────────────────
function Write-Color {
    param([string]$Text, [string]$Color = "White")
    if (-not $Electron) {
        Write-Host $Text -ForegroundColor $Color
    }
}

# ── 检测 ComfyUI 引擎 ─────────────────────────────────────
if (-not (Test-Path $ComfyUIDir)) {
    Emit "ENGINE_MISSING" $ComfyUIDir
    Write-Color "`n错误：未找到 ComfyUI 引擎！" Red
    Write-Color "请先双击 ComfyUI-Engine.exe 解压引擎到当前目录。" Yellow
    if (-not $Electron) {
        Read-Host "按 Enter 键退出"
    }
    exit 2
}
Emit "ENGINE_OK"

if (-not $Electron) {
    $hfDisplay = if ($NoMirror) { "huggingface.co" } else { "hf-mirror.com" }
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  ComfyUI 模型下载器" -ForegroundColor White
    Write-Host "  目标目录: $ModelsDir" -ForegroundColor White
    Write-Host "  镜像源:   $hfDisplay" -ForegroundColor White
    Write-Host "  下载工具: $(if ($UseAria2c) { 'aria2c (多连接, 断点续传)' } else { '.NET HttpClient (断点续传)' })" -ForegroundColor White
    Write-Host "  并发数:   $Parallel" -ForegroundColor White
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
}

# ── 模型清单 ──────────────────────────────────────────────
$HFBase = if ($NoMirror) { "https://huggingface.co" } else { "https://hf-mirror.com" }

$Models = @(
    @{ Subdir = "diffusion_models"; Filename = "z_image_turbo_bf16.safetensors"
       Url = "$HFBase/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors"
       Size = "12.3 GB" },
    @{ Subdir = "unet";              Filename = "flux1-schnell-fp8-e4m3fn.safetensors"
       Url = "$HFBase/Kijai/flux-fp8/resolve/main/flux1-schnell-fp8-e4m3fn.safetensors"
       Size = "11.9 GB" },
    @{ Subdir = "text_encoders";     Filename = "qwen_2.5_vl_7b_fp8_scaled.safetensors"
       Url = "$HFBase/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors"
       Size = "9.4 GB" },
    @{ Subdir = "diffusion_models";  Filename = "qwen-image-2512-Q3_K_M.gguf"
       Url = "$HFBase/unsloth/Qwen-Image-2512-GGUF/resolve/main/qwen-image-2512-Q3_K_M.gguf"
       Size = "~9 GB" },
    @{ Subdir = "text_encoders";     Filename = "qwen_3_4b.safetensors"
       Url = "$HFBase/Comfy-Org/z_image_turbo/resolve/main/split_files/text_encoders/qwen_3_4b.safetensors"
       Size = "8.0 GB" },
    @{ Subdir = "clip";              Filename = "t5xxl_fp8_e4m3fn.safetensors"
       Url = "$HFBase/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors"
       Size = "4.9 GB" },
    @{ Subdir = "loras";             Filename = "Qwen-Image-Lightning-4steps-V1.0.safetensors"
       Url = "$HFBase/lightx2v/Qwen-Image-Lightning/resolve/main/Qwen-Image-Lightning-4steps-V1.0.safetensors"
       Size = "1.7 GB" },
    @{ Subdir = "vae";               Filename = "ae.safetensors"
       Url = "$HFBase/Comfy-Org/z_image_turbo/resolve/main/split_files/vae/ae.safetensors"
       Size = "335 MB" },
    @{ Subdir = "vae";               Filename = "qwen_image_vae.safetensors"
       Url = "$HFBase/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors"
       Size = "254 MB" },
    @{ Subdir = "clip";              Filename = "clip_l.safetensors"
       Url = "$HFBase/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors"
       Size = "246 MB" }
)

# ── 工具函数 ──────────────────────────────────────────────

# HEAD 请求获取远程文件大小
function Get-RemoteFileSize {
    param([string]$Url)
    try {
        $req = [System.Net.WebRequest]::Create($Url)
        $req.Method = "HEAD"
        $req.Timeout = 30000
        $resp = $req.GetResponse()
        if ($resp.ContentLength -ge 0) {
            $size = [long]$resp.ContentLength
            $resp.Close()
            return $size
        }
        $resp.Close()
    } catch {
        # 静默失败
    }
    return -1
}

# 字节数 → 人类可读
function Format-FileSize {
    param([long]$Bytes)
    if ($Bytes -lt 0) { return "?" }
    if ($Bytes -ge 1TB) { return "{0:N2} TB" -f ($Bytes / 1TB) }
    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    return "$Bytes B"
}

# ── aria2c 下载（多连接 + 实时速度上报） ────────────────────
function Invoke-Aria2cDownload {
    param($Model, $DestDir, $DestFile, $CompleteFile)

    $retryCount = 0
    while ($retryCount -lt $MaxRetries) {
        $retryCount++

        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = "aria2c"
        $psi.Arguments = "--continue=true --auto-file-renaming=false --allow-overwrite=true --split=4 --min-split-size=1M --max-connection-per-server=4 --file-allocation=none --console-log-level=error --summary-interval=0 --dir=$DestDir --out=$($Model.Filename) --download-result=hide $($Model.Url)"
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true

        $proc = [System.Diagnostics.Process]::Start($psi)
        $proc.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::BelowNormal

        $lastBytes = if (Test-Path $DestFile) { (Get-Item $DestFile).Length } else { 0 }
        $lastTime = Get-Date

        while (-not $proc.HasExited) {
            Start-Sleep -Milliseconds 1000
            if (Test-Path $DestFile) {
                $curr = (Get-Item $DestFile).Length
                $elapsed = ((Get-Date) - $lastTime).TotalSeconds
                if ($elapsed -ge 1) {
                    $bps = ($curr - $lastBytes) / $elapsed
                    if ($bps -gt 0) {
                        Emit "SPEED" "$($Model.Filename):$($Model.Subdir):$("{0:N1}" -f ($bps / 1MB)) MB/s"
                    }
                    $lastBytes = $curr
                    $lastTime = Get-Date
                }
            }
        }
        $proc.WaitForExit()

        if ($proc.ExitCode -eq 0 -and (Test-Path $DestFile)) {
            [void](New-Item -ItemType File -Force -Path $CompleteFile)
            $sz = Format-FileSize -Bytes (Get-Item $DestFile).Length
            Emit "DONE" "$($Model.Filename):$($Model.Subdir):${sz}"
            Write-Color "   OK 完成 ($sz)" Green
            return $true
        }

        $errMsg = $proc.StandardError.ReadToEnd().Trim()
        if ($retryCount -lt $MaxRetries) {
            Start-Sleep -Seconds 3
        } else {
            if ($errMsg.Length -gt 200) { $errMsg = $errMsg.Substring(0, 200) + "..." }
            Emit "ERROR" "$($Model.Filename):$($Model.Subdir):0:${errMsg}"
            Write-Color "   失败: ${errMsg}" Red
        }
    }
    return $false
}

# ── .NET WebClient 下载（续传 + 实时进度上报） ────────────
function Invoke-WebClientDownload {
    param($Model, $DestFile, $CompleteFile)

    $retryCount = 0
    while ($retryCount -lt $MaxRetries) {
        $retryCount++

        try {
            $existingSize = if (Test-Path $DestFile) { (Get-Item $DestFile).Length } else { 0 }

            # 获取远程总大小（用于计算百分比）
            $remoteTotal = Get-RemoteFileSize -Url $Model.Url
            if ($remoteTotal -le 0) { $remoteTotal = -1 }

            $wc = New-Object System.Net.WebClient
            $startTime = Get-Date
            $script:lastBytes = $existingSize
            $script:lastReport = $startTime
            $script:first = $true

            # 注册进度回调
            Register-ObjectEvent -InputObject $wc -EventName DownloadProgressChanged -Action {
                $e = $Event.SourceEventArgs
                $existing = $Event.MessageData.ExistingSize
                $filename = $Event.MessageData.Filename
                $subdir = $Event.MessageData.Subdir
                $total = $Event.MessageData.TotalBytes
                $currentTotal = $e.BytesReceived + $existing

                if ($total -gt 0) {
                    $pct = [Math]::Min(100, [Math]::Round(($currentTotal / $total) * 100))
                    Write-Output "${Prefix}PROGRESS:${filename}:${subdir}:${pct}"
                }

                $now = Get-Date
                $elapsedSecs = (($now - $script:lastReport).TotalSeconds)
                if ($elapsedSecs -ge 2 -or $script:first) {
                    $bytesDelta = $currentTotal - $script:lastBytes
                    if ($elapsedSecs -gt 0) {
                        $speedMBs = ($bytesDelta / 1MB) / $elapsedSecs
                        if ($speedMBs -ge 0.01) {
                            Write-Output "${Prefix}SPEED:${filename}:${subdir}:$("{0:N1}" -f $speedMBs) MB/s"
                        }
                        if ($total -gt 0 -and $speedMBs -gt 0) {
                            $remainingBytes = $total - $currentTotal
                            if ($remainingBytes -gt 0) {
                                $etaSec = [Math]::Round($remainingBytes / ($speedMBs * 1MB), 0)
                                Write-Output "${Prefix}ETA:${filename}:${subdir}:${etaSec}"
                            }
                        }
                    }
                    $script:lastBytes = $currentTotal
                    $script:lastReport = $now
                    $script:first = $false
                }
            } -MessageData @{
                ExistingSize = $existingSize
                Filename = $Model.Filename
                Subdir = $Model.Subdir
                TotalBytes = $remoteTotal + $existingSize
            } -SupportEvent | Out-Null

            $wc.DownloadFileAsync((New-Object System.Uri($Model.Url)), $DestFile)
            while ($wc.IsBusy) {
                Start-Sleep -Milliseconds 500
            }
            $wc.Dispose()

            if (Test-Path $DestFile) {
                [void](New-Item -ItemType File -Force -Path $CompleteFile)
                $sz = Format-FileSize -Bytes (Get-Item $DestFile).Length
                Emit "DONE" "$($Model.Filename):$($Model.Subdir):${sz}"
                Write-Color "   OK 完成 ($sz)" Green
                return $true
            }
        } catch {
            if ($retryCount -lt $MaxRetries) {
                Start-Sleep -Seconds 3
            } else {
                $msg = ($_.Exception.Message -replace "[\r\n]+", " ").Trim()
                Emit "ERROR" "$($Model.Filename):$($Model.Subdir):0:${msg}"
                Write-Color "   失败: ${msg}" Red
            }
        }
    }
    return $false
}

# ── 主下载调度函数 ────────────────────────────────────────
function Download-File {
    param($Model)

    $destDir  = Join-Path $ModelsDir $Model.Subdir
    $destFile = Join-Path $destDir $Model.Filename
    $completeFile = "$destFile.complete"

    New-Item -ItemType Directory -Force -Path $destDir | Out-Null

    # 步骤1：检查 complete 标记 → 跳过
    if ((Test-Path $destFile) -and (Test-Path $completeFile)) {
        $sz = Format-FileSize -Bytes (Get-Item $destFile).Length
        Emit "SKIP" "$($Model.Filename):$($Model.Subdir):${sz}"
        Write-Color "  跳过 $($Model.Filename) (${sz})" DarkGray
        return "SKIP"
    }

    # 步骤2：检查已有部分文件，对比远程尺寸
    $existingSize = if (Test-Path $destFile) { (Get-Item $destFile).Length } else { 0 }

    if ($existingSize -gt 0) {
        $remoteBytes = Get-RemoteFileSize -Url $Model.Url
        if ($remoteBytes -gt 0 -and $existingSize -eq $remoteBytes) {
            [void](New-Item -ItemType File -Force -Path $completeFile)
            $sz = Format-FileSize -Bytes $existingSize
            Emit "SKIP" "$($Model.Filename):$($Model.Subdir):${sz}"
            Write-Color "  跳过 $($Model.Filename) (本地已与远程一致)" DarkGray
            return "SKIP"
        }
        $localStr = Format-FileSize -Bytes $existingSize
        $remoteStr = Format-FileSize -Bytes $remoteBytes
        Emit "CHECK" "$($Model.Filename):$($Model.Subdir):${localStr}:${remoteStr}"
        Write-Color "  发现已有文件 (本地 ${localStr} / 远程 ${remoteStr})" Cyan
        Emit "RESUME" "$($Model.Filename):$($Model.Subdir):${localStr}"
        Write-Color "  将从 ${localStr} 处续传" Yellow
    }

    Emit "START" "$($Model.Filename):$($Model.Subdir):$($Model.Size)"
    Write-Color "下载 $($Model.Subdir)/$($Model.Filename) ($($Model.Size))" Yellow

    # 步骤3：执行下载
    if ($UseAria2c) {
        $ok = Invoke-Aria2cDownload -Model $Model -DestDir $destDir -DestFile $destFile -CompleteFile $completeFile
    } else {
        $ok = Invoke-WebClientDownload -Model $Model -DestFile $destFile -CompleteFile $completeFile
    }

    return if ($ok) { "DONE" } else { "FAIL" }
}

# ── 主流程 ────────────────────────────────────────────────
Emit "READY"
Emit "TOTAL" $Models.Count

New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null

$okCount = 0
$skipCount = 0
$failCount = 0

# 构建待下载列表（预先做尺寸比对，只保留真正需要下载的）
$pending = New-Object System.Collections.ArrayList
foreach ($model in $Models) {
    $destDir  = Join-Path $ModelsDir $model.Subdir
    $destFile = Join-Path $destDir $model.Filename
    $completeFile = "$destFile.complete"

    if ((Test-Path $destFile) -and (Test-Path $completeFile)) {
        $sz = Format-FileSize -Bytes (Get-Item $destFile).Length
        Emit "SKIP" "$($model.Filename):$($model.Subdir):${sz}"
        Write-Color "跳过 $($model.Filename) (${sz})" DarkGray
        $skipCount++
        continue
    }

    New-Item -ItemType Directory -Force -Path $destDir | Out-Null

    # 检查已有部分文件 → 远程尺寸比对
    $existingSize = if (Test-Path $destFile) { (Get-Item $destFile).Length } else { 0 }
    if ($existingSize -gt 0) {
        $remoteBytes = Get-RemoteFileSize -Url $model.Url
        if ($remoteBytes -gt 0 -and $existingSize -eq $remoteBytes) {
            [void](New-Item -ItemType File -Force -Path $completeFile)
            $sz = Format-FileSize -Bytes $existingSize
            Emit "SKIP" "$($model.Filename):$($model.Subdir):${sz}"
            Write-Color "跳过 $($model.Filename) (本地已与远程一致) ($sz)" DarkGray
            $skipCount++
            continue
        }
        $localStr = Format-FileSize -Bytes $existingSize
        $remoteStr = Format-FileSize -Bytes $remoteBytes
        if ($remoteBytes -gt 0) {
            Emit "CHECK" "$($model.Filename):$($model.Subdir):${localStr}:${remoteStr}"
            Write-Color "校验 $($model.Subdir)/$($model.Filename) — 本地 ${localStr} / 远程 ${remoteStr}" Cyan
        }
        Emit "RESUME" "$($model.Filename):$($model.Subdir):${localStr}"
        Write-Color "续传 $($model.Subdir)/$($model.Filename) (已有 ${localStr})" Yellow
    }

    [void]$pending.Add($model)
}

# 下载调度器
$jobs = @{}
$nextIndex = 0

while ($nextIndex -lt $pending.Count -or $jobs.Count -gt 0) {
    # 检查已完成作业
    $finishedKeys = @()
    foreach ($key in $jobs.Keys) {
        $job = $jobs[$key]
        if ($job.State -eq 'Completed') {
            $result = Receive-Job $job
            Remove-Job $job -ErrorAction SilentlyContinue
            $finishedKeys += $key

            if ($result -eq "DONE") { $okCount++; Write-Color "  OK 完成" Green }
            elseif ($result -eq "SKIP") { $skipCount++ }
            else { $failCount++; Write-Color "  失败" Red }

        } elseif ($job.State -eq 'Failed' -or $job.State -eq 'Stopped') {
            Remove-Job $job -ErrorAction SilentlyContinue
            $finishedKeys += $key
            $failCount++
        }
    }
    foreach ($key in $finishedKeys) { $jobs.Remove($key) }

    # 启动新作业
    while ($jobs.Count -lt $Parallel -and $nextIndex -lt $pending.Count) {
        $model = $pending[$nextIndex]
        $nextIndex++

        if (-not $Electron) {
            Write-Host "⬇ $($model.Subdir)/$($model.Filename) ($($model.Size))" -ForegroundColor Yellow
        }

        $prefixArg = if ($Electron) { $PREFIX } else { "" }
        $job = Start-Job -Name "dl_$nextIndex" -ScriptBlock {
            param($M, $MDir, $Retries, $Aria2c, $Elec, $Pref)
            $Prefix = $Pref
            function Emit {
                param([string]$T, [string]$M2 = "")
                if ($Prefix) {
                    if ($M2) { Write-Output "${Prefix}${T}:${M2}" }
                    else { Write-Output "${Prefix}${T}" }
                } else {
                    # 手动模式：在后台作业中缓存输出，主线程通过 Receive-Job 拿到
                    if ($M2) { Write-Output "${T}:${M2}" }
                    else { Write-Output "${T}" }
                }
            }
            function Format-FileSize {
                param([long]$B)
                if ($B -lt 0) { return "?" }
                if ($B -ge 1TB) { return "{0:N2} TB" -f ($B / 1TB) }
                if ($B -ge 1GB) { return "{0:N2} GB" -f ($B / 1GB) }
                if ($B -ge 1MB) { return "{0:N2} MB" -f ($B / 1MB) }
                if ($B -ge 1KB) { return "{0:N2} KB" -f ($B / 1KB) }
                return "$B B"
            }
            function Get-RemoteFileSize {
                param([string]$U)
                try {
                    $req = [System.Net.WebRequest]::Create($U)
                    $req.Method = "HEAD"; $req.Timeout = 30000
                    $resp = $req.GetResponse()
                    if ($resp.ContentLength -ge 0) {
                        $s = [long]$resp.ContentLength; $resp.Close(); return $s
                    }
                    $resp.Close()
                } catch {}
                return -1
            }
            function Download-Aria2c {
                param($M, $DD, $DF, $CF)
                $rc = 0
                while ($rc -lt $Retries) {
                    $rc++
                    $psi = New-Object System.Diagnostics.ProcessStartInfo
                    $psi.FileName = "aria2c"
                    $psi.Arguments = "--continue=true --auto-file-renaming=false --allow-overwrite=true --split=4 --min-split-size=1M --max-connection-per-server=4 --file-allocation=none --console-log-level=error --summary-interval=0 --dir=$DD --out=$($M.Filename) --download-result=hide $($M.Url)"
                    $psi.RedirectStandardOutput = $true
                    $psi.RedirectStandardError = $true
                    $psi.UseShellExecute = $false
                    $psi.CreateNoWindow = $true
                    $proc = [System.Diagnostics.Process]::Start($psi)
                    $lastB = if (Test-Path $DF) { (Get-Item $DF).Length } else { 0 }
                    $lastT = Get-Date
                    while (-not $proc.HasExited) {
                        Start-Sleep -Milliseconds 1000
                        if (Test-Path $DF) {
                            $curr = (Get-Item $DF).Length
                            $el = ((Get-Date) - $lastT).TotalSeconds
                            if ($el -ge 1 -and ($curr - $lastB) -gt 0) {
                                $bps = ($curr - $lastB) / $el
                                Emit "SPEED" "$($M.Filename):$($M.Subdir):$("{0:N1}" -f ($bps/1MB)) MB/s"
                                $lastB = $curr; $lastT = Get-Date
                            }
                        }
                    }
                    $proc.WaitForExit()
                    if ($proc.ExitCode -eq 0 -and (Test-Path $DF)) {
                        [void](New-Item -ItemType File -Force -Path $CF)
                        $sz = Format-FileSize -Bytes (Get-Item $DF).Length
                        Emit "DONE" "$($M.Filename):$($M.Subdir):${sz}"
                        return "DONE"
                    }
                    $err = $proc.StandardError.ReadToEnd() -replace "[\r\n]+", " "
                    if ($err.Length -gt 200) { $err = $err.Substring(0,200) + "..." }
                    if ($rc -lt $Retries) { Start-Sleep -Seconds 3 }
                    else { Emit "ERROR" "$($M.Filename):$($M.Subdir):0:$err" }
                }
                return "FAIL"
            }
            function Download-WebClient {
                param($M, $DF, $CF)
                $rc = 0
                while ($rc -lt $Retries) {
                    $rc++
                    try {
                        $existing = if (Test-Path $DF) { (Get-Item $DF).Length } else { 0 }
                        $total = Get-RemoteFileSize -U $M.Url
                        if ($total -le 0) { $total = -1 }

                        $wc = New-Object System.Net.WebClient
                        $wc.DownloadFileAsync((New-Object System.Uri($M.Url)), $DF)
                        $lastB = $existing; $lastT = Get-Date
                        while ($wc.IsBusy) {
                            Start-Sleep -Milliseconds 1000
                            if (Test-Path $DF) {
                                $curr = (Get-Item $DF).Length
                                $el = ((Get-Date) - $lastT).TotalSeconds
                                if ($el -ge 1 -and ($curr - $lastB) -gt 0) {
                                    $bps = ($curr - $lastB) / $el
                                    if ($bps -gt 0) {
                                        Emit "SPEED" "$($M.Filename):$($M.Subdir):$("{0:N1}" -f ($bps/1MB)) MB/s"
                                        if ($total -gt 0) {
                                            $pct = [Math]::Min(100, [Math]::Round(($curr / $total) * 100))
                                            Emit "PROGRESS" "$($M.Filename):$($M.Subdir):${pct}"
                                            $remaining = $total - $curr
                                            if ($remaining -gt 0) {
                                                $eta = [Math]::Round($remaining / $bps, 0)
                                                Emit "ETA" "$($M.Filename):$($M.Subdir):${eta}"
                                            }
                                        }
                                    }
                                    $lastB = $curr; $lastT = Get-Date
                                }
                            }
                        }
                        $wc.Dispose()
                        if (Test-Path $DF) {
                            [void](New-Item -ItemType File -Force -Path $CF)
                            $sz = Format-FileSize -Bytes (Get-Item $DF).Length
                            Emit "DONE" "$($M.Filename):$($M.Subdir):${sz}"
                            return "DONE"
                        }
                    } catch {
                        if ($rc -lt $Retries) { Start-Sleep -Seconds 3 }
                        else {
                            $msg = ($_.Exception.Message -replace "[\r\n]+", " ").Trim()
                            Emit "ERROR" "$($M.Filename):$($M.Subdir):0:$msg"
                        }
                    }
                }
                return "FAIL"
            }

            Emit "START" "$($M.Filename):$($M.Subdir):$($M.Size)"

            if ($Aria2c) {
                return Download-Aria2c -M $M -DD (Join-Path $MDir $M.Subdir) -DF (Join-Path (Join-Path $MDir $M.Subdir) $M.Filename) -CF "$(Join-Path (Join-Path $MDir $M.Subdir) $M.Filename).complete"
            } else {
                return Download-WebClient -M $M -DF (Join-Path (Join-Path $MDir $M.Subdir) $M.Filename) -CF "$(Join-Path (Join-Path $MDir $M.Subdir) $M.Filename).complete"
            }
        } -ArgumentList $model, $ModelsDir, $MaxRetries, $UseAria2c, $Electron.IsPresent, $prefixArg

        $jobs["dl_$nextIndex"] = $job
    }

    if ($jobs.Count -gt 0) {
        Start-Sleep -Milliseconds 500
    }
}

# 完成
Emit "COMPLETE" "${okCount}:${skipCount}:${failCount}"

if (-not $Electron) {
    Write-Host ""
    if ($failCount -gt 0) {
        Write-Host "⚠ $okCount 成功, $skipCount 跳过, $failCount 失败（重新运行脚本重试）" -ForegroundColor Yellow
        Write-Host "运行 txt2img-backend.exe 启动服务。" -ForegroundColor White
    } else {
        Write-Host "完成！$okCount 下载, $skipCount 跳过。" -ForegroundColor Green
        Write-Host "运行 txt2img-backend.exe 即可启动服务。" -ForegroundColor White
    }
}

if (-not $Electron) {
    Read-Host "按 Enter 键退出"
}
if ($failCount -gt 0) { exit 1 } else { exit 0 }
