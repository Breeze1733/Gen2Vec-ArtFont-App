# CLI 工具打包与分发方案

## 1. CLI 现状

CLI 工具位于 `apps/cli/`，是一个纯 Node.js ESM 工具，零外部依赖，仅使用 Node 内置模块。

```
apps/cli/
├── bin/gen2vec.mjs              # 入口：参数解析 + 命令路由
├── src/
│   ├── api.mjs                  # HTTP API 层
│   ├── commands/
│   │   ├── generate.mjs         # generate 命令
│   │   ├── vectorize.mjs        # vectorize 命令
│   │   └── pipeline.mjs         # pipeline 命令
│   └── utils/file.mjs           # 文件读写
└── README.md
```

**当前问题：**
- 无 `package.json`，无版本管理
- 必须用完整路径运行
- CLI 只是一个 HTTP 客户端——假设后端已经在运行
- 未随桌面端一起分发

## 2. 核心设计：CLI 即后端管理器

CLI 不只是一个 HTTP 客户端，它应该像 Electron 一样，**负责后端进程的完整生命周期**：

```
build-gen2vec-cli.ps1 启动
  │
  ├─ 1. 检查 backend/ 目录（跟 exe 同级）
  ├─ 2. 检查/解压 ComfyUI 引擎
  ├─ 3. 检查/下载 AI 模型
  ├─ 4. spawn txt2img-backend + vectorizer-backend
  ├─ 5. 轮询 healthz → 就绪
  ├─ 6. 执行用户命令 (generate / vectorize / pipeline)
  └─ 7. 退出时 → POST /shutdown → kill 子进程
```

与 Electron 的区别只在于：Electron 有 splash 窗口 + GUI，CLI 在终端输出进度。

## 3. 分发方式

CLI 只有一种形态：**`build-gen2vec-cli.ps1` + `backend/` 目录**，exe 启动时自动发现同级 `backend/`。

```
gen2vec/                    # 随便叫什么名字
├── build-gen2vec-cli.ps1             # 用户入口
└── backend/                # 后端文件
    ├── txt2img-backend.exe
    ├── vectorizer-backend.exe
    ├── ComfyUI-Engine.exe
    ├── download-models.ps1
    └── models/rembg/...
```

通过 **两个渠道** 给到用户：

| 渠道 | 怎么给 | 用户看到的样子 |
|------|--------|---------------|
| **随桌面端安装包** | `extraResources` 打进 NSIS | `resources/build-gen2vec-cli.ps1` + `resources/backend/` |
| **独立下载** | 压缩包，解压即用 | `gen2vec/build-gen2vec-cli.ps1` + `gen2vec/backend/` |

内容完全一样，只是放的目录不同。不做 npm 包。

### 3.1 随桌面端时

exe 打进 `resources/`，跟 `backend/` 同级。`gen2vec_cli.bat` 包装：

```batch
@echo off
"%~dp0resources\build-gen2vec-cli.ps1" %*
```

`extraResources` 加一行：

```jsonc
{ "from": "../../apps/cli/dist/gen2vec_cli.exe", "to": "gen2vec_cli.exe" }
```

### 3.2 独立分发时

压缩包解压后就是一个目录，里面 exe 和 backend/ 同级。用户直接运行 `build-gen2vec-cli.ps1`。

## 4. CLI 启动流程（与 Electron 一致）

CLI 的 `runStartupSequence()` 逻辑跟 Electron 的 [main.cjs](../apps/desktop/electron/main.cjs#L417) 完全对应：

```
$ gen2vec generate --text "你好"

  ⏳ 矢量艺术字生成器 v0.1.0
  ──────────────────────────────
  [1/4] 推理引擎... 已就绪 (跳过)
  [2/4] AI 模型... 已就绪 (跳过)
  [3/4] 启动服务...
        矢量化服务... ✓ (127.0.0.1:8000)
        文生图服务... ✓ (127.0.0.1:9001)
  [4/4] 就绪 (3.2s)
  ──────────────────────────────
  正在生成: "你好" → 霓虹风格
  ✓ 已保存: ./outputs/task_20250605_143022/original.png
  耗时: 12.3s

$ gen2vec shutdown

  ⏳ 正在关闭后端服务...
  ✓ 已关闭
```

### 4.1 日常使用（后端已在运行）

如果用户连续执行多条命令，每次启动都走 4 步太慢。优化方式跟 Electron 一样——检测端口是否被占用，`/healthz` 返回的 service 匹配则复用：

```
$ gen2vec generate --text "你好"     # 冷启动 ~30s（含引擎解压/后端启动）
$ gen2vec generate --text "世界"     # 热启动 <1s（后端已在线，跳过步骤 1-4）
$ gen2vec vectorize --input a.png   # 热启动 <1s
$ gen2vec shutdown                  # 手动关闭后端
```

### 4.2 首次运行

```
$ gen2vec generate --text "你好"

  ⏳ 矢量艺术字生成器 v0.1.0
  ──────────────────────────────
  [1/4] 推理引擎... 正在解压 (ComfyUI-Engine.exe)...
        解压完成 (28.3s)
  [2/4] AI 模型...
        首次运行需要下载 10 个模型文件 (约 58 GB)
        是否下载？[Y/n] y
        正在下载 (1/10): z_image_turbo_bf16.safetensors  12.3 GB  45%
        ...
  [3/4] 启动服务... ✓
  [4/4] 就绪
```

### 4.3 降级场景

| 场景 | 行为 |
|------|------|
| backend/ 目录不存在 | 提示用户确认目录结构，列出期望路径 |
| ComfyUI-Engine.exe 不存在 | 跳过引擎解压，后端使用 Pillow stub 降级 |
| 模型全部缺失 + 用户跳过 | 文生图降级为 Pillow stub，矢量化和 health 仍可用 |
| 后端启动超时 (30s) | 打印错误，退出码 1 |

## 5. 具体实现：CLI 改造清单

不改现有的命令逻辑，只加一层启动/退出管理。

### 5.1 入口改造 `bin/gen2vec.mjs`

```js
// 现有逻辑
const command = positionals[0]
switch (command) {
  case 'generate': await runGenerate(...)
  case 'vectorize': await runVectorize(...)
  // ...
}

// 改造后
const command = positionals[0]

if (command === 'shutdown') {
  await shutdownBackends()
  process.exit(0)
}

// 其他命令需要后端在线 → 先确保后端启动
const backendDir = resolveBackendDir()  // exe 同级的 backend/ 目录
const backendReady = await ensureBackends(backendDir, command !== 'health')

if (!backendReady && command !== 'health') {
  console.error('[错误] 后端服务未就绪，无法执行命令')
  process.exit(1)
}

switch (command) {
  case 'generate': await runGenerate(...)
  // ...
}

// 退出前清理（如果是本次启动的）
if (startedByUs) {
  await shutdownBackends()
}
```

### 5.2 新增模块 `src/startup.mjs`

把 Electron `main.cjs` 的启动逻辑搬到 CLI（纯 Node.js，零 Electron 依赖）：

```js
// src/startup.mjs — CLI 后端管理模块

import { spawn } from 'node:child_process'
import { resolve, join } from 'node:path'
import { existsSync, accessSync } from 'node:fs'
import { constants } from 'node:fs'

// ── 路径解析 ──
// exe 同级的 backend/ 目录
// Node.js SEA 模式: process.execPath 是 exe 路径
// 普通 node 模式: process.argv[1] 是 gen2vec.mjs 路径
function resolveBackendDir() {
  const exeDir = dirname(process.execPath)
  // 优先检查 exe 同级
  const candidate = join(exeDir, 'backend')
  if (existsSync(candidate)) return candidate
  // 开发模式：检查项目根目录
  return null
}

// ── 跟 main.cjs 完全对应的函数 ──
// isComfyUIExtracted(), extractComfyUI(),
// checkModelsExist(), downloadModels(),
// spawnBackend(), waitForHealthz(),
// startBackends(), checkBackendHealth(),
// runStartupSequence()
//
// 区别只在于进度输出：main.cjs 发 IPC 给 splash，
// CLI 用 console.log / process.stdout.write
```

### 5.3 退出清理

```js
// 进程退出时自动杀子进程
let backendProcs = []

process.on('exit', () => {
  for (const proc of backendProcs) {
    try { proc.kill() } catch {}
  }
})

// 也响应 SIGINT (Ctrl+C)
process.on('SIGINT', async () => {
  console.log('\n正在关闭后端...')
  await shutdownBackends()
  process.exit(0)
})
```

## 6. 构建：Node.js SEA 单文件 EXE

跟桌面端一样，CLI 用 Node.js SEA 构建成单个 `build-gen2vec-cli.ps1`（~70 MB）。

```powershell
# apps/cli/scripts/build-cli-exe.ps1
.\scripts\build-cli-exe.ps1
# 产物: apps/cli/dist/build-gen2vec-cli.ps1 (~70 MB)
```

构建脚本见附录 A。

## 7. 完整构建流程

```powershell
# 1. 构建 CLI EXE
cd apps/cli
.\scripts\build-cli-exe.ps1
# → dist/build-gen2vec-cli.ps1

# 2. 构建后端 EXE
cd services/txt2img-api
.\scripts\build-backend-exe.ps1

cd services/vectorizer-api
.\scripts\build-backend-exe.ps1

# 3. 组装独立分发包
#    手动或脚本：把 build-gen2vec-cli.ps1 + backend/ 目录放一起，打包 tar.gz
cd apps/cli
.\scripts\package-cli-release.ps1
# → dist/gen2vec-v0.1.0.tar.gz

# 4. 构建 Electron 安装包（含 CLI）
cd apps/desktop
npm run electron:build
# → release/矢量艺术字生成器 Setup x.x.x.exe
```

## 8. 待实现清单

- [ ] `apps/cli/src/startup.mjs` — CLI 后端管理模块（从 main.cjs 移植）
- [ ] `apps/cli/bin/gen2vec.mjs` — 入口改造：启动前先 ensureBackends
- [ ] `apps/cli/scripts/build-cli-exe.ps1` — Node.js SEA 构建脚本
- [ ] `apps/cli/scripts/package-cli-release.ps1` — 组装独立分发包
- [ ] `apps/desktop/gen2vec_cli.bat` — 包装脚本
- [ ] `apps/desktop/package.json` — 添加 `build-gen2vec-cli.ps1` 到 `extraResources`

---

## 附录 A：Node.js SEA 构建脚本

```powershell
# apps/cli/scripts/build-cli-exe.ps1

param(
  [string]$OutputDir = "dist"
)

$ErrorActionPreference = "Stop"
$CliRoot = Split-Path -Parent $PSScriptRoot

$DistDir = Join-Path $CliRoot $OutputDir
Remove-Item -Recurse -Force $DistDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $DistDir -Force | Out-Null

# 1. 生成 sea-config.json
$SeaConfig = @{
  main = "./bin/gen2vec.mjs"
  output = "./dist/sea-prep.blob"
  disableExperimentalSEAWarning = $true
} | ConvertTo-Json

$SeaConfigPath = Join-Path $CliRoot "sea-config.json"
$SeaConfig | Set-Content -Path $SeaConfigPath -Encoding UTF8

# 2. 生成 blob
Push-Location $CliRoot
node --experimental-sea-config $SeaConfigPath
Pop-Location

# 3. 复制 node.exe 并注入 blob
$NodeExe = (Get-Command node).Source
$TargetExe = Join-Path $DistDir "build-gen2vec-cli.ps1"
Copy-Item $NodeExe $TargetExe

npx postject $TargetExe NODE_SEA_BLOB (Join-Path $DistDir "sea-prep.blob") `
  --sentinel-fuse NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2

# 4. 清理
Remove-Item $SeaConfigPath -ErrorAction SilentlyContinue
Remove-Item (Join-Path $DistDir "sea-prep.blob") -ErrorAction SilentlyContinue

$Size = [math]::Round((Get-Item $TargetExe).Length / 1MB, 1)
Write-Host "✅ build-gen2vec-cli.ps1 构建完成 ($Size MB)" -ForegroundColor Green
```

## 附录 B：独立分发包组装脚本

```powershell
# apps/cli/scripts/package-cli-release.ps1

param(
  [string]$Version = "0.1.0",
  [string]$OutputDir = "dist"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$DistDir = Join-Path $Root $OutputDir
$ReleaseDir = Join-Path $DistDir "gen2vec-v$Version"

# 1. 确保 CLI EXE 已构建
if (-not (Test-Path (Join-Path $DistDir "build-gen2vec-cli.ps1"))) {
  Write-Host "先构建 CLI EXE..." -ForegroundColor Yellow
  & (Join-Path $PSScriptRoot "build-cli-exe.ps1")
}

# 2. 创建发布目录
Remove-Item -Recurse -Force $ReleaseDir -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null

# 3. 复制 CLI EXE
Copy-Item (Join-Path $DistDir "build-gen2vec-cli.ps1") $ReleaseDir

# 4. 复制后端文件
$BackendSrc = Join-Path $Root ".." ".." "services"
Copy-Item (Join-Path $BackendSrc "txt2img-api\dist\*") (Join-Path $ReleaseDir "backend") -Recurse
Copy-Item (Join-Path $BackendSrc "vectorizer-api\dist\*") (Join-Path $ReleaseDir "backend") -Recurse

# 5. 打包
$ArchiveName = "gen2vec-v$Version.zip"
Compress-Archive -Path $ReleaseDir -DestinationPath (Join-Path $DistDir $ArchiveName) -Force

Write-Host "✅ 独立分发包: $DistDir\$ArchiveName" -ForegroundColor Green
```
