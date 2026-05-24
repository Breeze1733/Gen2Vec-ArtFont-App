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
Development-Training/
├── apps/
│   └── desktop/                    # Electron + Vue 3 桌面端
│       ├── electron/main.cjs       # Electron 主进程（IPC、HTTP 请求后端）
│       ├── electron/preload.cjs    # contextBridge 安全 IPC
│       └── src/renderer/           # Vue 3 SPA（Vite 构建）
│           ├── App.vue             # 根组件：状态管理、历史记录
│           ├── api.js              # API 层：mock SVG 生成 + 后端调用
│           ├── components/         # ModeSwitcher, GenerationForm, ResultPanel, HistoryPanel
│           └── styles/global.css   # 单文件 CSS，无框架
├── services/
│   ├── vectorizer-api/             # FastAPI 服务：位图 → SVG 矢量化（FR3 引擎）
│   │   └── app/
│   │       ├── main.py             # 路由：/healthz, POST /api/v1/vectorize, POST /api/v1/generate
│   │       ├── models.py           # Pydantic 请求/响应模型
│   │       └── vectorizer.py       # 核心引擎：OpenCV 量化 → vtracer 追踪 → svgwrite 组装
│   └── txt2img-api/                  # FastAPI 服务：文本 → 位图生成
│       └── src/app/
│           ├── main.py             # 路由：/healthz, POST /api/v1/txt2img（自动启动 ComfyUI）
│           ├── models.py           # Pydantic 模型
│           └── generator.py        # 生成器：ComfyUI HTTP 客户端 + 本地 stub 降级
├── workflows/                      # ComfyUI 工作流 JSON
├── packages/                       # （预留）共享 SDK/类型/工具
├── docs/                           # （预留）文档
└── scripts/                        # （预留）开发/构建/发布脚本
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
# 或：uv run uvicorn app.main:app --host 0.0.0.0 --port 9001 --app-dir src
```

设置 `AUTO_START_COMFYUI=0` 可跳过自动启动 ComfyUI。ComfyUI 不可达时自动降级为本地 Pillow stub。

### 桌面端

```powershell
cd apps/desktop
npm install
npm run electron:dev    # Vite 开发 + Electron
npm run electron:build  # 生产构建（electron-builder, NSIS 安装包）
```

后端地址默认 `http://127.0.0.1:8000/api/v1`，可通过 `ART_TEXT_BACKEND_URL` 环境变量覆盖。

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
| POST | `/api/v1/generate` | vectorizer-api | 🔧 预留（501） |
| POST | `/api/v1/txt2img` | txt2img-api | ✅ 文本→位图 |
