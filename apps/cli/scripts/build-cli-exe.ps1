# apps/cli/scripts/build-cli-exe.ps1
# 使用 Node.js SEA 构建 gen2vec_cli.exe 单文件可执行文件
#
# 构建产物供 Electron 安装包的 extraResources 收集，随桌面端一起分发。
#
# 前置条件:
#   - Node.js 20+ (需要 --experimental-sea-config)
#   - npx postject (自动安装)
#
# 用法:
#   .\build-cli-exe.ps1                        # 默认输出到 dist/gen2vec_cli.exe
#   .\build-cli-exe.ps1 -OutputDir ..\desktop\resources  # 直接输出到 desktop 资源目录

param(
  [string]$OutputDir = "dist"
)

# 设置 UTF-8 编码，避免中文乱码
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CliRoot = Split-Path -Parent $ScriptDir

$DistDir = Join-Path $CliRoot $OutputDir
$BlobPath = Join-Path $DistDir "sea-prep.blob"
$ExePath = Join-Path $DistDir "gen2vec_cli.exe"
$ConfigPath = Join-Path $CliRoot "sea-config.json"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Gen2Vec CLI — Node.js SEA 构建" -ForegroundColor Cyan
Write-Host "  定位: Electron 安装包附带命令行工具" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 准备工作目录
Write-Host "[1/5] 准备构建目录..." -ForegroundColor Yellow
Remove-Item -Recurse -Force $DistDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $DistDir -Force | Out-Null
Write-Host "       输出: $DistDir"

# 2. 生成 sea-config.json
Write-Host "[2/5] 生成 SEA 配置文件..." -ForegroundColor Yellow
$SeaConfig = @{
  main    = "./bin/gen2vec.mjs"
  output  = "./$OutputDir/sea-prep.blob"
  disableExperimentalSEAWarning = $true
  assets = @{
    "package.json" = "./package.json"
  }
} | ConvertTo-Json -Compress

$Utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($ConfigPath, $SeaConfig, $Utf8NoBom)
Write-Host "       入口: bin/gen2vec.mjs"

# 3. 生成 blob
Write-Host "[3/5] 生成 V8 快照 (blob)..." -ForegroundColor Yellow
Push-Location $CliRoot
try {
  $savedPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $null = node --experimental-sea-config $ConfigPath 2>&1
  $success = $LASTEXITCODE -eq 0
  $ErrorActionPreference = $savedPreference
  if (-not $success) {
    throw "SEA config 生成失败 (exit code: $LASTEXITCODE)"
  }
  Write-Host "       blob: $BlobPath"
} finally {
  Pop-Location
}

# 4. 复制 node.exe
Write-Host "[4/5] 复制 Node.js 运行时..." -ForegroundColor Yellow
$NodeExe = (Get-Command node).Source
Copy-Item $NodeExe $ExePath -Force
Write-Host "       源: $NodeExe"
Write-Host "       目标: $ExePath"

# 5. 注入 blob
Write-Host "[5/5] 注入 SEA blob..." -ForegroundColor Yellow
$savedPreference = $ErrorActionPreference
$ErrorActionPreference = "Continue"
cmd /c "npx postject `"$ExePath`" NODE_SEA_BLOB `"$BlobPath`" --sentinel-fuse NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2"
$success = $LASTEXITCODE -eq 0
$ErrorActionPreference = $savedPreference
if (-not $success) {
  throw "postject 注入失败 (exit code: $LASTEXITCODE)"
}

# 6. 清理临时文件
Write-Host ""
Write-Host "[清理] 删除临时文件..." -ForegroundColor Yellow
Remove-Item $ConfigPath -ErrorAction SilentlyContinue
Remove-Item $BlobPath -ErrorAction SilentlyContinue

# 7. 统计
$ExeSize = [math]::Round((Get-Item $ExePath).Length / 1MB, 1)

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  ✅ 构建完成!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  CLI 可执行文件: $ExePath"
Write-Host "  体积: $ExeSize MB"
Write-Host ""
Write-Host "  下一步:" -ForegroundColor Cyan
Write-Host "  将此文件放入 desktop 构建的 extraResources:" -ForegroundColor White
Write-Host `    "extraResources": [` -ForegroundColor Gray
Write-Host `      { "from": "path/to/gen2vec_cli.exe", "to": "../gen2vec_cli.exe" }` -ForegroundColor Gray
Write-Host `    ]` -ForegroundColor Gray
Write-Host ""
Write-Host "  安装后用户可在安装目录下直接运行:" -ForegroundColor White
Write-Host "    gen2vec_cli --help" -ForegroundColor Cyan
Write-Host "    gen2vec_cli pipeline --text `"你好`" --prompt `"霓虹`"" -ForegroundColor Cyan
