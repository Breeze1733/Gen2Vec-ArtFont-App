# CLAUDE.md

本文档给 Claude Code / Codex 等代码代理使用，用于快速理解仓库结构、运行方式和修改约束。

## 沟通约定

- 与用户沟通使用中文。
- 文档、注释、提交说明优先使用中文。
- 代码标识符、API 字段、文件名、专有框架名使用英文原名。
- 修改前先读相关模块，优先沿用现有风格，不做无关重构。

## 项目定位

Gen2Vec ArtFont 是一个本地优先的 AI 艺术字生成与矢量化应用。

主流程：

```text
文字 + 风格提示词
  -> txt2img-api
  -> ComfyUI 工作流或 Pillow stub
  -> original.png
  -> vectorizer-api
  -> transparent.png + result.svg + preview.png
```

用户入口有两个：

- `apps/desktop`：Electron + Vue 3 桌面端，适合日常交互。
- `apps/cli`：Node.js CLI，适合批量验收、脚本自动化和调试。

后端分为两个独立服务：

- `services/txt2img-api`：文本到位图，默认端口 `9001`。
- `services/vectorizer-api`：位图到 SVG，默认端口 `8000`。

## 仓库结构

```text
apps/
├─ desktop/
│  ├─ electron/main.cjs              # Electron 主进程、后端进程管理、IPC、产物写入
│  ├─ electron/preload.cjs           # contextBridge，暴露 window.artTextApp
│  ├─ src/renderer/App.vue           # 主界面、任务编排、历史恢复
│  ├─ src/renderer/api.js            # 渲染进程 API 封装
│  ├─ src/renderer/components/       # 表单、参数、结果、历史组件
│  └─ src/renderer/styles/global.css # 全局样式
├─ cli/
│  ├─ bin/gen2vec.mjs                # CLI 入口和参数解析
│  ├─ src/api.mjs                    # 后端 HTTP 调用
│  ├─ src/commands/                  # generate/vectorize/pipeline/batch/env
│  └─ src/utils/output.mjs           # 输出目录、元数据、CSV 汇总
services/
├─ txt2img-api/
│  ├─ app/main.py                    # FastAPI 路由、ComfyUI 启动和关闭
│  ├─ app/generator.py               # 工作流加载、参数注入、ComfyUI 调用、降级链
│  ├─ app/models.py                  # Pydantic 请求/响应模型
│  ├─ workflows/                     # ComfyUI API 格式 JSON
│  └─ tests/                         # pytest
└─ vectorizer-api/
   ├─ app/main.py                    # FastAPI 路由和图片来源解析
   ├─ app/models.py                  # Pydantic 请求/响应模型
   ├─ app/image_processing.py        # rembg、降噪、裁剪、颜色量化
   ├─ app/vectorization.py           # vtracer、SVG 格式化、质量评估
   └─ models/rembg/                  # isnet-general-use.onnx
```

## 关键架构约定

- 桌面端开发模式不自动启动后端；打包模式才由 Electron 主进程启动 `resources/backend` 下的 EXE。
- CLI 不管理后端生命周期，只检查和调用已运行的后端。
- 文生图请求由 `txt2img-api` 选择工作流；如果请求中 `workflow` 为空，按文本语言走降级链。
- `WORKFLOW_PATH` 环境变量优先级最高，会覆盖请求中的 `workflow`。
- 矢量化优先使用本地路径传图，失败时再回退到 base64，减少大图在 IPC/HTTP 中传输。
- `vectorizer-api` 强制使用本地 rembg 模型，不应在运行时下载模型。
- 运行产物统一写入任务目录，历史恢复依赖这些固定文件名。

## 常用命令

### txt2img-api

```powershell
cd services/txt2img-api
uv sync
uv run txt2img-api
```

关闭 ComfyUI 自动启动：

```powershell
$env:AUTO_START_COMFYUI = "0"
uv run txt2img-api
```

测试：

```powershell
cd services/txt2img-api
uv run pytest -v
```

### vectorizer-api

```powershell
cd services/vectorizer-api
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

需要保证模型存在：

```text
services/vectorizer-api/models/rembg/isnet-general-use.onnx
```

### desktop

```powershell
cd apps/desktop
npm install
npm run electron:dev
```

构建渲染层：

```powershell
cd apps/desktop
npm run build
```

打包安装包：

```powershell
cd apps/desktop
npm run electron:build
```

### CLI

```powershell
node apps/cli/bin/gen2vec.mjs health
node apps/cli/bin/gen2vec.mjs pipeline --text "七里香" --prompt "清新国风，墨绿色金边"
node apps/cli/bin/gen2vec.mjs vectorize --input artwork.png --preset detailed
node apps/cli/bin/gen2vec.mjs batch --input-file testdata/art_text_prompts_150.txt
```

构建 CLI 单文件 EXE：

```powershell
cd apps/cli
npm install
npm run build
```

注意：CLI EXE 构建使用 Node.js SEA，需要 Node.js 20+。

## API 端点

| 方法 | 路径 | 服务 | 说明 |
| --- | --- | --- | --- |
| `GET` | `/healthz` | 两个后端 | 健康检查 |
| `POST` | `/shutdown` | 两个后端 | 优雅退出 |
| `POST` | `/api/v1/txt2img` | `txt2img-api` | 文本生成 PNG |
| `POST` | `/api/v1/vectorize` | `vectorizer-api` | PNG/JPG 转 SVG |

默认 URL：

```text
http://127.0.0.1:9001/api/v1/txt2img
http://127.0.0.1:8000/api/v1/vectorize
```

## 工作流与模型

`services/txt2img-api/app/generator.py` 中的降级链：

```python
_CHINESE_FALLBACK = ["qwen_image_2512_gguf", "test_z_image_turbo"]
_ENGLISH_FALLBACK = ["flux_schnell", "test_z_image_turbo"]
```

工作流 JSON 必须是 ComfyUI API 格式，即顶层为节点字典，每个节点包含 `class_type` 和 `inputs`。后端通过 `class_type` 自动注入：

- `CLIPTextEncode` / `CLIPTextEncodeFlux`：正向与负向提示词。
- `EmptyLatentImage` / `EmptySD3LatentImage`：宽高。
- `KSampler` / `KSamplerAdvanced`：seed。

Qwen-Image 请求分辨率会映射到官方支持的比例尺寸。

## 矢量化预设

真实默认值位于 `services/vectorizer-api/app/vectorization.py`，桌面端和 CLI 也应保持一致。

| 预设 | color_precision | filter_speckle | corner_threshold | length_threshold | layer_difference | scale |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `clean` | 2 | 48 | 120 | 30 | 38 | 2 |
| `balanced` | 4 | 18 | 70 | 12 | 20 | 2 |
| `detailed` | 6 | 2 | 30 | 3 | 4 | 3 |
| `ultra` | 8 | 1 | 20 | 2 | 2 | 3 |

如果调整预设，至少同步检查：

- `services/vectorizer-api/app/vectorization.py`
- `apps/desktop/src/renderer/App.vue`
- `apps/cli/src/utils/output.mjs`

## 输出约定

任务目录固定包含：

```text
original.png
transparent.png
result.svg
preview.png
metadata.json
run.log
```

文生图任务还会包含：

```text
workflows/workflow_api.json
workflows/nodes.md
workflows/model_dependencies.json
```

不要随意改这些文件名，桌面端历史恢复、CLI 汇总和测试验收都依赖它们。

输出根目录：

- CLI 默认：当前工作目录下的 `outputs/`
- 桌面端开发模式：仓库根目录 `outputs/`
- 桌面端打包模式：`Documents/Gen2Vec-ArtFont-App/outputs/`
- `ART_TEXT_OUTPUT_ROOT` 可覆盖

## 打包注意事项

后端：

```powershell
cd services/txt2img-api
.\scripts\build-backend-exe.ps1

cd services/vectorizer-api
.\scripts\build-backend-exe.ps1
```

桌面端 `apps/desktop/package.json` 的 `build.extraResources` 当前会复制：

- `txt2img-backend.exe`
- `7za.exe`
- `ComfyUI-GGUF.zip`
- `download-comfyui-engine.ps1`
- `download-models.ps1`
- `README.md`
- `vectorizer-backend.exe`
- `models/`
- `gen2vec_cli.exe`

`electron/main.cjs` 已实现 ComfyUI 引擎下载（`download-comfyui-engine.ps1`）和模型下载（`download-models.ps1`）流程。打包时不再需要包含 ComfyUI-Engine.exe（7z SFX），引擎从 GitHub Releases 自动下载。

## 修改风险点

- 不要把 ComfyUI 便携包或大模型打进 PyInstaller 单文件 EXE；后端代码设计为在 EXE 同级查找。
- 不要让 vectorizer-api 在运行时联网下载 rembg 模型；它依赖离线模型和 MD5 校验。
- 不要把桌面端渲染层直接改成 Node API 访问；当前安全边界是 `contextBridge`。
- 不要随意改 `/healthz` 返回的 `service` 字段，Electron 会用它判断端口是否可复用。
- 不要随意改输出目录删除逻辑；`delete-output-dir` 有 outputs 根目录校验。
- 如果改 API schema，需要同步 `apps/desktop/src/renderer/api.js`、`apps/cli/src/api.mjs` 和 README。

## 推荐验证清单

根据改动范围选择验证：

```powershell
# Python 语法检查
python -m compileall services/txt2img-api services/vectorizer-api

# txt2img 自动化测试
cd services/txt2img-api
uv run pytest -v

# 桌面端构建
cd apps/desktop
npm run build

# CLI 健康检查，需要两个后端已启动
node apps/cli/bin/gen2vec.mjs health
```

当前仓库中 `vectorizer-api` 与 `desktop` 没有完整自动化测试；涉及这两块时，最好补充手动验证步骤或小型回归脚本。
