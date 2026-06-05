# apps/cli/scripts/build-cli-exe.ps1
# 使用 Node.js SEA 构建 gen2vec_cli.exe 单文件可执行文件
#
# 前置条件:
#   - Node.js 20+ (需要 --experimental-sea-config)
#   - npx postject (自动安装)
#
# 用法:
#   .\build-cli-exe.ps1                  # 默认输出到 dist/gen2vec_cli.exe
#   .\build-cli-exe.ps1 -OutputDir out   # 自定义输出目录

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
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$CheckDir = $CliRoot
Write-Host "[0/5] 检查 package.json..." -ForegroundColor Yellow
$PackageJsonPath = Join-Path $CliRoot "package.json"
if (-not (Test-Path $PackageJsonPath)) {
  Write-Host "       未找到 package.json，正在创建..." -ForegroundColor DarkYellow
  $PackageJson = @{
    name    = "gen2vec-cli"
    type    = "module"
    main    = "bin/gen2vec.mjs"
    private = $true
  } | ConvertTo-Json
  $Utf8NoBom = New-Object System.Text.UTF8Encoding $false
  [System.IO.File]::WriteAllText($PackageJsonPath, $PackageJson, $Utf8NoBom)
  Write-Host "       已创建 package.json (type: module)"
} else {
  Write-Host "       已存在 package.json"
}

# 1. 准备工作目录
Write-Host "[1/5] 准备构建目录..." -ForegroundColor Yellow
Remove-Item -Recurse -Force $DistDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $DistDir -Force | Out-Null
Write-Host "       输出: $DistDir"

# 2. 生成 sea-config.json（不使用 useSnapshot，改用 assets 嵌入 package.json）
Write-Host "[2/5] 生成 SEA 配置文件..." -ForegroundColor Yellow
$SeaConfig = @{
  main    = "./bin/gen2vec.mjs"
  output  = "./$OutputDir/sea-prep.blob"
  disableExperimentalSEAWarning = $true
  assets = @{
    "package.json" = "./package.json"
  }
} | ConvertTo-Json -Compress

# 使用 UTF8 无 BOM 写入
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($ConfigPath, $SeaConfig, $Utf8NoBom)
Write-Host "       入口: bin/gen2vec.mjs"

# 3. 生成 blob
Write-Host "[3/5] 生成 V8 快照 (blob)..." -ForegroundColor Yellow
Push-Location $CliRoot
try {
  # node --experimental-sea-config 的输出走 stderr
  # PowerShell $ErrorActionPreference=Stop + 2>&1 会将 stderr 转为异常
  # 因此使用 $? 而非 try/catch 来检查
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
Write-Host "       运行: npx postject ..."
# npx 首次会下载 postject 包，需要直通控制台让用户看到进度
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
Write-Host "  文件: $ExePath"
Write-Host "  体积: $ExeSize MB"
Write-Host ""
Write-Host "  下一步:" -ForegroundColor Cyan
Write-Host "  1. 测试: $ExePath --help" -ForegroundColor White
Write-Host "  2. 配合 backend/ 目录使用:" -ForegroundColor White
Write-Host "     gen2vec_cli.exe" -ForegroundColor White
Write-Host "     └── backend/" -ForegroundColor White
Write-Host "         ├── txt2img-backend.exe" -ForegroundColor White
Write-Host "         └── vectorizer-backend.exe" -ForegroundColor White
