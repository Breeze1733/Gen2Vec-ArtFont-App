<#
.SYNOPSIS
    下载 isnet-general-use.onnx 模型文件并校验 MD5。
.DESCRIPTION
    从 rembg 官方 GitHub Release 下载模型，同时计算实际 MD5，
    与预期值比对，校验不通过则删除文件并退出。
.NOTES
    本脚本与 .bat 版本功能完全一致，并存于同一目录。
#>

$ErrorActionPreference = 'Stop'

$ModelName = 'isnet-general-use.onnx'
$ModelUrl  = 'https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx'
$ModelMd5  = 'FC16EBD8B0C10D971D3513D564D01E29'
$ModelPath = Join-Path -Path $PSScriptRoot -ChildPath $ModelName

Write-Host "Downloading ${ModelName}..." -ForegroundColor Cyan

try {
    Invoke-WebRequest -Uri $ModelUrl -OutFile $ModelPath
} catch {
    Write-Host 'Download failed.' -ForegroundColor Red
    exit 1
}

Write-Host 'Verifying MD5 checksum...' -ForegroundColor Cyan
$actualMd5 = (Get-FileHash -Algorithm MD5 -LiteralPath $ModelPath).Hash

if ($actualMd5 -ne $ModelMd5) {
    Write-Host 'Checksum mismatch.' -ForegroundColor Red
    Write-Host "Expected: $ModelMd5"
    Write-Host "Actual:   $actualMd5"
    Remove-Item -LiteralPath $ModelPath -Force
    exit 1
}

Write-Host "Model ready: $ModelPath" -ForegroundColor Green
