# CLAUDE.md

本文档为 Claude Code 提供本仓库的指引。

## 沟通约定

- 与用户沟通使用**中文**
- 文档描述、注释等使用**中文**
- 代码中的标识符、API 名、专有名词等使用标准**英文**

## 项目概览

矢量艺术字生成器 — 本地优先的 AI 艺术字工具。根据提示词生成位图艺术字（通过 ComfyUI 或本地降级方案），再使用计算机视觉技术将位图矢量化输出 SVG。

支持三种模式：单条提示词、批量提示词、图片矢量化。

## 仓库结构

```
Gen2Vec-ArtFont-App/
├── apps/
│   ├── desktop/                        # Electron + Vue 3 桌面端
│   │   ├── electron/
│   │   │   ├── main.cjs                # 主进程：IPC 处理、HTTP 代理到后端
│   │   │   └── preload.cjs             # contextBridge 安全 IPC（window.artTextApp）
│   │   ├── src/renderer/
│   │   │   ├── App.vue                 # 根组件：GPU 检测、状态管理、历史记录
│   │   │   ├── api.js                  # API 层：后端 HTTP 调用
│   │   │   ├── main.js                 # Vue 入口
│   │   │   ├── components/
│   │   │   │   ├── ModeSwitcher.vue    # 模式切换（单条/批量/矢量化）
│   │   │   │   ├── GenerationForm.vue  # 输入表单
│   │   │   │   ├── VectorParams.vue    # 矢量化参数面板
│   │   │   │   ├── ResultPanel.vue     # 结果展示
│   │   │   │   └── HistoryPanel.vue    # 历史任务
│   │   │   └── styles/global.css       # 单文件 CSS
│   │   ├── package.json
│   │   └── vite.config.js
│   └── cli/                            # Node.js CLI 工具（无需 Electron）
│       ├── bin/gen2vec.mjs             # CLI 入口
│       ├── src/
│       │   ├── api.mjs                 # 后端 API 调用层
│       │   ├── commands/
│       │   │   ├── generate.mjs        # generate 命令
│       │   │   ├── vectorize.mjs       # vectorize 命令
│       │   │   └── pipeline.mjs        # pipeline 命令
│       │   └── utils/file.mjs          # 文件读写工具
│       └── README.md
├── services/
│   ├── vectorizer-api/                 # FastAPI：位图 → SVG 矢量化
│   │   ├── app/
│   │   │   ├── main.py                 # 路由：/healthz, POST /api/v1/vectorize
│   │   │   ├── models.py               # Pydantic 模型（VectorConfig, VectorizeRequest/Response）
│   │   │   ├── image_processing.py     # 图像预处理：rembg 抠图、去噪、裁剪、量化
│   │   │   ├── vectorization.py        # 矢量化核心：vtracer 追踪 + 质量评估
│   │   │   └── app.py                  # 入口
│   │   ├── models/rembg/               # 离线 rembg ONNX 模型
│   │   └── requirements.txt
│   └── txt2img-api/                    # FastAPI：文本 → 位图生成
│       ├── app/
│       │   ├── main.py                 # 路由：/healthz, POST /api/v1/txt2img
│       │   ├── models.py               # Pydantic 模型（GenerationRequest/Response）
│       │   └── generator.py            # ComfyUI 客户端 + Pillow 本地 stub 降级
│       ├── scripts/
│       │   ├── run_comfyui.py          # ComfyUI 启动脚本
│       │   └── poll_comfy.py           # ComfyUI 状态轮询
│       ├── tests/
│       │   ├── test_api.py             # API 测试
│       │   └── test_generator.py       # 生成器测试
│       ├── workflows/                  # ComfyUI 工作流 JSON（独立于根目录 workflows）
│       └── pyproject.toml
├── workflows/                          # （预留）根目录工作流模板
├── packages/                           # （预留）共享 SDK/类型/工具
├── docs/
│   └── electron-ipc.md                 # Electron IPC API 文档
├── scripts/                            # （预留）开发/构建/发布脚本
├── README.md
└── CLAUDE.md
```

## 关键架构决策

- **FR3 矢量化引擎**（`vectorizer.py`）：通过 k-means 进行颜色量化，逐层用 vtracer 追踪路径，用 svgwrite 组装分层 SVG，用 cairosvg 渲染 PNG 预览，输出轮廓偏差质量指标。
- **ComfyUI 集成**：txt2img-api 会自动启动捆绑的 ComfyUI 便携实例（如果存在），ComfyUI 不可达时降级为本地 Pillow stub。
- **桌面端 ↔ 后端 IPC**：Electron 主进程代理 HTTP 请求到 FastAPI 后端。渲染层仅通过 `window.artTextApp`（contextBridge）通信，生产环境无 CORS 问题。
- **前端无框架**：仅 global.css，未使用 Tailwind 等 CSS 框架。
- **独立依赖管理**：每个服务/应用独立管理自己的依赖，无 monorepo workspace 工具。

## 启动服务

### Vectorizer API（端口 8000）

```powershell
cd services/vectorizer-api
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

依赖：OpenCV, scikit-image, vtracer, cairosvg, svgwrite

### txt2img-api（端口 9001）

```powershell
cd services/txt2img-api
uv sync
uv run txt2img-api
# 或：uv run uvicorn app.main:app --host 0.0.0.0 --port 9001
```

设置 `AUTO_START_COMFYUI=0` 可跳过自动启动 ComfyUI。ComfyUI 不可达时自动降级为本地 Pillow stub。

### 桌面端

```powershell
cd apps/desktop
npm install
npm run electron:dev    # Vite 开发 + Electron
npm run electron:build  # 生产构建（electron-builder, NSIS 安装包）
```

矢量化地址默认 `http://127.0.0.1:8000/api/v1/vectorize`，可通过 `VECTORIZER_BACKEND_URL` 环境变量覆盖。
文生图地址默认 `http://127.0.0.1:9001/api/v1/txt2img`，可通过 `TXT2IMG_BACKEND_URL` 环境变量覆盖。

### CLI 工具

```powershell
# 直接运行（无需安装）
node apps/cli/bin/gen2vec.mjs --help

# 常用命令
node apps/cli/bin/gen2vec.mjs generate --text "你好" --prompt "霓虹风格"
node apps/cli/bin/gen2vec.mjs vectorize --input artwork.png --preset detailed
node apps/cli/bin/gen2vec.mjs pipeline --text "Hello" --vector-preset ultra
node apps/cli/bin/gen2vec.mjs health
```

CLI 直接调用后端 HTTP 接口，无需 Electron 环境。详见 [apps/cli/README.md](apps/cli/README.md)。

## 测试

```powershell
# txt2img-api 测试
cd services/txt2img-api
uv run pytest
```

使用 FastAPI TestClient（见 [tests/test_api.py](services/txt2img-api/tests/test_api.py)）。

vectorizer-api 和 desktop 目前尚无测试。

## API 端点

| 方法 | 路径 | 服务 | 状态 |
|--------|------|---------|--------|
| GET | `/healthz` | vectorizer-api, txt2img-api | ✅ |
| POST | `/api/v1/vectorize` | vectorizer-api | ✅ 位图→SVG |
| POST | `/api/v1/txt2img` | txt2img-api | ✅ 文本→位图 |

## 环境变量

| 变量 | 服务 | 说明 | 默认值 |
|------|------|------|--------|
| `VECTORIZER_BACKEND_URL` | desktop, cli | 矢量化接口完整 URL | `http://127.0.0.1:8000/api/v1/vectorize` |
| `TXT2IMG_BACKEND_URL` | desktop, cli | 文生图接口完整 URL | `http://127.0.0.1:9001/api/v1/txt2img` |
| `TXT2IMG_WORKFLOW` | cli | ComfyUI 工作流名称 | `test_z_image_turbo` |
| `AUTO_START_COMFYUI` | txt2img-api | 是否自动启动 ComfyUI | `1` |
| `WORKFLOW_PATH` | txt2img-api | 自定义工作流 JSON 路径 | — |
| `COMFYUI_HOST` | txt2img-api | ComfyUI 地址 | `http://127.0.0.1:8188` |
| `COMFYUI_POLL_TIMEOUT` | txt2img-api | ComfyUI 轮询超时（秒） | `500` |

## 矢量化预设

| 预设 | color_precision | filter_speckle | corner_threshold | length_threshold | layer_difference | scale |
|------|-----------------|----------------|------------------|------------------|------------------|-------|
| clean | 3 | 15 | 60 | 12 | 20 | 2 |
| balanced | 5 | 6 | 45 | 5 | 10 | 2 |
| detailed | 6 | 2 | 30 | 3 | 4 | 3 |
| ultra | 8 | 1 | 20 | 2 | 2 | 3 |
