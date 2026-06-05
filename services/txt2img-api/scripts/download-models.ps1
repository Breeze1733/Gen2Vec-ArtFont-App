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
    SKIP:filename:subdir        — 文件已存在，跳过
    START:filename:subdir:size  — 开始下载
    DONE:filename:subdir:size   — 下载完成
    ERROR:filename:subdir:msg   — 下载失败
    COMPLETE:ok:skip:fail       — 全部完成（ok=成功, skip=跳过, fail=失败）
    ENGINE_MISSING:path         — 引擎目录不存在（退出码 2）

  所有状态行以 "MODELDL:" 为前缀，便于 Electron 过滤。

.PARAMETER DestDir
  目标目录（默认：脚本所在目录）。Electron 传入 extraResources 的 backend/ 路径。

.PARAMETER Electron
  Electron 集成模式：输出 MODELDL: 结构化行，抑制人类可读输出。

.PARAMETER NoMirror
  直接使用 huggingface.co 而非 hf-mirror.com 镜像。

.PARAMETER MaxRetries
  每个文件的最大重试次数（默认 3）。

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
    [int]$MaxRetries = 3
)

$ErrorActionPreference = "Stop"

# ── 输出前缀（Electron 模式统一前缀）─────────────────────
$PREFIX = if ($Electron) { "MODELDL:" } else { "" }

# ── 路径 ──────────────────────────────────────────────────
$ComfyUIDir = Join-Path $DestDir "ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable"
$ModelsDir  = Join-Path $ComfyUIDir "ComfyUI\models"

# ── Emit 函数 ─────────────────────────────────────────────
# Electron 模式下只输出 MODELDL: 行；手动模式下用 Write-Host 彩色输出。
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
    } else {
        # 手动模式的对应输出在调用处处理
    }
}

# ── 检测 ComfyUI 引擎 ─────────────────────────────────────
if (-not (Test-Path $ComfyUIDir)) {
    Emit "ENGINE_MISSING" $ComfyUIDir
    if (-not $Electron) {
        Write-Host "`n❌ 错误：未找到 ComfyUI 引擎！" -ForegroundColor Red
        Write-Host "   请先双击 ComfyUI-Engine.exe 解压引擎到当前目录。" -ForegroundColor Yellow
    }
    if (-not $Electron) {
        Write-Host ""
        Read-Host "按 Enter 键退出"
    }
    exit 2
}
Emit "ENGINE_OK"

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

# ── 主流程 ────────────────────────────────────────────────
Emit "READY"
Emit "TOTAL" $Models.Count

# 确保 models/ 根目录存在
New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null

$okCount = 0
$skipCount = 0
$failCount = 0

foreach ($model in $Models) {
    $destDir  = Join-Path $ModelsDir $model.Subdir
    $destFile = Join-Path $destDir $model.Filename

    # 已存在 → 跳过
    if (Test-Path $destFile) {
        Emit "SKIP" "$($model.Filename):$($model.Subdir)"

        if (-not $Electron) {
            $existingSize = "{0:F2} GB" -f ((Get-Item $destFile).Length / 1GB)
            Write-Host "⏭ $($model.Filename) ($existingSize)" -ForegroundColor DarkGray
        }

        $skipCount++
        continue
    }

    # 创建子目录
    New-Item -ItemType Directory -Force -Path $destDir | Out-Null

    # 下载（带重试）
    Emit "START" "$($model.Filename):$($model.Subdir):$($model.Size)"

    if (-not $Electron) {
        Write-Host "⬇ $($model.Subdir)/$($model.Filename) ($($model.Size))" -ForegroundColor Yellow
    }

    $downloaded = $false
    for ($attempt = 1; $attempt -le $MaxRetries; $attempt++) {
        try {
            Invoke-WebRequest -Uri $model.Url -OutFile $destFile -Resume -ErrorAction Stop

            $actualSize = "{0:F2} GB" -f ((Get-Item $destFile).Length / 1GB)
            Emit "DONE" "$($model.Filename):$($model.Subdir):$actualSize"

            if (-not $Electron) {
                Write-Host "   ✅ 完成 ($actualSize)" -ForegroundColor Green
            }

            $okCount++
            $downloaded = $true
            break
        }
        catch {
            if ($attempt -eq $MaxRetries) {
                $errMsg = $_.Exception.Message -replace "`n|`r", " "
                Emit "ERROR" "$($model.Filename):$($model.Subdir):$errMsg"

                if (-not $Electron) {
                    Write-Host "   ❌ 失败: $errMsg" -ForegroundColor Red
                }

                $failCount++
            }
            else {
                Start-Sleep -Seconds 5
            }
        }
    }
}

# 完成
Emit "COMPLETE" "${okCount}:${skipCount}:${failCount}"

if (-not $Electron) {
    Write-Host ""
    if ($failCount -gt 0) {
        Write-Host "⚠ $okCount 成功, $skipCount 跳过, $failCount 失败（重新运行脚本重试）" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "运行 txt2img-backend.exe 启动服务。" -ForegroundColor White
    } else {
        Write-Host "✅ 完成！$okCount 下载, $skipCount 跳过。" -ForegroundColor Green
        Write-Host ""
        Write-Host "运行 txt2img-backend.exe 即可启动服务。" -ForegroundColor White
    }
}

# exit code: 0 = 全部成功或只有跳过；非零 = 有失败
if (-not $Electron) {
    Write-Host ""
    Read-Host "按 Enter 键退出"
}
if ($failCount -gt 0) { exit 1 } else { exit 0 }
