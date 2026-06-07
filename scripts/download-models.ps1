# -- download-models.ps1 — AI 模型下载脚本 --
<#
.SYNOPSIS
# -- 下载 10 个 AI 模型文件到 ComfyUI 便携版的 models/ 目录。 --

.PARAMETER DestDir
# -- 目标目录（默认：脚本所在目录）。 --

.PARAMETER Electron
# -- Electron 集成模式：输出 MODELDL: 结构化行。 --

.PARAMETER NoMirror
# -- 直接使用 huggingface.co 而非 hf-mirror.com 镜像。 --

.PARAMETER MaxRetries
# -- 每个文件的最大重试次数（默认 3）。 --

.PARAMETER Parallel
# -- 并行下载文件数（默认 3，最大建议不超过 5）。 --
#>

param(
    [string]$DestDir = $PSScriptRoot,
    [switch]$Electron,
    [switch]$NoMirror,
    [int]$MaxRetries = 3,
    [int]$Parallel = 3
)

$ErrorActionPreference = "Stop"
$PREFIX = if ($Electron) { "MODELDL:" } else { "" }

# -- 路径 --
$ComfyUIDir = Join-Path $DestDir "ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable"
$ModelsDir  = Join-Path $ComfyUIDir "ComfyUI\models"

# -- 检测 aria2c --
$UseAria2c = $null -ne (Get-Command "aria2c" -ErrorAction SilentlyContinue)
if (-not $Electron -and -not $PSBoundParameters.ContainsKey("Parallel")) {
    $Parallel = 1
}

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

$global:downloadJobs = @()
$script:downloadCleanupStarted = $false

function Stop-DownloadJobs {
    if ($script:downloadCleanupStarted) { return }
    $script:downloadCleanupStarted = $true

    $jobs = @()
    if ($global:downloadJobs) {
        $jobs += @($global:downloadJobs | ForEach-Object { $_.Job } | Where-Object { $_ })
    }
    $jobs += @(Get-Job -Name "dl_*" -ErrorAction SilentlyContinue)
    $jobs = @($jobs | Where-Object { $_ } | Sort-Object Id -Unique)

    foreach ($job in $jobs) {
        if ($job.State -eq "Running" -or $job.State -eq "NotStarted") {
            Stop-Job -Job $job -ErrorAction SilentlyContinue
        }
        Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    }

    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -eq "aria2c.exe" -and
            ($_.CommandLine -match "hf-mirror|huggingface|safetensors|gguf")
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }

    $global:downloadJobs = @()
}

trap {
    Emit "ERROR" "download-models.ps1|script|130|用户中断，已停止后台下载任务"
    Write-Color "`n已停止后台下载任务。" Yellow
    Stop-DownloadJobs
    exit 130
}

# -- jian ce yin qing --
if (-not (Test-Path $ComfyUIDir)) {
    Emit "ENGINE_MISSING" $ComfyUIDir
    Write-Color "`n错误：未找到 ComfyUI 引擎！" Red
    Write-Color "需要目录: $ComfyUIDir" Yellow
    Write-Color "请先把 ComfyUI-Engine.exe 放在脚本同级目录并完成解压，或用 -DestDir 指向 backend 目录。" Yellow
    if (-not $Electron) { Read-Host "按 Enter 键退出" }
    exit 2
}
Emit "ENGINE_OK"

if (-not $Electron) {
    $hfD = if ($NoMirror) { "huggingface.co" } else { "hf-mirror.com" }
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "  ComfyUI 模型下载器" -ForegroundColor White
    Write-Host "  目标目录: $ModelsDir" -ForegroundColor White
    Write-Host "  镜像源:   $hfD" -ForegroundColor White
    Write-Host "  下载工具: $(if ($UseAria2c) { 'aria2c' } else { 'PowerShell Range HTTP' })" -ForegroundColor White
    Write-Host "  并发数:   $Parallel" -ForegroundColor White
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
}

# -- 模型清单 --
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

# -- 辅助函数 --
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
        $req = [System.Net.WebRequest]::Create($Url)
        $req.Method = "HEAD"; $req.Timeout = 30000
        $resp = $req.GetResponse()
        if ($resp.ContentLength -ge 0) {
            $s = [long]$resp.ContentLength; $resp.Close(); return $s
        }
        $resp.Close()
    } catch {}
    return -1
}

# -- 主流程 --
Emit "READY"
Emit "TOTAL" $Models.Count

New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null

$okCount = 0
$skipCount = 0
$failCount = 0

function Complete-DownloadEntry {
    param($Entry)

    $jobId = $Entry.Job.Id
    $state = $Entry.Job.State
    $resultItems = @(Receive-Job $Entry.Job -ErrorAction SilentlyContinue)
    Remove-Job $Entry.Job -Force -ErrorAction SilentlyContinue
    $result = if ($resultItems.Count -gt 0) { $resultItems[-1] } else { $null }

    $destF = Join-Path (Join-Path $ModelsDir $Entry.Model.Subdir) $Entry.Model.Filename
    if ($state -eq 'Completed' -and $result -and $result.Success -and (Test-Path $destF) -and (Test-Path "$destF.complete")) {
        $sz = Format-FileSize -Bytes (Get-Item $destF).Length
        Emit "DONE" "$($Entry.Model.Filename)|$($Entry.Model.Subdir)|${sz}"
        Write-Color "  OK $($Entry.Model.Subdir)/$($Entry.Model.Filename) ($sz)" Green
        $script:okCount++
    } else {
        $msg = if ($result -and $result.Message) { $result.Message } else { "后台任务状态: $state" }
        Emit "ERROR" "$($Entry.Model.Filename)|$($Entry.Model.Subdir)|0|$msg"
        Write-Color "  失败 $($Entry.Model.Subdir)/$($Entry.Model.Filename): $msg" Red
        $script:failCount++
    }

    $global:downloadJobs = @($global:downloadJobs | Where-Object { $_.Job.Id -ne $jobId })
}

# -- 构建待下载列表（预先做尺寸比对） --
foreach ($model in $Models) {
    $destDir  = Join-Path $ModelsDir $model.Subdir
    $destFile = Join-Path $destDir $model.Filename
    $completeFile = "$destFile.complete"

    if ((Test-Path $destFile) -and (Test-Path $completeFile)) {
        $sz = Format-FileSize -Bytes (Get-Item $destFile).Length
        Emit "SKIP" "$($model.Filename)|$($model.Subdir)|${sz}"
        Write-Color "跳过 $($model.Subdir)/$($model.Filename) (${sz})" DarkGray
        $skipCount++
        continue
    }

    New-Item -ItemType Directory -Force -Path $destDir | Out-Null

    $existingSize = if (Test-Path $destFile) { (Get-Item $destFile).Length } else { 0 }
    if ($existingSize -gt 0) {
        $remoteBytes = Get-RemoteFileSize -Url $model.Url
        if ($remoteBytes -gt 0 -and $existingSize -eq $remoteBytes) {
            [void](New-Item -ItemType File -Force -Path $completeFile)
            $sz = Format-FileSize -Bytes $existingSize
            Emit "SKIP" "$($model.Filename)|$($model.Subdir)|${sz}"
            Write-Color "跳过 $($model.Subdir)/$($model.Filename) (与远程一致, $sz)" DarkGray
            $skipCount++
            continue
        }
        $localStr = Format-FileSize -Bytes $existingSize
        $remoteStr = Format-FileSize -Bytes $remoteBytes
        Emit "CHECK" "$($model.Filename)|$($model.Subdir)|${localStr}|${remoteStr}"
        Write-Color "校验 $($model.Subdir)/$($model.Filename) - 本地 ${localStr} / 远程 ${remoteStr}" Cyan
        Emit "RESUME" "$($model.Filename)|$($model.Subdir)|${localStr}"
        Write-Color "续传 $($model.Subdir)/$($model.Filename) (已有 ${localStr})" Yellow
    }

    Emit "START" "$($model.Filename)|$($model.Subdir)|$($model.Size)"
    Write-Color "下载 $($model.Subdir)/$($model.Filename) ($($model.Size))" Yellow

# -- 真正并行：使用 Start-Job 在后台下载 --
    $job = Start-Job -Name "dl_$([System.IO.Path]::GetRandomFileName())" -ScriptBlock {
        param($M, $MDir, $Retries)
        $ErrorActionPreference = "Stop"
        $destDir  = Join-Path $MDir $M.Subdir
        $destFile = Join-Path $destDir $M.Filename
        $completeFile = "$destFile.complete"
        New-Item -ItemType Directory -Force -Path $destDir | Out-Null

        $useAria = $null -ne (Get-Command "aria2c" -ErrorAction SilentlyContinue)

        function Get-JobFileSize {
            param([string]$Path)
            if (Test-Path $Path) { return [long](Get-Item $Path).Length }
            return 0
        }

        function New-DownloadResult {
            param(
                [bool]$Success,
                [string]$Message,
                [int]$Code = 0
            )
            [pscustomobject]@{
                Success = $Success
                Message = $Message
                Code = $Code
                Bytes = Get-JobFileSize -Path $destFile
            }
        }

        function Invoke-RangeDownload {
            param([string]$Url, [string]$OutputPath)

            $existing = Get-JobFileSize -Path $OutputPath
            $request = [System.Net.HttpWebRequest]::Create($Url)
            $request.Method = "GET"
            $request.Timeout = 30000
            $request.ReadWriteTimeout = 30000
            $request.UserAgent = "Gen2Vec-ArtFont-ModelDownloader/1.0"
            if ($existing -gt 0) {
                $request.AddRange($existing)
            }

            try {
                $response = $request.GetResponse()
            } catch [System.Net.WebException] {
                $resp = $_.Exception.Response
                if ($resp -and [int]$resp.StatusCode -eq 416) {
                    if (Test-Path $OutputPath) {
                        Remove-Item -LiteralPath $OutputPath -Force -ErrorAction SilentlyContinue
                    }
                    $request = [System.Net.HttpWebRequest]::Create($Url)
                    $request.Method = "GET"
                    $request.Timeout = 30000
                    $request.ReadWriteTimeout = 30000
                    $request.UserAgent = "Gen2Vec-ArtFont-ModelDownloader/1.0"
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

        for ($i = 0; $i -lt $Retries; $i++) {
            try {
                if ($useAria) {
                    $p = Start-Process -FilePath "aria2c" -ArgumentList "--continue=true --auto-file-renaming=false --allow-overwrite=true --split=4 --file-allocation=none --console-log-level=error --dir=""$destDir"" --out=""$($M.Filename)"" ""$($M.Url)""" -NoNewWindow -Wait -PassThru
                    if ($p.ExitCode -eq 0) {
                        [void](New-Item -ItemType File -Force -Path $completeFile)
                        return New-DownloadResult -Success $true -Message "aria2c 完成"
                    }
                    throw "aria2c 退出码 $($p.ExitCode)"
                } else {
                    Invoke-RangeDownload -Url $M.Url -OutputPath $destFile
                    [void](New-Item -ItemType File -Force -Path $completeFile)
                    return New-DownloadResult -Success $true -Message "下载完成"
                }
            } catch {
                $lastError = $_.Exception.Message
                if ($i -ge $Retries - 1) {
                    return New-DownloadResult -Success $false -Message $lastError -Code 1
                }
                Start-Sleep -Seconds 3
            }
        }
        return New-DownloadResult -Success $false -Message "达到最大重试次数" -Code 1
    } -ArgumentList $model, $ModelsDir, $MaxRetries

# -- 收集作业引用 --
    if (-not $global:downloadJobs) { $global:downloadJobs = @() }
    $global:downloadJobs += @{ Job = $job; Model = $model }

# -- 控制并发：等待直到活跃作业数小于 $Parallel --
    while ($true) {
        $active = @($global:downloadJobs | Where-Object { $_.Job.State -eq 'Running' -or $_.Job.State -eq 'NotStarted' })
        if ($active.Count -lt $Parallel) { break }
# -- 等待任意一个作业完成 --
        $finishedJob = Wait-Job -Job ($active.Job) -Any -Timeout 1 2>$null
        if ($finishedJob) {
# -- 处理已完成的作业 --
            foreach ($job in @($finishedJob)) {
                $entry = @($global:downloadJobs | Where-Object { $_.Job.Id -eq $job.Id })[0]
                if ($entry) {
                    Complete-DownloadEntry -Entry $entry
                }
            }
        }
    }
}

# -- 等待所有剩余作业完成 --
foreach ($entry in @($global:downloadJobs)) {
    $null = Wait-Job $entry.Job -Timeout 7200 -ErrorAction SilentlyContinue
    Complete-DownloadEntry -Entry $entry
}
$global:downloadJobs = @()

# -- 完成 --
Emit "COMPLETE" "${okCount}|${skipCount}|${failCount}"

if (-not $Electron) {
    Write-Host ""
    if ($failCount -gt 0) {
        Write-Host "完成：$okCount 成功, $skipCount 跳过, $failCount 失败" -ForegroundColor Yellow
    } else {
        Write-Host "完成！$okCount 下载, $skipCount 跳过。" -ForegroundColor Green
    }
}
if (-not $Electron) { Read-Host "按 Enter 键退出" }
Stop-DownloadJobs
if ($failCount -gt 0) { exit 1 } else { exit 0 }
