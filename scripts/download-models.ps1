# download-models.ps1 — AI 模型下载脚本
<#
.SYNOPSIS
  下载 10 个 AI 模型文件到 ComfyUI 便携版的 models/ 目录。

.DESCRIPTION
  用于手动部署和 Electron 自动调用两种场景。
  默认使用 hf-mirror.com 国内镜像。

.PARAMETER DestDir
  目标目录（默认：脚本所在目录）。

.PARAMETER Electron
  Electron 集成模式：输出 MODELDL: 结构化行。

.PARAMETER NoMirror
  直接使用 huggingface.co 而非 hf-mirror.com 镜像。

.PARAMETER MaxRetries
  每个文件的最大重试次数（默认 3）。

.PARAMETER Parallel
  并行下载文件数（默认 3，最大建议不超过 5）。
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

# ── 路径 ──────────────────────────────────────────────────
$ComfyUIDir = Join-Path $DestDir "ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable"
$ModelsDir  = Join-Path $ComfyUIDir "ComfyUI\models"

# ── 检测 aria2c ───────────────────────────────────────────
$UseAria2c = $null -ne (Get-Command "aria2c" -ErrorAction SilentlyContinue)

function Emit {
    param([string]$Type, [string]$Message = "")
    if ($Electron) {
        if ($Message) { Write-Output "${PREFIX}${Type}:${Message}" }
        else { Write-Output "${PREFIX}${Type}" }
    }
}

function Write-Color {
    param([string]$Text, [string]$Color = "White")
    if (-not $Electron) { Write-Host $Text -ForegroundColor $Color }
}

# ── 检测引擎 ──────────────────────────────────────────────
if (-not (Test-Path $ComfyUIDir)) {
    Emit "ENGINE_MISSING" $ComfyUIDir
    Write-Color "`n错误：未找到 ComfyUI 引擎！" Red
    Write-Color "请先双击 ComfyUI-Engine.exe 解压引擎到当前目录。" Yellow
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
    Write-Host "  下载工具: $(if ($UseAria2c) { 'aria2c' } else { 'WebClient' })" -ForegroundColor White
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

# ── 辅助函数 ──────────────────────────────────────────────
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

# ── 单文件下载函数（由子进程调用） ─────────────────────────
function Download-SingleFile {
    param([string]$Url, [string]$DestFile, [int]$Retries)
    $ErrorActionPreference = "Continue"
    for ($i = 0; $i -lt $Retries; $i++) {
        try {
            if ($UseAria2c) {
                $p = Start-Process -FilePath "aria2c" -ArgumentList "--continue=true --auto-file-renaming=false --allow-overwrite=true --split=4 --file-allocation=none --console-log-level=error --dir=""$(Split-Path $DestFile -Parent)"" --out=""$(Split-Path $DestFile -Leaf)"" ""$Url""" -NoNewWindow -Wait -PassThru
                if ($p.ExitCode -eq 0) { return $true }
            } else {
                $wc = New-Object System.Net.WebClient
                $wc.DownloadFile($Url, $DestFile)
                $wc.Dispose()
                return $true
            }
        } catch {
            if ($i -ge $Retries - 1) { throw }
            Start-Sleep -Seconds 3
        }
    }
    return $false
}

# ── 主流程 ────────────────────────────────────────────────
Emit "READY"
Emit "TOTAL" $Models.Count

New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null

$okCount = 0
$skipCount = 0
$failCount = 0
$pending = New-Object System.Collections.ArrayList

# 构建待下载列表（预先做尺寸比对）
foreach ($model in $Models) {
    $destDir  = Join-Path $ModelsDir $model.Subdir
    $destFile = Join-Path $destDir $model.Filename
    $completeFile = "$destFile.complete"

    # 有 complete 标记 → 跳过
    if ((Test-Path $destFile) -and (Test-Path $completeFile)) {
        $sz = Format-FileSize -Bytes (Get-Item $destFile).Length
        Emit "SKIP" "$($model.Filename):$($model.Subdir):${sz}"
        Write-Color "跳过 $($model.Filename) (${sz})" DarkGray
        $skipCount++
        continue
    }

    New-Item -ItemType Directory -Force -Path $destDir | Out-Null

    # 有部分文件 → 远程尺寸比对
    $existingSize = if (Test-Path $destFile) { (Get-Item $destFile).Length } else { 0 }
    if ($existingSize -gt 0) {
        $remoteBytes = Get-RemoteFileSize -Url $model.Url
        if ($remoteBytes -gt 0 -and $existingSize -eq $remoteBytes) {
            [void](New-Item -ItemType File -Force -Path $completeFile)
            $sz = Format-FileSize -Bytes $existingSize
            Emit "SKIP" "$($model.Filename):$($model.Subdir):${sz}"
            Write-Color "跳过 $($model.Filename) (与远程一致, $sz)" DarkGray
            $skipCount++
            continue
        }
        $localStr = Format-FileSize -Bytes $existingSize
        $remoteStr = Format-FileSize -Bytes $remoteBytes
        Emit "CHECK" "$($model.Filename):$($model.Subdir):${localStr}:${remoteStr}"
        Write-Color "校验 $($model.Subdir)/$($model.Filename) — 本地 ${localStr} / 远程 ${remoteStr}" Cyan
        Emit "RESUME" "$($model.Filename):$($model.Subdir):${localStr}"
        Write-Color "续传 $($model.Subdir)/$($model.Filename) (已有 ${localStr})" Yellow
    }
    [void]$pending.Add($model)
}

if ($pending.Count -eq 0) {
    Emit "COMPLETE" "${okCount}:${skipCount}:${failCount}"
    Write-Color "全部模型已就绪。" Green
    if (-not $Electron) { Read-Host "按 Enter 键退出" }
    exit 0
}

# ── 并行下载调度器（不使用 Start-Job，直接用进程并行） ────
# 使用 Start-Process -PassThru 来并行管理多个进程
$running = @{}

while ($pending.Count -gt 0 -or $running.Count -gt 0) {
    # 清理已完成进程
    $finished = @()
    foreach ($pid2 in $running.Keys) {
        $p = $running[$pid2].Process
        $modelInfo = $running[$pid2].Model
        if ($p.HasExited) {
            $destDir2 = Join-Path $ModelsDir $modelInfo.Subdir
            $destFile2 = Join-Path $destDir2 $modelInfo.Filename
            $completeFile2 = "$destFile2.complete"

            if ($p.ExitCode -eq 0 -and (Test-Path $destFile2)) {
                [void](New-Item -ItemType File -Force -Path $completeFile2)
                $szf = Format-FileSize -Bytes (Get-Item $destFile2).Length
                Emit "DONE" "$($modelInfo.Filename):$($modelInfo.Subdir):${szf}"
                Write-Color "  OK 完成 ($szf)" Green
                $okCount++
            } else {
                Emit "ERROR" "$($modelInfo.Filename):$($modelInfo.Subdir):0:下载进程退出码 $($p.ExitCode)"
                Write-Color "  失败" Red
                $failCount++
            }
            $finished += $pid2
        }
    }
    foreach ($pid2 in $finished) { $running.Remove($pid2) }

    # 启动新进程
    while ($running.Count -lt $Parallel -and $pending.Count -gt 0) {
        $model = $pending[0]
        $pending.RemoveAt(0)

        $destDir3 = Join-Path $ModelsDir $model.Subdir
        $destFile3 = Join-Path $destDir3 $model.Filename

        Emit "START" "$($model.Filename):$($model.Subdir):$($model.Size)"
        # 如果已有部分文件，说明是续传，改变提示文字
        if ((Test-Path $destFile3) -and (Get-Item $destFile3).Length -gt 0) {
            Write-Color "↻ 续传 $($model.Subdir)/$($model.Filename)" Yellow
        } else {
            Write-Color "⬇ $($model.Subdir)/$($model.Filename) ($($model.Size))" Yellow
        }

        # 生成包装脚本路径
        $execDir2 = Split-Path -Parent $PSCommandPath
        if (-not $execDir2) { $execDir2 = $PSScriptRoot }
        if (-not $execDir2) { $execDir2 = "." }
        $wrapperPath = Join-Path $execDir2 "dl_$([System.IO.Path]::GetRandomFileName()).ps1"

        # 编写包装脚本
        $wrapperContent = @"
`$ErrorActionPreference = "Continue"
`$url = "$($model.Url)"
`$dest = "$destFile3"
`$retries = $MaxRetries
`$useAria = `$$UseAria2c
for (`$i = 0; `$i -lt `$retries; `$i++) {
    try {
        if (`$useAria) {
            `$p = Start-Process -FilePath "aria2c" -ArgumentList "--continue=true --auto-file-renaming=false --allow-overwrite=true --split=4 --file-allocation=none --console-log-level=error --dir=""`$(Split-Path `$dest -Parent)"" --out=""`$(Split-Path `$dest -Leaf)"" ""`$url""" -NoNewWindow -Wait -PassThru
            if (`$p.ExitCode -eq 0) { exit 0 }
        } else {
            (New-Object System.Net.WebClient).DownloadFile(`$url, `$dest)
            exit 0
        }
    } catch {
        if (`$i -ge `$retries - 1) { exit 1 }
        Start-Sleep -Seconds 3
    }
}
exit 1
"@
        Set-Content -Path $wrapperPath -Value $wrapperContent -Encoding UTF8

        $proc = Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$wrapperPath`"" -NoNewWindow -Wait -PassThru

        # 清理包装脚本
        Remove-Item $wrapperPath -Force -ErrorAction SilentlyContinue

        # 检查结果
        if ($proc.ExitCode -eq 0 -and (Test-Path $destFile3)) {
            [void](New-Item -ItemType File -Force -Path "$destFile3.complete")
            $sz2 = Format-FileSize -Bytes (Get-Item $destFile3).Length
            Emit "DONE" "$($model.Filename):$($model.Subdir):${sz2}"
            Write-Color "  OK 完成 ($sz2)" Green
            $okCount++
        } else {
            Emit "ERROR" "$($model.Filename):$($model.Subdir):0:下载失败"
            Write-Color "  失败" Red
            $failCount++
        }
    }

    if ($running.Count -gt 0) {
        Start-Sleep -Milliseconds 500
    }
}

# ── 完成 ──────────────────────────────────────────────────
Emit "COMPLETE" "${okCount}:${skipCount}:${failCount}"

if (-not $Electron) {
    Write-Host ""
    if ($failCount -gt 0) {
        Write-Host "⚠ $okCount 成功, $skipCount 跳过, $failCount 失败" -ForegroundColor Yellow
    } else {
        Write-Host "完成！$okCount 下载, $skipCount 跳过。" -ForegroundColor Green
    }
}
if (-not $Electron) { Read-Host "按 Enter 键退出" }
if ($failCount -gt 0) { exit 1 } else { exit 0 }
