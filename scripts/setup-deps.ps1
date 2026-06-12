<#
.SYNOPSIS
    开发者一键补全本地开发所需的所有依赖。
.DESCRIPTION
    依次提示并执行：
      1. download-comfyui-engine.ps1  — 下载 ComfyUI 便携版及自定义节点
      2. configure-comfyui.ps1        — 配置 ComfyUI（补丁、Python 包）
      3. download-models.ps1          — 下载 AI 模型到 ComfyUI models/
      4. download-isnet-general-use.ps1 — 下载矢量化 rembg 模型

    每个步骤执行前都会询问确认（y/n），按 n 跳过当前步骤。
.NOTES
    适用于首次拉取仓库后的开发者，也可用于重置依赖。
    所有脚本均在仓库根目录下以相对路径定位，请勿移动本脚本位置。
#>

$ErrorActionPreference = 'Stop'

# ── 定位仓库根目录 ──────────────────────────────────────────────
$ScriptDir = $PSScriptRoot
$RepoRoot  = Resolve-Path (Join-Path $ScriptDir '..')

# ── 步骤定义 ────────────────────────────────────────────────────
$Steps = @(
    @{
        Name        = '下载 ComfyUI 引擎及自定义节点'
        Description = 'scripts/download-comfyui-engine.ps1'
        WorkDir     = Join-Path $RepoRoot 'services\txt2img-api'
        ScriptRel   = 'scripts\download-comfyui-engine.ps1'
    }
    @{
        Name        = '配置 ComfyUI（补丁 / Python 包）'
        Description = 'scripts/configure-comfyui.ps1'
        WorkDir     = Join-Path $RepoRoot 'services\txt2img-api'
        ScriptRel   = 'scripts\configure-comfyui.ps1'
    }
    @{
        Name        = '下载 AI 模型到 ComfyUI models/'
        Description = 'scripts/download-models.ps1'
        WorkDir     = Join-Path $RepoRoot 'services\txt2img-api'
        ScriptRel   = 'scripts\download-models.ps1'
    }
    @{
        Name        = '下载矢量化 rembg 模型'
        Description = 'services\vectorizer-api\models\rembg\download-isnet-general-use.ps1'
        WorkDir     = $RepoRoot
        ScriptRel   = 'services\vectorizer-api\models\rembg\download-isnet-general-use.ps1'
    }
)

Write-Host '═════════════════════════════════════════════════════' -ForegroundColor Cyan
Write-Host '   Gen2Vec ArtFont — 开发依赖一键补全'               -ForegroundColor Cyan
Write-Host '═════════════════════════════════════════════════════' -ForegroundColor Cyan
Write-Host ''

foreach ($Step in $Steps) {
    $fullPath = Resolve-Path (Join-Path $RepoRoot $Step.ScriptRel)

    Write-Host "▶ 步骤：$($Step.Name)" -ForegroundColor Yellow
    Write-Host "   $($Step.Description)" -ForegroundColor DarkGray

    do {
        $answer = Read-Host '   继续？(y/n)'
        $answer = $answer.Trim().ToLower()
    } while ($answer -notin @('y', 'n'))

    if ($answer -eq 'n') {
        Write-Host '   已跳过。' -ForegroundColor Gray
        Write-Host ''
        continue
    }

    Write-Host '   执行中，请稍候…' -ForegroundColor Green
    Write-Host ''

    Push-Location $Step.WorkDir
    try {
        & $fullPath
        if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
            Write-Host "   ❌ 脚本退出码 $LASTEXITCODE" -ForegroundColor Red
            Write-Host '   继续下一步。' -ForegroundColor Gray
        } else {
            Write-Host "   ✅ 完成" -ForegroundColor Green
        }
    } catch {
        Write-Host "   ❌ 执行异常：$_" -ForegroundColor Red
        Write-Host '   继续下一步。' -ForegroundColor Gray
    } finally {
        Pop-Location
    }
    Write-Host ''
}

Write-Host '═════════════════════════════════════════════════════' -ForegroundColor Cyan
Write-Host '   所有步骤执行完毕。'                               -ForegroundColor Cyan
Write-Host '   如有步骤被跳过，可单独运行对应脚本补上。'           -ForegroundColor Cyan
Write-Host '═════════════════════════════════════════════════════' -ForegroundColor Cyan
