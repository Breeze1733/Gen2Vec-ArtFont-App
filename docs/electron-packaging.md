# Electron 桌面端打包与分发方案

## 1. 总体架构

```
┌──────────────────────────────────────────────────┐
│                   Electron 壳                      │
│  ┌─────────────┐  ┌────────────────────────────┐ │
│  │   main.cjs   │  │     renderer (Vue 3)        │ │
│  │  (主进程)     │──│  App.vue / api.js / ...     │ │
│  │  IPC 代理    │  │                            │ │
│  └──────┬──────┘  └────────────────────────────┘ │
│         │                                         │
│         │ HTTP (localhost)                        │
│         ▼                                         │
│  ┌─────────────────┐  ┌──────────────────────┐   │
│  │ txt2img-backend │  │  vectorizer-backend   │   │
│  │   :9001         │  │    :8000              │   │
│  │ (FastAPI)       │  │  (FastAPI)            │   │
│  └───────┬─────────┘  └──────────────────────┘   │
│          │                                        │
│          │ spawn + 端口轮询 (8188)                  │
│          ▼                                        │
│  ┌─────────────────────────────────────────┐      │
│  │         ComfyUI_windows_portable          │      │
│  │    (python_embeded + CUDA + 模型)         │      │
│  └─────────────────────────────────────────┘      │
└──────────────────────────────────────────────────┘
```

### 1.1 进程职责划分（关键设计原则）

三层进程中，**每层只对自己的直接子进程负责**，不跨层管理：

```
Electron ──spawn──→ txt2img-backend.exe ──spawn──→ ComfyUI (python_embeded)
          ──spawn──→ vectorizer-backend.exe
```

| 进程 | 管理者 | 职责 |
|------|--------|------|
| **Electron** | 用户 | 文件准备（下载引擎、下载模型）、spawn 两个 FastAPI 后端、轮询 healthz、退出时调 /shutdown |
| **txt2img-backend.exe** | **Electron** | 管理 ComfyUI 进程的完整生命周期（spawn、端口轮询、config 写入、退出时清理） |
| **ComfyUI** | **txt2img-backend.exe** | GPU 推理 |

**Electron 不直接管理 ComfyUI。** ComfyUI 是 txt2img-backend 的内部实现细节。Electron 只关心两件事：

1. txt2img-backend 启动前，ComfyUI 的文件（目录 + 模型）已经就位
2. `GET /healthz` 返回 200 时，整个文生图链路（含 ComfyUI）已就绪

这样做的好处：
- Electron 不用理解 ComfyUI 的命令行参数、config.ini、network_mode 等细节
- ComfyUI 进程生命周期与 txt2img-backend 绑定，不会出现孤儿进程
- 未来 txt2img-backend 内部切换推理引擎，Electron 零改动

## 2. 分发包组成

### 2.1 安装包内文件

```
矢量艺术字生成器 Setup.exe  (NSIS 安装包)
│
└─ 安装到用户选择的目录后:
    ├── 矢量艺术字生成器.exe          (Electron 主程序)
    ├── resources/
    │   ├── app.asar                  (前端 + Electron 代码)
    │   └── backend/                  (extraResources)
    │       ├── txt2img-backend.exe   (文生图后端, ~27 MB)
    │       ├── vectorizer-backend.exe  (矢量化后端)
    │       ├── models/                  (矢量化模型)
    │       │   └── rembg/
    │       │       └── isnet-general-use.onnx
    │       ├── ComfyUI-GGUF.zip               (GGUF 自定义节点, ~40 KB)
    │       ├── download-comfyui-engine.ps1 (ComfyUI 引擎 + GGUF 下载脚本)
    │       ├── download-models.ps1   (模型下载脚本)
    │       └── README.md
    └── ... (Electron 运行时文件)
```

### 2.2 首次运行后目录

```
{安装目录}/
├── 矢量艺术字生成器.exe
├── resources/
│   ├── app.asar
│   └── backend/
│       ├── txt2img-backend.exe
│       ├── vectorizer-backend.exe
│       ├── models/                                 ← 矢量化模型 (与 EXE 同级)
│       │   └── rembg/
│       │       └── isnet-general-use.onnx
│       ├── 7za.exe                                    ← 解压工具
│       ├── ComfyUI-GGUF.zip                          ← GGUF 节点
│       ├── download-comfyui-engine.ps1              ← 引擎下载脚本
│       ├── download-models.ps1
│       ├── ComfyUI_windows_portable_nvidia/    ← 下载解压产物
│       │   └── ComfyUI_windows_portable/
│       │       ├── python_embeded/
│       │       ├── ComfyUI/
│       │       │   ├── main.py
│       │       │   ├── custom_nodes/
│       │       │   └── models/                 ← 模型下载到这里
│       │       │       ├── diffusion_models/
│       │       │       ├── unet/
│       │       │       ├── text_encoders/
│       │       │       ├── clip/
│       │       │       ├── loras/
│       │       │       └── vae/
│       │       └── user/
│       │           └── __manager/
│       │               └── config.ini           ← 自动写入 network_mode=offline
└── 用户文档/
    └── Gen2Vec-ArtFont-App/
        └── outputs/                             ← 生成产物输出目录
```

## 3. 启动流程

每次启动都遵循同一个流程，其中"下载引擎"和"下载模型"两步通过检测文件是否存在自动跳过，大部分用户只在首次遇到。

```
应用启动 (每次都会走)
  │
  ├─ 1. 显示启动画面 (splash window)，展示当前操作和进度
  │
  ├─ 2. 检查并下载 ComfyUI  ← 仅首次
  │     if ComfyUI_windows_portable_nvidia/ComfyUI_windows_portable/ComfyUI/main.py 不存在:
  │       spawn powershell -File download-comfyui-engine.ps1 -Electron -DestDir backend/
  │       等待下载 + 解压完成（输出 ENGINEDL: 行，检查 sentinel 文件）
  │     else → 跳过此步，直接进入 3
  │
  ├─ 3. 检查并下载模型  ← 仅首次（或模型不完整时）
  │     if models/vae/ae.safetensors 不存在 (哨兵文件):
  │       spawn powershell -File download-models.ps1 -Electron
  │       逐行解析输出 (MODELDL: 前缀), 更新进度条
  │     进度: "正在下载模型 (1/10)..."
  │     else → 跳过此步，直接进入 4
  │
  ├─ 4. 启动后端服务  ← 每次都会走
  │     spawn txt2img-backend.exe
  │     spawn vectorizer-backend.exe
  │     轮询 http://127.0.0.1:9001/healthz (最多 30s)
  │     轮询 http://127.0.0.1:8000/healthz (最多 30s)
  │     进度: "正在启动服务..."
  │
  └─ 5. 全部就绪 → 关闭启动画面 → 打开主窗口
```

### 3.1 首次启动（安装后第一次运行）

上面 5 步全部执行。用户会看到：解压进度 → 模型下载进度条 → 服务启动 → 进入主界面。

预计耗时：解压 ~30s + 下载 30min-2h + 启动 ~30s。

### 3.2 日常启动（第 2 次及以后）

步骤 2（解压）和步骤 3（下载）检测到文件已存在，**直接跳过**。实际只执行：

1. 显示启动画面
2. ~~解压~~ → 跳过
3. ~~下载模型~~ → 跳过
4. spawn 后端 → 轮询 healthz → 就绪
5. 打开主窗口

预计耗时：~30s（后端启动 + ComfyUI 冷启动）。

### 3.3 降级策略

| 场景 | 处理方式 |
|------|----------|
| ComfyUI 解压失败 | 提示用户重新安装，退出应用 |
| 模型下载全部失败 + 用户跳过 | 文生图功能不可用，提示用户稍后通过菜单触发下载 |
| 模型下载部分失败 | 已下载的模型可用，缺失模型对应工作流自动跳过 |
| 后端启动超时 (30s) | 提示检查端口占用，用户可重试 |

## 4. 进程生命周期管理

### 4.1 启动后端

```javascript
// 伪代码示例
const { spawn } = require('child_process')
const backendDir = path.join(process.resourcesPath, 'backend')

// 启动文生图后端（cwd 决定 ComfyUI portable 查找路径）
const txt2imgProc = spawn(
  path.join(backendDir, 'txt2img-backend.exe'),
  [],
  {
    cwd: backendDir,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  }
)

// 启动矢量化后端（cwd 决定 models/rembg/ 查找路径）
const vectorizerProc = spawn(
  path.join(backendDir, 'vectorizer-backend.exe'),
  [],
  {
    cwd: backendDir,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  }
)

// 轮询 healthz
async function waitForReady(url, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const resp = await fetch(url)
      if (resp.ok) return true
    } catch {}
    await sleep(1000)
  }
  throw new Error(`Backend at ${url} did not become ready within ${timeoutMs}ms`)
}

await Promise.all([
  waitForReady('http://127.0.0.1:9001/healthz'),
  waitForReady('http://127.0.0.1:8000/healthz'),
])
```

### 4.2 关闭后端

```javascript
// 应用退出前 — 使用 before-quit + preventDefault 确保 /shutdown 请求发出后再退出
app.on('before-quit', (event) => {
  event.preventDefault()   // 阻止默认退出，等待 TCP 包发出

  // 向两个后端 POST /shutdown
  for (const url of SHUTDOWN_URLS) {
    const req = net.request({
      method: 'POST',
      protocol: 'http:',
      hostname: '127.0.0.1',
      port: url.port,
      path: '/shutdown',
    })
    req.on('error', () => {})
    req.setHeader('Content-Type', 'application/json')
    req.write(JSON.stringify({}))
    req.end()
  }

  // 兜底: 杀掉直接子进程（txt2img-backend.exe, vectorizer-backend.exe）
  // 注意: ComfyUI 是 txt2img-backend 的子进程，会在 /shutdown 中被清理
  txt2imgProc?.kill()
  vectorizerProc?.kill()

  // 延迟 300ms 确保 TCP 包发出后再退出
  setTimeout(() => { app.exit(0) }, 300)
})
```

### 4.3 端口冲突处理

启动时检查端口是否已被占用：

```javascript
async function isPortInUse(port) {
  return new Promise((resolve) => {
    const server = require('net').createServer()
    server.once('error', () => resolve(true))
    server.once('listening', () => { server.close(); resolve(false) })
    server.listen(port, '127.0.0.1')
  })
}
```

若端口已被占用且 `/healthz` 返回的 `service` 字段匹配，则复用已有进程（不重复启动）。

## 5. 环境变量

桌面端打包后不使用外部环境变量管理，以下值均为后端内部默认值，用户无需设置。

| 变量 | 值 | 说明 |
|------|-----|------|
| `AUTO_START_COMFYUI` | `1` | txt2img-backend 内部自动启动 ComfyUI |
| `COMFYUI_NETWORK_MODE` | `offline` | 默认离线，阻止 ComfyUI-Manager 网络检查 |
| `VECTORIZER_BACKEND_URL` | `http://127.0.0.1:8000/api/v1/vectorize` | Electron 负责保证后端已启动 |
| `TXT2IMG_BACKEND_URL` | `http://127.0.0.1:9001/api/v1/txt2img` | Electron 负责保证后端已启动 |
| `ART_TEXT_OUTPUT_ROOT` | 开发: 项目根 `outputs/`，打包: `文档/Gen2Vec-ArtFont-App/outputs/` | 可通过环境变量覆盖产物输出目录 |

> **注意**：`/healthz` 返回 200 仅表示 FastAPI 进程已启动，此时 ComfyUI 可能还在后台加载模型。如果用户在 ComfyUI 就绪前发起生成请求，可能会拿到降级的 Pillow stub（`engine: "local-studio"`）。稍后重试即可——ComfyUI 就绪后（通常 30s 内）后续请求会正常使用 GPU 推理。

## 6. 关键路径解析

### 6.1 electron-builder 配置

`apps/desktop/package.json` → `"build"` 字段：

```jsonc
{
  "build": {
    "appId": "com.arttext.generator",
    "productName": "矢量艺术字生成器",
    "directories": { "output": "release" },
    "files": ["dist/**/*", "electron/**/*"],
    "extraResources": [
      { "from": "../../services/txt2img-api/dist/txt2img-backend.exe", "to": "backend/txt2img-backend.exe" },
      { "from": "../../services/txt2img-api/dist/ComfyUI-GGUF.zip",     "to": "backend/ComfyUI-GGUF.zip" },
      { "from": "../../scripts/download-comfyui-engine.ps1",            "to": "backend/download-comfyui-engine.ps1" },
      { "from": "../../scripts/download-models.ps1", "to": "backend/download-models.ps1" },
      { "from": "../../services/txt2img-api/dist/README.md", "to": "backend/README.md" },
      { "from": "../../services/vectorizer-api/dist/vectorizer-backend.exe", "to": "backend/vectorizer-backend.exe" },
      { "from": "../../services/vectorizer-api/dist/models", "to": "backend/models" },
      { "from": "../../apps/cli/dist/gen2vec_cli.exe", "to": "../gen2vec_cli.exe" }
    ],
    "win": { "target": "nsis" },
    "nsis": {
      "oneClick": false,
      "allowToChangeInstallationDirectory": true
    }
  }
}
```

### 6.2 开发 vs 生产路径

| 场景 | 后端 EXE 位置 | 判断方式 |
|------|--------------|----------|
| 开发 (`npm run electron:dev`) | 手动启动 `uv run txt2img-api` | 直接连 localhost，由开发者在终端手动管理 |
| 打包后 (.exe) | `process.resourcesPath/backend/txt2img-backend.exe` | `app.isPackaged` 为 true |

```javascript
function getBackendDir() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'backend')
  }
  // 开发模式: 不启动后端, 假设开发者手动启动
  return null
}
```

### 6.3 txt2img-backend 内部路径

`_get_executable_dir()` 在 PyInstaller frozen 模式下返回 `sys.executable` 的父目录，即 `resources/backend/`。ComfyUI portable 同级放置：

```
resources/backend/
├── txt2img-backend.exe          ← sys.executable
├── 
└── ComfyUI_windows_portable_nvidia/
    └── ComfyUI_windows_portable/
        └── python_embeded/python.exe
```

`_build_comfyui_command()` 构造的命令行：

```
resources\backend\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\python_embeded\python.exe
  -s ComfyUI/main.py
  --windows-standalone-build
  --disable-api-nodes
  --fast fp16_accumulation
```

`cwd` 设为 `ComfyUI_windows_portable/`，相对路径 `ComfyUI/main.py` 正确解析。

## 7. 模型下载体验

### 7.1 UI 流程

```
首次启动 → 检测模型缺失 → 弹窗
  ┌─────────────────────────────────────────┐
  │   🔧 首次运行需要下载 AI 模型             │
  │                                          │
  │   需要下载 10 个模型文件 (约 58 GB)        │
  │   请确保网络畅通，可能需要较长时间          │
  │                                          │
  │   进度: ████████░░░░░░░░  5/10           │
  │   当前: z_image_turbo_bf16.safetensors    │
  │   速度: 12.3 MB/s  剩余: ~45 分钟         │
  │                                          │
  │           [开始下载]  [跳过]              │
  └─────────────────────────────────────────┘
```

### 7.2 download-models.ps1 的 Electron 模式

`-Electron` 参数使脚本输出结构化文本，每行以 `MODELDL:` 开头：

```
MODELDL:TOTAL|10
MODELDL:ENGINE_OK
MODELDL:START|z_image_turbo_bf16|1/10|12.3 GB
MODELDL:DONE|z_image_turbo_bf16
MODELDL:SKIP|flux1-schnell
MODELDL:START|qwen_image_2512|2/10|9.0 GB
MODELDL:ERROR|qwen_image_2512|timeout
MODELDL:COMPLETE|8|2|0
MODELDL:READY
```

| 消息类型 | 格式 | 说明 |
|----------|------|------|
| `TOTAL` | `TOTAL\|N` | 模型文件总数 |
| `ENGINE_OK` | — | 引擎目录已就绪 |
| `START` | `START\|文件名\|序号/总数\|大小` | 开始下载某个文件 |
| `DONE` | `DONE\|文件名` | 下载成功（或已存在跳过） |
| `SKIP` | `SKIP\|文件名` | 文件已存在，跳过 |
| `ERROR` | `ERROR\|文件名\|原因` | 下载失败 |
| `COMPLETE` | `COMPLETE\|成功数\|跳过数\|失败数` | 全部完成 |
| `READY` | — | 模型目录就绪，可开始使用 |

`main.cjs` 逐行解析 `stdout`，提取 `MODELDL:` 行更新进度条。`TOTAL` 到达前不显示文件总数，`COMPLETE` 到达后汇总结果。

### 7.3 断点续传与重试

- `download-models.ps1` 内置逻辑：文件已存在且大小匹配 → 跳过
- 最多重试 3 次，每次失败后等待递增时间
- 部分失败不阻塞应用启动，已下载的模型可用

## 8. 启动性能优化

### 8.1 冷启动时间线

| 阶段 | 操作 | 预计耗时 |
|------|------|----------|
| 解压 ComfyUI | `` 自解压 2GB | ~30s（仅首次） |
| 下载 ComfyUI 引擎 | download-comfyui-engine.ps1 下载并解压 ~2 GB | ~5-15min（仅首次，取决于网速） |
| 启动 txt2img-backend | PyInstaller 解压 + Python 初始化 | ~3s |
| 启动 vectorizer-backend | PyInstaller 解压 + Python 初始化 | ~2s |
| ComfyUI 冷启动 | python_embeded + custom nodes 加载 | ~20-30s (network_mode=offline) |

### 8.2 已实施的优化

- **ComfyUI-Manager 离线模式**：启动前自动写入 `network_mode = offline`，跳过 GitHub 缓存拉取和 ComfyRegistry 同步，节省 10-15s
- **`--disable-api-nodes`**：阻止前端与互联网通信
- **直接构造命令行**：跳过 `.bat` 启动器，减少一层 shell 开销

## 9. 错误处理与降级

| 场景 | 处理方式 |
|------|----------|
| 端口 9001/8000 被占用 | 检查 `/healthz` 是否返回正确 service 名，是则复用 |
| ComfyUI 解压失败 | 弹窗提示重新安装，退出应用 |
| 模型全部缺失 + 用户跳过下载 | 文生图功能不可用，提示用户稍后通过菜单下载 |
| 模型部分缺失 | 缺少模型对应的工作流不可用，降级链自动跳过 |
| txt2img-backend 启动超时 | 弹窗提示检查环境，用户可重试 |
| ComfyUI 启动超时 (120s) | 生成请求降级到 Pillow stub |
| 生成请求超时 (300s) | 桌面端提示超时，用户可重试 |

## 10. 打包命令

```powershell
# 1. 构建后端 EXE（使用 PyInstaller，具体命令见各服务目录脚本）
#    - services/txt2img-api/ → dist/txt2img-backend.exe
#    - services/vectorizer-api/ → dist/vectorizer-backend.exe + dist/models/

# 2. 构建 CLI EXE
cd apps/cli
npm install
npm run build
# 产物: apps/cli/dist/gen2vec_cli.exe

# 3. 确认打包前置文件清单
#    必须存在:
#      services/txt2img-api/dist/txt2img-backend.exe
#      services/txt2img-api/dist/ComfyUI-GGUF.zip
#      services/txt2img-api/dist/README.md
#      services/vectorizer-api/dist/vectorizer-backend.exe
#      services/vectorizer-api/dist/models/rembg/isnet-general-use.onnx
#      apps/cli/dist/gen2vec_cli.exe
#      scripts/download-comfyui-engine.ps1
#      scripts/download-models.ps1
#    不应存在（已废弃）:
#      services/txt2img-api/dist/ComfyUI-Engine.exe

# 4. 构建 Electron 安装包
cd apps/desktop
npm install
npm run electron:build
# 产物: apps/desktop/release/矢量艺术字生成器 Setup x.x.x.exe

## 11. 待实现清单

以下均为可选增强项，核心打包流程已全部实现：

- [x] ComfyUI 引擎在线下载（`download-comfyui-engine.ps1` — 首次运行时自动拉取官方 portable + GGUF）
- [x] AI 模型在线下载（`download-models.ps1` — 首次运行时从 HuggingFace 镜像拉取）
- [x] 启动画面进度展示（splash window 实时显示下载/解压/启动进度）
- [x] ComfyUI-Manager 离线模式（启动前自动写入 `network_mode = offline`）
- [ ] "稍后下载模型"菜单入口（IPC 接口 `art-text/download-models` 已就绪，缺 UI 菜单项）
- [ ] 主窗口内嵌模型下载进度组件（配合菜单入口使用）
