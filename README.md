<!--
  项目徽章区域。接入 CI/CD 或 Release 后，可替换为真实链接。
-->
<!-- [![Build](https://img.shields.io/github/actions/workflow/status/...)](#) -->
<!-- [![Version](https://img.shields.io/github/v/release/...)](#) -->
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](#环境要求)
[![Desktop](https://img.shields.io/badge/desktop-Electron%20%2B%20Vue-42b883.svg)](#技术栈)
[![Backend](https://img.shields.io/badge/backend-FastAPI-009688.svg)](#技术栈)

# Gen2Vec ArtFont

> 矢量艺术字生成器。本地优先的 AI 艺术字工具：输入文字与风格描述，生成艺术字位图，并通过计算机视觉流水线转换为可编辑、可缩放的 SVG 矢量图。

[背景](#背景) |
[特性](#特性) |
[架构](#架构) |
[快速开始](#快速开始) |
[使用指南](#使用指南) |
[API 参考](#api-参考) |
[配置说明](#配置说明) |
[开发指南](#开发指南) |
[许可证](#许可证)

---

## 目录

- [Gen2Vec ArtFont](#gen2vec-artfont)
  - [目录](#目录)
  - [背景](#背景)
  - [特性](#特性)
  - [架构](#架构)
    - [模块职责](#模块职责)
    - [数据流](#数据流)
  - [项目结构](#项目结构)
  - [快速开始](#快速开始)
    - [环境要求](#环境要求)
    - [安装与启动](#安装与启动)
      - [1. 启动矢量化后端（端口 8000）](#1-启动矢量化后端端口-8000)
      - [2. 启动文生图后端（端口 9001）](#2-启动文生图后端端口-9001)
      - [3. 启动桌面端](#3-启动桌面端)
    - [验证安装](#验证安装)
  - [使用指南](#使用指南)
    - [桌面端](#桌面端)
    - [CLI 命令行](#cli-命令行)
  - [API 参考](#api-参考)
    - [端点列表](#端点列表)
    - [请求与响应示例](#请求与响应示例)
      - [`GET /healthz`](#get-healthz)
      - [`POST /api/v1/txt2img`](#post-apiv1txt2img)
      - [`POST /api/v1/vectorize`](#post-apiv1vectorize)
  - [配置说明](#配置说明)
    - [环境变量](#环境变量)
    - [矢量化预设](#矢量化预设)
    - [工作流降级链](#工作流降级链)
  - [输出规范](#输出规范)
  - [开发指南](#开发指南)
    - [本地开发](#本地开发)
    - [测试](#测试)
    - [构建与打包](#构建与打包)
      - [构建后端 EXE](#构建后端-exe)
      - [构建 CLI EXE](#构建-cli-exe)
      - [构建 Electron 安装包](#构建-electron-安装包)
  - [技术栈](#技术栈)
  - [许可证](#许可证)

---

## 背景

在品牌设计、海报制作、活动物料、UI 素材等场景中，艺术字通常需要同时满足两个要求：视觉风格明确，以及后续可编辑、可缩放。传统方式依赖设计师手工绘制，效率低，批量产出和自动化验收也比较困难。

Gen2Vec ArtFont 将“文生图生成”和“位图矢量化”拆成两段本地流水线：

1. `txt2img-api` 根据文字和风格提示词调用 ComfyUI 工作流生成艺术字位图。
2. `vectorizer-api` 对位图进行背景移除、降噪、颜色量化和路径追踪，输出 SVG。
3. 桌面端和 CLI 共享同一套后端能力，既能手动操作，也能批量验收。

项目当前面向 Windows 桌面交付，支持本地模型和本地产物保存；ComfyUI 或模型不可用时，文生图链路会降级到 Pillow stub，保证系统仍能返回可诊断结果。

## 特性

- **文生图生成**：对接 ComfyUI，支持 Flux Schnell、Z-Image Turbo、Qwen-Image 等工作流。
- **智能矢量化**：rembg 离线抠图、OpenCV 边缘保留降噪、颜色量化、vtracer SVG 路径追踪。
- **工作流降级**：按文本语言自动选择工作流；失败后切换候选工作流，最终兜底到 Pillow stub。
- **多端覆盖**：Electron + Vue 3 桌面端用于日常操作，Node.js CLI 用于批量任务和自动化验收。
- **批量处理**：支持 TXT / CSV / JSON 批量输入，逐条容错执行并生成汇总 CSV。
- **标准产物**：固定输出 `original.png`、`transparent.png`、`result.svg`、`preview.png`、`metadata.json`、`run.log`。
- **本地优先**：矢量化模型使用本地 ONNX 文件；输出结果默认写入本机 `outputs/` 或用户文档目录。

## 架构

```text
┌───────────────────────────────────────────────┐
│                  Interface Layer              │
│  ┌──────────────────┐   ┌──────────────────┐  │
│  │ Electron + Vue 3 │   │ Node.js CLI       │  │
│  │ desktop GUI      │   │ automation        │  │
│  └────────┬─────────┘   └────────┬─────────┘  │
└───────────┼──────────────────────┼────────────┘
            │ HTTP / IPC           │ HTTP
            v                      v
┌───────────────────────────────────────────────┐
│                   Service Layer               │
│  ┌──────────────────┐   ┌──────────────────┐  │
│  │ txt2img-api      │   │ vectorizer-api   │  │
│  │ :9001            │   │ :8000            │  │
│  │ text -> bitmap   │   │ bitmap -> SVG    │  │
│  └────────┬─────────┘   └────────┬─────────┘  │
└───────────┼──────────────────────┼────────────┘
            │                      │
            v                      v
      ComfyUI :8188          rembg + OpenCV + vtracer
      Flux / Z-Image
      / Qwen-Image
```

### 模块职责

| 模块 | 路径 | 职责 |
| --- | --- | --- |
| 桌面端 | `apps/desktop` | UI、任务编排、历史恢复、打包后后端进程管理 |
| CLI | `apps/cli` | 命令行参数解析、后端调用、批量任务、产物写入 |
| 文生图服务 | `services/txt2img-api` | ComfyUI 工作流加载、提示词注入、生成图片、降级策略 |
| 矢量化服务 | `services/vectorizer-api` | 图片来源解析、背景移除、预处理、SVG 生成、质量指标 |
| 测试数据 | `testdata` | 批量艺术字测试样例 |
| 文档 | `docs` | 打包方案、硬件环境、需求文档等 |

### 数据流

```text
用户输入：文字 + 风格提示词 + 矢量化参数
  |
  v
txt2img-api
  |-- ComfyUI 工作流成功 -> original.png
  |-- ComfyUI 不可用 ----> Pillow stub original.png
  |
  v
vectorizer-api
  |-- rembg 背景移除
  |-- OpenCV 降噪 / 裁剪 / 抗锯齿保留
  |-- 颜色量化
  |-- vtracer 路径追踪
  |
  v
transparent.png + result.svg + preview.png + metadata.json
```

## 项目结构

```text
Gen2Vec-ArtFont-App/
├─ apps/
│  ├─ desktop/                       # Electron + Vue 3 桌面端
│  │  ├─ electron/
│  │  │  ├─ main.cjs                 # 主进程：后端生命周期、IPC、文件写入
│  │  │  ├─ preload.cjs              # contextBridge 安全桥接
│  │  │  └─ splash.html              # 打包版启动页
│  │  ├─ src/renderer/
│  │  │  ├─ App.vue                  # 主界面与任务编排
│  │  │  ├─ api.js                   # 渲染层 API 封装
│  │  │  ├─ components/              # 表单、参数、结果、历史组件
│  │  │  └─ styles/global.css        # 全局样式
│  │  ├─ package.json                # Electron / Vite / 打包配置
│  │  └─ vite.config.js
│  └─ cli/                           # Node.js CLI
│     ├─ bin/gen2vec.mjs             # CLI 入口
│     ├─ src/api.mjs                 # 后端 HTTP 调用
│     ├─ src/commands/               # generate/vectorize/pipeline/batch/env
│     ├─ src/utils/                  # 文件与输出目录工具
│     └─ scripts/                    # CLI 单文件 EXE 构建脚本
├─ services/
│  ├─ txt2img-api/                   # 文本 -> 位图 FastAPI 服务
│  │  ├─ app/main.py                 # 路由、关闭接口、ComfyUI 生命周期
│  │  ├─ app/generator.py            # 工作流加载、参数注入、ComfyUI 调用
│  │  ├─ app/models.py               # Pydantic 请求/响应模型
│  │  ├─ workflows/                  # ComfyUI API 格式工作流 JSON
│  │  ├─ tests/                      # pytest 测试
│  │  └─ scripts/                    # 后端 EXE 构建与模型下载脚本
│  └─ vectorizer-api/                # 位图 -> SVG FastAPI 服务
│     ├─ app/main.py                 # 路由与图片来源解析
│     ├─ app/image_processing.py     # rembg、降噪、裁剪、颜色量化
│     ├─ app/vectorization.py        # vtracer、SVG 预览、质量评估
│     ├─ app/models.py               # Pydantic 模型与参数校验
│     ├─ models/rembg/               # 离线 rembg ONNX 模型
│     └─ scripts/                    # 后端 EXE 构建脚本
├─ docs/                             # 项目文档
├─ tests/                            # 测试集
│  ├─ fixtures/                      # 测试样例文本
│  └─ README.md                      # 预留放测试脚本
├─ outputs/                          # 运行产物，已 gitignore
├─ README.md
├─ CLAUDE.md
└─ LICENSE
```

## 快速开始

### 环境要求

| 组件 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows 10 / 11 | 当前桌面交付和打包流程按 Windows 设计 |
| Node.js | 18+ | 桌面端开发与 CLI 运行；构建 CLI EXE 需要 Node.js 20+ |
| npm | 9+ | Node.js 包管理 |
| Python | 3.13+ | `txt2img-api` 要求 |
| uv | 推荐 | `txt2img-api` 的 Python 依赖管理 |
| GPU | NVIDIA 独显推荐 | ComfyUI 推理推荐独显；无 GPU 时可使用降级能力 |

矢量化服务需要本地 rembg 模型：

```text
services/vectorizer-api/models/rembg/isnet-general-use.onnx
```

模型 MD5：

```text
fc16ebd8b0c10d971d3513d564d01e29
```

可运行以下脚本下载：

```powershell
services\vectorizer-api\models\rembg\download-isnet-general-use.bat
```

### 安装与启动

建议使用三个终端分别启动两个后端和桌面端。

#### 1. 启动矢量化后端（端口 8000）

```powershell
cd services/vectorizer-api
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- [vectorizer API 说明文档](services/vectorizer-api/README.md)

#### 2. 启动文生图后端（端口 9001）

```powershell
cd services/txt2img-api
uv sync
uv run txt2img-api
```

如果不希望服务启动时自动拉起 ComfyUI：

```powershell
$env:AUTO_START_COMFYUI = "0"
uv run txt2img-api
```

此时 ComfyUI 不可用的请求会降级为 Pillow stub。

- [txt2img API说明](services\txt2img-api\README.md)

#### 3. 启动桌面端

```powershell
cd apps/desktop
npm install
npm run electron:dev
```

开发模式下 Electron 不自动管理后端进程，需要保持两个后端终端运行。

### 验证安装

```powershell
node apps/cli/bin/gen2vec.mjs health
node apps/cli/bin/gen2vec.mjs env
```

预期两个服务均可用：

```text
txt2img 服务:    正常
矢量化服务:      正常
```

## 使用指南

### 桌面端

桌面端提供三个主要工作模式：

| 模式 | 操作流程 |
| --- | --- |
| 单条生成 | 输入艺术字文本和风格提示词，调整矢量化参数，生成 PNG + SVG |
| 批量生成 | 粘贴或导入多条文本，逐条生成并写入批量汇总 CSV |
| 图片矢量化 | 选择本地 PNG/JPG 图片，跳过文生图，直接输出 SVG |

结果面板支持：

- 查看原图、透明图、SVG 回渲染预览图。
- 打开任务输出目录。
- 打开 SVG 预览。
- 从历史任务恢复本地产物。

### CLI 命令行

CLI 定位为自动化验收和批量处理工具。它只调用后端，不负责启动后端。

基本格式：

```powershell
node apps/cli/bin/gen2vec.mjs <command> [options]
```

命令列表：

| 命令 | 说明 | 示例 |
| --- | --- | --- |
| `pipeline` | 完整流水线：文本 -> 位图 -> SVG | `pipeline --text "七里香" --prompt "清新国风"` |
| `generate` | 仅生成位图 | `generate --text "Hello" --prompt "neon sign"` |
| `vectorize` | 仅矢量化已有图片 | `vectorize --input artwork.png --preset detailed` |
| `batch` | 批量流水线 | `batch --input-file testdata/art_text_prompts_150.txt` |
| `health` | 后端健康检查 | `health` |
| `env` | 显示环境信息 | `env` |
| `shutdown` | 关闭后端服务 | `shutdown` |

常用示例：

```powershell
# 完整流水线
node apps/cli/bin/gen2vec.mjs pipeline --text "七里香" --prompt "清新国风，墨绿色金边" --vector-preset detailed

# 只生成位图
node apps/cli/bin/gen2vec.mjs generate --text "Hello" --prompt "neon sign, clean solid background"

# 只矢量化已有图片
node apps/cli/bin/gen2vec.mjs vectorize --input artwork.png --preset ultra --preview

# 批量生成
node apps/cli/bin/gen2vec.mjs batch --input-file testdata/art_text_prompts_150.txt --output-dir outputs/cli-batch
```

批量 TXT 输入格式：

```text
文本 | 风格提示词 | 负面提示词 | seed | resolution
七里香 | 清新国风，墨绿色金边 | 模糊，断笔 | 42 | 1024x1024
夏日冰饮 50% | 清爽蓝白配色，冰块纹理 | | 43 | 1024x1024
```

CSV 输入示例：

```csv
text,prompt,negative,seed,resolution
七里香,清新国风，墨绿色金边,模糊，断笔,42,1024x1024
Hello,neon sign,blur,100,1024x1024
```

JSON 输入示例：

```json
[
  { "text": "七里香", "prompt": "清新国风，墨绿色金边", "seed": 42 },
  { "text": "Hello", "prompt": "neon sign", "seed": 100 }
]
```

## API 参考

### 端点列表

| 方法 | 路径 | 服务 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/healthz` | 两个后端 | 健康检查 |
| `POST` | `/shutdown` | 两个后端 | 优雅关闭服务 |
| `POST` | `/api/v1/txt2img` | `txt2img-api` | 文本生成位图 |
| `POST` | `/api/v1/vectorize` | `vectorizer-api` | 位图矢量化 |

### 请求与响应示例

#### `GET /healthz`

```json
{ "ok": true, "service": "txt2img-api" }
```

```json
{ "ok": true, "service": "vectorizer-api" }
```

#### `POST /api/v1/txt2img`

请求：

```json
{
  "text": "七里香",
  "prompt": "清新国风，墨绿色金边",
  "negative_prompt": "",
  "resolution": "1024x1024",
  "seed": 42,
  "style": "default",
  "format": "PNG",
  "workflow": ""
}
```

响应：

```json
{
  "image_base64": "data:image/png;base64,...",
  "image_name": "txt2img-generated.png",
  "metadata": {
    "engine": "comfyui",
    "prompt": "清新国风，墨绿色金边",
    "resolution": "1024x1024",
    "seed": 42,
    "fallback_tier": 0,
    "workflow_used": "qwen_image_2512_gguf"
  },
  "workflow_api": {},
  "model_dependencies": {}
}
```

#### `POST /api/v1/vectorize`

请求：

```json
{
  "source_type": "generated",
  "text": "七里香",
  "prompt": "清新国风，墨绿色金边",
  "resolution": "1024x1024",
  "seed": 42,
  "vector": {
    "preset": "detailed",
    "color_precision": 6,
    "filter_speckle": 2,
    "corner_threshold": 30,
    "length_threshold": 3,
    "layer_difference": 4,
    "scale": 3,
    "evaluate_quality": true,
    "remove_edge_white_background": true
  },
  "generated_image": {
    "file_path": "outputs/task_xxx/original.png"
  }
}
```

响应：

```json
{
  "transparent_png": "data:image/png;base64,...",
  "preview_png": "data:image/png;base64,...",
  "png": "data:image/png;base64,...",
  "svg": "<svg ...></svg>",
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
    "quality": {
      "svg_fidelity": 94.7
    }
  }
}
```

## 配置说明

### 环境变量

| 变量 | 默认值 | 作用范围 | 说明 |
| --- | --- | --- | --- |
| `TXT2IMG_BACKEND_URL` | `http://127.0.0.1:9001/api/v1/txt2img` | desktop / CLI | 文生图接口完整 URL |
| `VECTORIZER_BACKEND_URL` | `http://127.0.0.1:8000/api/v1/vectorize` | desktop / CLI | 矢量化接口完整 URL |
| `TXT2IMG_WORKFLOW` | 空 | CLI | 指定 ComfyUI 工作流名；为空时使用后端降级链 |
| `ART_TEXT_OUTPUT_ROOT` | `outputs` 或用户文档目录 | desktop / CLI | 产物输出根目录 |
| `AUTO_START_COMFYUI` | `1` | txt2img-api | 是否在启动时自动拉起 ComfyUI |
| `COMFYUI_HOST` | `http://127.0.0.1:8188` | txt2img-api | ComfyUI API 地址 |
| `COMFYUI_POLL_TIMEOUT` | `500` | txt2img-api | 轮询 ComfyUI 完成的最大秒数 |
| `COMFYUI_POLL_INTERVAL` | `1.0` | txt2img-api | 轮询间隔秒数 |
| `WORKFLOW_PATH` | 空 | txt2img-api | 指定 ComfyUI API 格式 JSON 的绝对路径，会覆盖请求中的 `workflow` |
| `COMFYUI_LAUNCHER_BAT` | 空 | txt2img-api | 使用自定义 ComfyUI 启动脚本 |
| `COMFYUI_NETWORK_MODE` | `offline` | txt2img-api | 写入 ComfyUI-Manager 配置，减少启动联网检查 |

输出目录规则：

- CLI 默认写入当前工作目录下的 `outputs/`。
- 桌面端开发模式写入仓库根目录 `outputs/`。
- 桌面端打包模式写入 `Documents/Gen2Vec-ArtFont-App/outputs/`。
- 设置 `ART_TEXT_OUTPUT_ROOT` 后使用该目录。

### 矢量化预设

| 预设 | color_precision | filter_speckle | corner_threshold | length_threshold | layer_difference | scale | 适用场景 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `clean` | 2 | 48 | 120 | 30 | 38 | 2 | 路径更少，文件更小，适合干净图形 |
| `balanced` | 4 | 18 | 70 | 12 | 20 | 2 | 默认推荐，平衡细节与体积 |
| `detailed` | 6 | 2 | 30 | 3 | 4 | 3 | 保留更多颜色层次和边缘细节 |
| `ultra` | 8 | 1 | 20 | 2 | 2 | 3 | 最大细节，文件体积也最大 |

预设值来自 `services/vectorizer-api/app/vectorization.py`。传入预设后，仍可单独覆盖 6 个底层参数。

### 工作流降级链

`txt2img-api` 会根据文本内容选择候选工作流。显式传入 `workflow` 时只尝试指定工作流；未指定时使用降级链。

| 文本类型 | 优先级 1 | 优先级 2 | 兜底 |
| --- | --- | --- | --- |
| 中文为主 | `qwen_image_2512_gguf` | `test_z_image_turbo` | Pillow stub |
| 英文或其他 | `flux_schnell` | `test_z_image_turbo` | Pillow stub |

`WORKFLOW_PATH` 环境变量优先级最高，会直接指定工作流 JSON 路径。

## 输出规范

每次任务会生成独立目录，目录名由运行模式、时间和种子等信息组成。典型结构：

```text
outputs/
├─ task_YYYYMMDD_HHMMSS_mmm/
│  ├─ original.png                  # 文生图原始位图或用户上传原图
│  ├─ transparent.png               # 透明背景 PNG
│  ├─ result.svg                    # SVG 矢量图
│  ├─ preview.png                   # SVG 回渲染 PNG 预览
│  ├─ metadata.json                 # 参数、耗时、质量指标等元数据
│  ├─ run.log                       # key=value 运行日志
│  └─ workflows/                    # 文生图任务的工作流快照
│     ├─ workflow_api.json
│     ├─ nodes.md
│     └─ model_dependencies.json
└─ batch_summary.csv                # 批量任务汇总，如有
```

`metadata.json` 主要字段：

```json
{
  "schema_version": 1,
  "task_name": "task_YYYYMMDD_HHMMSS_mmm",
  "mode": "single",
  "engine": "vectorizer-api-split-pipeline",
  "generation": {
    "text": "七里香",
    "prompt": "清新国风，墨绿色金边",
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

## 开发指南

### 本地开发

```powershell
# 1. 安装 txt2img-api 依赖
cd services/txt2img-api
uv sync

# 2. 安装 vectorizer-api 依赖
cd ..\vectorizer-api
pip install -r requirements.txt

# 3. 安装桌面端依赖
cd ..\..\apps\desktop
npm install

# 4. 启动两个后端，再启动桌面端
npm run electron:dev
```

推荐后端分别在独立终端中启动，便于查看日志。

### 测试

当前自动化测试主要覆盖 `txt2img-api`：

```powershell
cd services/txt2img-api
uv run pytest -v
```

Python 语法检查：

```powershell
python -m compileall services/txt2img-api services/vectorizer-api
```

桌面端构建检查：

```powershell
cd apps/desktop
npm run build
```

### 构建与打包

#### 构建后端 EXE

```powershell
cd services/txt2img-api
.\scripts\build-backend-exe.ps1

cd ..\vectorizer-api
.\scripts\build-backend-exe.ps1
```

#### 构建 CLI EXE

```powershell
cd apps/cli
npm install
npm run build
```

CLI 单文件 EXE 使用 Node.js SEA，构建环境需要 Node.js 20+。

#### 构建 Electron 安装包

```powershell
cd apps/desktop
npm install
npm run electron:build
```

`apps/desktop/package.json` 当前打包资源包括：

| 内容 | 来源 |
| --- | --- |
| `txt2img-backend.exe` | `services/txt2img-api/dist/` |
| `download-models.ps1` | `services/txt2img-api/dist/` |
| `README.md` | `services/txt2img-api/dist/` |
| `vectorizer-backend.exe` | `services/vectorizer-api/dist/` |
| `models/` | `services/vectorizer-api/dist/models` |
| `gen2vec_cli.exe` | `apps/cli/dist/` |

注意：`electron/main.cjs` 已包含检测和解压 `ComfyUI-Engine.exe` 的逻辑。如果交付包需要内置 ComfyUI 自解压包，需要确认 `apps/desktop/package.json` 的 `extraResources` 同步包含该文件。

详见 [docs/electron-packaging.md](docs/electron-packaging.md)。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 桌面端 | Electron 42, Vue 3, Vite 8 |
| CLI | Node.js ES Modules, Node.js SEA |
| 后端框架 | FastAPI, Uvicorn, Pydantic |
| 文生图 | ComfyUI, Flux Schnell, Z-Image Turbo, Qwen-Image |
| 图像处理 | Pillow, OpenCV, scikit-image |
| 背景移除 | rembg, ONNX Runtime, `isnet-general-use.onnx` |
| 矢量化 | vtracer, svgwrite, cairosvg |
| 打包 | electron-builder, PyInstaller, PowerShell |

## 许可证

本项目源代码基于 [MIT License](LICENSE) 开源。

第三方依赖、ComfyUI 工作流、模型权重和下载脚本所涉及的模型文件可能遵循各自的许可证或使用条款。分发或商用前，请同时核对对应模型和依赖的许可要求。

Copyright (c) 2026 Breeze and Gen2Vec ArtFont contributors.
