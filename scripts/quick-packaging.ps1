$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

# 构建 txt2img 后端 EXE
& "$root\services\txt2img-api\scripts\build-backend-exe.ps1"

# 构建 vectorizer 后端 EXE
& "$root\services\vectorizer-api\scripts\build-backend-exe.ps1"

# 构建桌面端
Push-Location "$root\apps\desktop"
npm run electron:dev
Pop-Location
