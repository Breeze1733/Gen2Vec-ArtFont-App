<!--
  项目徽章区域 — 后续接入 CI/CD 后可替换为实际状态
-->
<!-- [![Build](https://img.shields.io/github/actions/workflow/status/...)](#) -->
<!-- [![Version](https://img.shields.io/github/v/release/...)](#) -->
<!-- [![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) -->

# Gen2Vec ArtFont

> 矢量艺术字生成器 — 本地优先的 AI 艺术字工具。输入文字与风格描述，自动生成位图艺术字并通过计算机视觉技术转换为高质量 SVG 矢量图。

[特性](#特性) •
[快速开始](#快速开始) •
[使用指南](#使用指南) •
[API 参考](#api-参考) •
[配置说明](#配置说明) •
[开发指南](#开发指南) •
[许可证](#许可证)

---

## 目录

- [背景](#背景)
- [特性](#特性)
- [架构](#架构)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
  - [环境要求](#环境要求)
  - [安装与启动](#安装与启动)
- [使用指南](#使用指南)
  - [桌面端](#桌面端)
  - [CLI 命令行](#cli-命令行)
- [API 参考](#api-参考)
  - [端点列表](#端点列表)
  - [请求/响应示例](#请求响应示例)
- [配置说明](#配置说明)
  - [环境变量](#环境变量)
  - [矢量化预设](#矢量化预设)
  - [工作流降级链](#工作流降级链)
- [输出规范](#输出规范)
- [开发指南](#开发指南)
  - [本地开发](#本地开发)
  - [测试](#测试)
  - [构建与打包](#构建与打包)
- [技术栈](#技术栈)
- [许可证](#许可证)

---

## 背景

在品牌设计、海报制作、UI 素材等场景中，经常需要将文字渲染为特定风格的艺术字，并以矢量格式交付（可无损缩放、便于二次编辑）。传统做法依赖设计师手工绘制，耗时且成本高。

Gen2Vec ArtFont 利用开源文生图模型（Flux、Z-Image、Qwen-Image）自动生成艺术字位图，再通过 rembg 背景移除 + vtracer 路径追踪的流水线将其转换为分层 SVG。整个过程在本地完成，无需联网，保护数据隐私。

### 适用场景

- **品牌设计**：快速生成 Logo 风格的艺术字 SVG
- **海报制作**：批量生成活动标题的艺术字素材
- **UI 素材**：为应用界面生成风格统一的图标文字
- **自动化验收**：通过 CLI 批量跑测试集，评估模型效果

---

## 特性

- **🎨 文生图** — 对接 ComfyUI，支持 Flux Schnell、Z-Image Turbo、Qwen-Image 等多模型工作流；自动检测中英文内容并构建最优提示词模板
- **✂️ 智能矢量化** — rembg 背景移除 → 双边滤波去噪 → k-means 颜色量化 → vtracer 分层路径追踪 → SVG 组装
- **📊 质量评估** — SVG 回渲染与原始透明图逐像素 RMSE 对比，输出保真度分数
- **🖥️ 多端覆盖** — Electron + Vue 3 桌面端（GUI）与 Node.js CLI（命令行）共享同一套后端服务
- **🔒 本地优先** — 所有 AI 推理在本地运行；ComfyUI 不可用时自动降级为 Pillow 本地轻量引擎
- **📦 批量处理** — 支持 TXT / CSV / JSON 批量输入，逐条容错执行，自动生成汇总 CSV
- **🔄 弹性降级** — 多模型工作流降级链，单个模型失败自动切换下一个，确保任务不中断

---

## 架构

```
┌──────────────────────────────────────────────────┐
│                   界面层 (UI Layer)                │
│  ┌──────────────────┐  ┌───────────────────────┐ │
│  │  Electron + Vue 3 │  │  Node.js CLI (.mjs)   │ │
│  │  (桌面端 GUI)     │  │  (命令行 / 自动化)    │ │
│  └────────┬─────────┘  └───────────┬───────────┘ │
│           │        HTTP            │              │
└───────────┼────────────────────────┼──────────────┘
            │                        │
┌───────────┼────────────────────────┼──────────────┐
│           ▼                        ▼              │
│                 服务层 (Service Layer)             │
│  ┌──────────────────┐  ┌───────────────────────┐ │
│  │  txt2img-api      │  │  vectorizer-api       │ │
│  │  :9001            │  │  :8000                │ │
│  │  文本 → 位图      │  │  位图 → SVG           │ │
│  └────────┬─────────┘  └───────────────────────┘ │
│           │                                       │
└───────────┼───────────────────────────────────────┘
            │
    ┌───────▼────────┐
    │    ComfyUI     │  ← 可选组件，自动启动 / 降级
    │    :8188        │
    │ Flux / Z-Image │
    │ / Qwen-Image   │
    └────────────────┘
```

### 数据流

```
用户输入 (文字 + 提示词)
    │
    ▼
txt2img-api ──→ ComfyUI (或本地 stub)
    │
    ▼
original.png ──→ vectorizer-api
    │
    ├── rembg 背景移除
    ├── 双边滤波去噪
    ├── k-means 颜色量化
    ├── vtracer 分层追踪
    └── SVG 组装 + 质量评估
    │
    ▼
result.svg + preview.png + metadata.json
```

---

## 项目结构

```
Gen2Vec-ArtFont-App/
│
├── apps/                             # 客户端应用
│   ├── desktop/                      # Electron + Vue 3 桌面端
│   │   ├── electron/
│   │   │   ├── main.cjs              # 主进程：后端生命周期、IPC 代理、启动画面
│   │   │   └── preload.cjs           # contextBridge 安全 IPC 桥接
│   │   └── src/renderer/
│   │       ├── App.vue               # 根组件：GPU 检测、模式切换、任务编排
│   │       ├── api.js                # API 层：直连 HTTP + Electron IPC 兜底
│   │       ├── components/           # UI 组件
│   │       │   ├── ModeSwitcher.vue  #   模式切换（单条 / 批量 / 矢量化）
│   │       │   ├── GenerationForm.vue#   输入表单
│   │       │   ├── VectorParams.vue  #   矢量化参数面板
│   │       │   ├── ResultPanel.vue   #   结果展示
│   │       │   └── HistoryPanel.vue  #   历史任务
│   │       └── styles/global.css     # 全局样式
│   │
│   └── cli/                          # Node.js CLI 工具
│       ├── bin/gen2vec.mjs           # CLI 入口
│       └── src/
│           ├── api.mjs               # 后端 HTTP 调用层
│           ├── commands/             # 命令实现
│           │   ├── generate.mjs      #   generate — 生成位图
│           │   ├── vectorize.mjs     #   vectorize — 位图矢量化
│           │   ├── pipeline.mjs      #   pipeline — 完整流水线
│           │   ├── batch.mjs         #   batch — 批量流水线
│           │   └── env.mjs           #   env — 环境信息
│           └── utils/                # 文件读写、输出目录管理
│
├── services/                         # 后端服务
│   ├── txt2img-api/                  # 文生图服务（Python / FastAPI）
│   │   ├── app/
│   │   │   ├── main.py               # 路由 + ComfyUI 生命周期管理
│   │   │   ├── generator.py          # ComfyUI 客户端 + 提示词模板引擎 + 降级 stub
│   │   │   └── models.py             # Pydantic 请求 / 响应模型
│   │   ├── workflows/                # ComfyUI API 格式工作流 JSON
│   │   │   ├── flux_schnell.json
│   │   │   ├── test_z_image_turbo.json
│   │   │   └── qwen_image_2512_gguf.json
│   │   ├── scripts/                  # ComfyUI 启动 / 轮询辅助脚本
│   │   └── tests/                    # pytest 测试
│   │
│   └── vectorizer-api/               # 矢量化服务（Python / FastAPI）
│       ├── app/
│       │   ├── main.py               # 路由 + 图像源解析
│       │   ├── image_processing.py   # rembg 抠图、去噪、裁剪、颜色量化
│       │   ├── vectorization.py      # vtracer 追踪 + 质量评估
│       │   └── models.py             # Pydantic 模型 + 预设参数
│       └── models/rembg/             # 离线背景移除 ONNX 模型
│
├── docs/                             # 项目文档
│   ├── 基于开源文生图模型的矢量艺术字生成应用.md  # 需求文档
│   ├── electron-packaging.md                       # 打包说明
│   └── hardware-environment.md                     # 测试机硬件报告
│
├── testdata/                         # 测试数据
│   └── art_text_prompts_150.txt      # 150 条批量测试样例
│
├── workflows/                        # （预留）根目录工作流模板
├── packages/                         # （预留）共享 SDK / 类型 / 工具
├── scripts/                          # （预留）开发 / 构建 / 发布脚本
├── outputs/                          # 运行时产物输出目录（gitignore）
│
├── README.md                         # 本文件
├── CLAUDE.md                         # Claude Code 项目指引
├── LICENSE                           # MIT 许可证
└── .gitignore
```

---

## 快速开始

### 环境要求

| 组件 | 最低版本 | 说明 |
|------|----------|------|
| Python | ≥ 3.13 | txt2img-api 运行环境 |
| Node.js | ≥ 18 | desktop / CLI 运行环境 |
| uv | 最新版 | Python 包管理器（[安装指南](https://docs.astral.sh/uv/)） |
| npm | ≥ 9 | Node.js 包管理器 |
| GPU（推荐） | NVIDIA 独显 ≥ 8 GB 显存 | ComfyUI 推理加速；无 GPU 时自动降级 |
| 操作系统 | Windows 10 / 11 | 当前仅支持 Windows |

### 安装与启动

所有命令在**项目根目录**下执行。三个组件需分别启动：

#### 第一步：启动矢量化后端（端口 8000）

```powershell
cd services/vectorizer-api
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

#### 第二步：启动文生图后端（端口 9001）

```powershell
cd services/txt2img-api
uv sync
uv run txt2img-api
```

> 服务启动后会自动检测并启动同目录下的 ComfyUI 便携版。设置 `$env:AUTO_START_COMFYUI="0"` 可跳过自动启动，此时文生图将使用本地 Pillow 降级引擎。

#### 第三步：启动桌面端

```powershell
cd apps/desktop
npm install
npm run electron:dev
```

> 桌面端默认连接 `http://127.0.0.1:8000`（矢量化）和 `http://127.0.0.1:9001`（文生图），可通过环境变量覆盖。

#### 验证安装

```powershell
# 检查两个后端是否就绪
node apps/cli/bin/gen2vec.mjs health
```

预期输出：

```
txt2img 服务:    ✓ 正常
矢量化服务:     ✓ 正常
```

---

## 使用指南

### 桌面端

桌面端提供三种工作模式，通过顶部标签页切换：

| 模式 | 操作流程 |
|------|----------|
| **单条生成** | 输入文字 + 风格提示词 → 调整矢量化参数 → 点击生成 → 查看 SVG 结果 |
| **批量生成** | 粘贴批量文本（`文字 \| 提示词` 格式，每行一条）→ 设置参数 → 批量执行 |
| **图片矢量化** | 选择本地 PNG/JPG 文件 → 调整矢量化参数 → 直接矢量化 |

结果面板支持：
- 预览 SVG（新标签页打开）
- 下载单文件（PNG / SVG / JSON）
- 打开任务输出目录
- 历史任务恢复（从本地文件重新加载）

### CLI 命令行

CLI 定位为**自动化验收控制台**，随桌面端安装包交付。假设后端已由桌面端启动（或手动启动）。

#### 基本格式

```powershell
node apps/cli/bin/gen2vec.mjs <command> [options]
```

#### 命令列表

| 命令 | 说明 | 示例 |
|------|------|------|
| `pipeline` | 完整流水线：文本 → 位图 → SVG | `pipeline --text "你好" --prompt "霓虹风格"` |
| `generate` | 仅生成位图 | `generate --text "你好" --prompt "霓虹风格"` |
| `vectorize` | 仅矢量化已有图片 | `vectorize --input artwork.png --preset detailed` |
| `batch` | 批量流水线 | `batch --input-file testdata/art_text_prompts_150.txt` |
| `health` | 后端健康检查 | `health` |
| `env` | 显示环境信息 | `env` |
| `shutdown` | 关闭后端服务 | `shutdown` |

#### pipeline 参数

| 参数 | 简写 | 类型 | 默认值 | 说明 |
|------|:----:|------|--------|------|
| `--text` | `-t` | string | — | 艺术字文本（**必填**） |
| `--prompt` | `-p` | string | `""` | 风格提示词 |
| `--negative` | `-n` | string | `""` | 负面提示词 |
| `--resolution` | `-r` | string | `1024 x 1024` | 输出分辨率 |
| `--seed` | `-s` | number | `0` | 随机种子（0 = 随机） |
| `--vector-preset` | | string | `balanced` | 矢量化预设 |
| `--output-dir` | | string | `./outputs` | 输出根目录 |
| `--output` | `-o` | string | — | 额外输出单个 SVG 路径 |
| `--wait` | | number | `0` | 等待后端就绪的最大秒数 |

#### batch 参数

| 参数 | 说明 |
|------|------|
| `--input-file` | 批量输入文件路径（TXT / CSV / JSON） |
| `--text` | 直接传入批量文本（支持 `\n` 换行） |
| `--negative` | 全局负面提示词 |
| `--resolution` | 全局分辨率 |
| `--seed` | 全局起始种子 |
| `--seed-step` | 每条 seed 递增步长（默认 0） |
| `--vector-preset` | 矢量化预设 |
| `--no-vectorize` | 仅生成 original.png，跳过矢量化 |
| `--output-dir` | 输出根目录 |

#### 批量输入格式

TXT（与桌面端批量输入框一致）：

```text
文本 | 风格提示词
七里香 | 清新国风、墨绿色金边
夏日冰饮 50% | 清爽蓝白配色、冰块纹理
```

CSV：

```csv
text,prompt,seed
七里香,清新国风,42
Hello,neon style,100
```

JSON：

```json
[
  { "text": "七里香", "prompt": "清新国风" },
  { "text": "Hello", "prompt": "neon style" }
]
```

---

## API 参考

### 端点列表

| 方法 | 路径 | 服务 | 说明 |
|------|------|------|------|
| `GET` | `/healthz` | txt2img-api, vectorizer-api | 健康检查 |
| `POST` | `/api/v1/txt2img` | txt2img-api | 文本生成位图 |
| `POST` | `/api/v1/vectorize` | vectorizer-api | 位图矢量化 |
| `POST` | `/shutdown` | txt2img-api, vectorizer-api | 优雅关闭服务 |

### 请求/响应示例

#### POST /api/v1/txt2img

**请求：**

```json
{
  "text": "七里香",
  "prompt": "清新国风、墨绿色金边",
  "negative_prompt": "",
  "resolution": "1024 x 1024",
  "seed": 42,
  "style": "default",
  "format": "PNG",
  "workflow": ""
}
```

**响应：**

```json
{
  "image_base64": "data:image/png;base64,iVBORw0KGgo...",
  "image_name": "清新国风-墨绿色金边.png",
  "metadata": {
    "engine": "comfyui",
    "prompt": "清新国风、墨绿色金边",
    "seed": 42,
    "canvas": { "width": 1024, "height": 1024 },
    "fallback_tier": 0,
    "workflow_used": "qwen_image_2512_gguf",
    "generated_at": "2026-06-07T06:30:00Z"
  },
  "workflow_api": { ... },
  "model_dependencies": {
    "checkpoints": [],
    "unets": ["qwen_image_2512-Q4_K_M.gguf"],
    "clip": ["qwen_2.5_vl_7b_fp8_scaled.safetensors"],
    "vae": ["qwen_image_vae.safetensors"],
    "loras": [],
    "workflow_name": "qwen_image_2512_gguf"
  }
}
```

#### POST /api/v1/vectorize

**请求：**

```json
{
  "source_type": "generated",
  "text": "七里香",
  "prompt": "清新国风",
  "resolution": "1024 x 1024",
  "seed": 42,
  "vector": {
    "preset": "detailed",
    "color_precision": 6,
    "filter_speckle": 2,
    "corner_threshold": 30,
    "length_threshold": 3,
    "layer_difference": 4,
    "scale": 3
  },
  "generated_image": {
    "file_path": "outputs/task_xxx/original.png"
  }
}
```

**响应：**

```json
{
  "transparent_png": "data:image/png;base64,...",
  "preview_png": "data:image/png;base64,...",
  "png": "data:image/png;base64,...",
  "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" ...>...</svg>",
  "metadata": {
    "engine": "vectorizer-api-split-pipeline",
    "params": {
      "preset": "detailed",
      "color_precision": 6,
      "filter_speckle": 2,
      "corner_threshold": 30,
      "length_threshold": 3,
      "layer_difference": 4,
      "scale": 3
    },
    "canvas": { "width": 1024, "height": 1024 },
    "stats": {
      "elapsed_ms": 2847.32,
      "svg_size_kb": 156.4
    },
    "quality": {
      "svg_fidelity": 94.7
    }
  }
}
```

---

## 配置说明

### 环境变量

#### 客户端变量（desktop / CLI）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TXT2IMG_BACKEND_URL` | `http://127.0.0.1:9001/api/v1/txt2img` | 文生图接口完整 URL |
| `VECTORIZER_BACKEND_URL` | `http://127.0.0.1:8000/api/v1/vectorize` | 矢量化接口完整 URL |
| `TXT2IMG_WORKFLOW` | `""` | ComfyUI 工作流名称（空 = 使用降级链） |
| `ART_TEXT_OUTPUT_ROOT` | `./outputs` | 产物输出根目录 |

#### 服务端变量（txt2img-api）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AUTO_START_COMFYUI` | `1` | 是否在启动时自动拉起 ComfyUI |
| `COMFYUI_HOST` | `http://127.0.0.1:8188` | ComfyUI 服务地址 |
| `COMFYUI_POLL_TIMEOUT` | `500` | ComfyUI 任务轮询超时（秒） |
| `COMFYUI_POLL_INTERVAL` | `1.0` | ComfyUI 轮询间隔（秒） |
| `WORKFLOW_PATH` | — | 自定义工作流 JSON 路径（覆盖默认） |
| `COMFYUI_LAUNCHER_BAT` | — | 自定义 ComfyUI 启动脚本（escape hatch） |
| `COMFYUI_NETWORK_MODE` | `offline` | ComfyUI-Manager 网络模式 |

### 矢量化预设

| 预设 | 颜色精度 | 斑点过滤 | 拐角阈值 | 长度阈值 | 图层差异 | 缩放 | 适用场景 |
|------|:--------:|:--------:|:--------:|:--------:|:--------:|:----:|----------|
| `clean` | 2 | 48 | 120 | 30 | 38 | 2× | 简洁 SVG，路径少，文件小 |
| `balanced` | 4 | 18 | 70 | 12 | 20 | 2× | **默认推荐**，细节与体积均衡 |
| `detailed` | 6 | 2 | 30 | 3 | 4 | 3× | 高精度，保留更多颜色层次 |
| `ultra` | 8 | 1 | 20 | 2 | 2 | 3× | 极致细节，适合高质量印刷 |

### 工作流降级链

txt2img-api 根据输入文本的语种自动选择最优模型，失败时自动切换：

| 文本类型 | 优先级 1 | 优先级 2 | 兜底 |
|----------|----------|----------|------|
| 中文为主 | Qwen-Image | Z-Image Turbo | Pillow 本地 stub |
| 英文 / 其他 | Flux Schnell | Z-Image Turbo | Pillow 本地 stub |

> 通过请求参数 `workflow` 可显式指定工作流名称，此时跳过降级链，仅尝试指定工作流。

---

## 输出规范

每次生成在 `outputs/` 下创建独立任务目录，命名规则为 `task_{YYYYMMDD_HHMMSS_mmm}`。

### 目录结构

```text
outputs/
├── task_20260607_143052_123/
│   ├── original.png                # 文生图原始位图
│   ├── transparent.png             # 去背景透明 PNG
│   ├── result.svg                  # 最终矢量 SVG（格式化，缩进美化）
│   ├── preview.png                 # SVG 回渲染预览图（cairosvg）
│   ├── metadata.json               # 结构化元数据
│   ├── run.log                     # 运行日志（key=value 格式）
│   └── workflows/                  # ComfyUI 工作流快照（文生图任务）
│       ├── workflow_api.json       #   API 格式工作流
│       ├── nodes.md                #   节点说明
│       └── model_dependencies.json #   模型依赖清单
│
├── task_20260607_143105_456/
│   └── ...
│
└── batch_summary.csv               # 批量模式汇总（如有）
```

### metadata.json 结构

```json
{
  "schema_version": 1,
  "task_id": "1717766400000",
  "task_name": "task_20260607_143052_123",
  "mode": "single",
  "engine": "vectorizer-api-split-pipeline",
  "generation": {
    "text": "七里香",
    "prompt": "清新国风、墨绿色金边",
    "seed": 42,
    "resolution": "1024x1024",
    "duration_ms": 15234
  },
  "params": {
    "preset": "detailed",
    "color_precision": 6,
    "filter_speckle": 2,
    "corner_threshold": 30,
    "length_threshold": 3,
    "layer_difference": 4,
    "scale": 3
  },
  "canvas": { "width": 1024, "height": 1024 },
  "stats": {
    "elapsed_ms": 2847.32,
    "svg_size_kb": 156.4
  },
  "quality": {
    "svg_fidelity": 94.7
  },
  "paths": {
    "original": "original.png",
    "transparent": "transparent.png",
    "svg": "result.svg",
    "preview": "preview.png",
    "metadata": "metadata.json",
    "log": "run.log"
  }
}
```

---

## 开发指南

### 本地开发

```powershell
# 1. 克隆仓库
git clone <repo-url>
cd Gen2Vec-ArtFont-App

# 2. 安装 Python 依赖
cd services/txt2img-api && uv sync
cd ../vectorizer-api && pip install -r requirements.txt

# 3. 安装 Node.js 依赖
cd ../../apps/desktop && npm install

# 4. 启动后端（两个终端）
# 终端 A：
cd services/vectorizer-api
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 终端 B：
cd services/txt2img-api
uv run txt2img-api

# 5. 启动桌面端开发模式
cd apps/desktop
npm run electron:dev
```

### 测试

```powershell
# txt2img-api 单元测试
cd services/txt2img-api
uv run pytest -v

# 运行单个测试文件
uv run pytest tests/test_generator.py -v
```

> vectorizer-api 和 desktop 目前尚无自动化测试（计划中）。

### 构建与打包

#### 桌面端安装包

```powershell
cd apps/desktop
npm run electron:build
```

使用 electron-builder 打包为 NSIS 安装包（`release/` 目录），自动捆绑：

| 捆绑内容 | 来源 | 打包方式 |
|----------|------|----------|
| `txt2img-backend.exe` | `services/txt2img-api/` | PyInstaller |
| `vectorizer-backend.exe` | `services/vectorizer-api/` | PyInstaller |
| `gen2vec_cli.exe` | `apps/cli/` | Node.js SEA 单文件 |
| `models/rembg/` | `services/vectorizer-api/models/` | 直接复制 |
| `download-models.ps1` | `services/txt2img-api/` | 直接复制 |

详见 [docs/electron-packaging.md](docs/electron-packaging.md)。

---

## 技术栈

| 层级 | 技术 | 版本 |
|------|------|------|
| **桌面端框架** | Electron | 42 |
| **前端框架** | Vue 3 + Vite | 3.5 / 8 |
| **CLI 运行时** | Node.js (ES Modules) | ≥ 18 |
| **后端框架** | FastAPI + Uvicorn | 0.115 |
| **文生图引擎** | ComfyUI (Flux / Z-Image / Qwen-Image) | — |
| **图像处理** | OpenCV, scikit-image, Pillow | 4.11 / 0.26 / 11.1 |
| **矢量化核心** | vtracer | 0.6 |
| **SVG 处理** | svgwrite, cairosvg | 1.4 / 2.7 |
| **背景移除** | rembg (ONNX Runtime) | 2.0 |
| **桌面打包** | electron-builder (NSIS) | 26 |
| **Python 打包** | PyInstaller | — |
| **CLI 打包** | Node.js Single Executable Apps | — |

---

## 许可证

本项目基于 [MIT License](LICENSE) 开源。

Copyright (c) 2026 Breeze