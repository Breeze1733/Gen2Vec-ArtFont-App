# txt2img-api

文生图生成后端。接收前端提示词等参数，通过 ComfyUI（或本地降级方案）生成图片，返回 PNG data URL 和元数据。

本服务只负责**生成位图**，后续位图到 SVG 的矢量化由独立的 `vectorizer-api` 服务处理。

## 架构

```
请求 → FastAPI → _call_comfyui_api() ──成功──→ 返回图片
                (HTTP POST /prompt          │
                 → 轮询 history             │
                 → 下载图片)                │
                  │                         │
                  └──失败/不可达─────────────┘
                           ↓
                   _local_stub_generate()  ← Pillow 降级
```

- ComfyUI 模式：提交工作流 → 轮询完成 → 下载图片 → base64 编码返回
- 本地降级模式：Pillow 生成渐变背景+文字，确保接口始终可用

## 接口

### `GET /healthz`

```json
{ "ok": true, "service": "txt2img-api" }
```

### `POST /api/v1/txt2img`

#### 请求体

```json
{
    "prompt": "霓虹城市夜景",
    "negative_prompt": "模糊, 低清晰度",
    "resolution": "1024 x 1024",
    "seed": 42,
    "style": "neon",
    "format": "PNG",
    "workflow": "test_z_image_turbo"
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `prompt` | string | — | **必填**，文本提示词 |
| `negative_prompt` | string | `""` | 负面提示词 |
| `resolution` | string | `"1024 x 1024"` | 格式 `宽 x 高`，如 `2048x1024` |
| `seed` | int | `0` | 随机种子，`0` 表示不指定（由 ComfyUI 决定） |
| `style` | string | `"default"` | 风格标签 |
| `format` | string | `"PNG"` | 仅支持 `"PNG"` 或 `"PNG + SVG"` |
| `workflow` | string | `""` | 工作流文件名（不含路径和扩展名），对应 `workflows/{name}.json` |

如果 `workflow` 为空，默认使用 `workflows/txt2img_api.json`。也可通过 `WORKFLOW_PATH` 环境变量完全覆盖。

#### 响应

```json
{
    "image_base64": "data:image/png;base64,...",
    "image_name": "ni-hong-cheng-shi-ye-jing.png",
    "metadata": {
        "engine": "comfyui",
        "prompt": "霓虹城市夜景",
        "negative_prompt": "模糊, 低清晰度",
        "resolution": "1024x1024",
        "seed": 42,
        "style": "neon",
        "format": "PNG",
        "canvas": { "width": 1024, "height": 1024 },
        "comfyui_prompt_id": "xxx-xxx-xxx",
        "generated_at": "2026-05-16T12:00:00+00:00",
        "artifact": {
            "image_name": "ni-hong-cheng-shi-ye-jing.png",
            "byte_length": 123456
        }
    }
}
```

| 字段 | 说明 |
|------|------|
| `image_base64` | PNG 图片的 data URL，可直接用于 `<img src="...">` |
| `image_name` | 自动根据 prompt 生成的文件名 |
| `metadata` | 完整的生成参数和执行信息 |

`metadata.engine` 标识实际使用的引擎：`"comfyui"` 或 `"local-studio"`。

## 快速开始

### 依赖

- Python ≥ 3.13
- uv（推荐）或 pip

### 安装与启动

```bash
cd services/txt2img-api
uv sync
uv run txt2img-api
```

或直接用 uvicorn：

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 9001 --app-dir src
```

服务默认监听 `0.0.0.0:9001`。

### 测试

```bash
cd services/txt2img-api
uv run pytest
```

## 配置

全部通过环境变量控制：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AUTO_START_COMFYUI` | `"1"` | 设为 `"0"` 禁用 ComfyUI 自动启动 |
| `COMFYUI_HOST` | `"http://127.0.0.1:8188"` | ComfyUI 服务地址 |
| `COMFYUI_POLL_TIMEOUT` | `"120"` | 轮询 ComfyUI 结果的最大等待秒数 |
| `COMFYUI_POLL_INTERVAL` | `"1.0"` | 轮询间隔（秒） |
| `WORKFLOW_PATH` | — | 完全指定工作流 JSON 的绝对路径，***会覆盖*** `workflow` 请求字段 |

示例：使用手动启动的 ComfyUI 运行：

```bash
AUTO_START_COMFYUI=0 uv run txt2img-api
```

## ComfyUI 集成

### 自动启动

启动 txt2img-api 时，如果检测到仓库内的可移植 ComfyUI 捆绑包，会自动以**无窗口、无浏览器**模式在后台启动：

```
services/txt2img-api/
└── ComfyUI_windows_portable_nvidia/
    └── ComfyUI_windows_portable/
        └── python_embeded/python.exe  ← 自动检测
            └── ComfyUI/main.py         ← 自动启动
```

启动参数为 `--fast fp16_accumulation`，输出定向到 `DEVNULL`，不显示控制台窗口。

### 交互流程

```
txt2img-api                              ComfyUI
  │                                      │
  ├─ POST /prompt ──────────────────────→│  (提交工作流 JSON)
  │  ← { prompt_id: "xxx" }             │
  │                                      │
  ├─ GET /history/{prompt_id} ──────────→│  (轮询完成状态)
  │  ← { status: { completed: true } }  │
  │                                      │
  ├─ GET /view?filename=... ────────────→│  (下载生成图片)
  │  ← png bytes                        │
```

### 手动启动 ComfyUI

如果不想使用自动启动，可先自行启动 ComfyUI：

```bash
cd services/txt2img-api/ComfyUI_windows_portable_nvidia/ComfyUI_windows_portable
.\python_embeded\python.exe -s ComfyUI\main.py
```

然后设置 `AUTO_START_COMFYUI=0` 运行 txt2img-api。

## 工作流

工作流 JSON 文件存放在 `services/txt2img-api/workflows/` 目录下，格式为 ComfyUI **API 格式**（flat JSON dict，每个节点包含 `class_type` 和 `inputs`）。

请求时通过 `workflow` 字段指定工作流名称（不含 `.json` 扩展名），例如 `workflows/test_z_image_turbo.json` → `"workflow": "test_z_image_turbo"`。

工作流中的节点通过 `class_type` 自动识别并注入参数：

| 节点 class_type | 注入参数 |
|----------------|---------|
| `CLIPTextEncode` | `inputs.text` — 第一个为正向提示词，第二个为负向提示词 |
| `EmptyLatentImage` / `EmptySD3LatentImage` | `inputs.width`, `inputs.height` |
| `KSampler` / `KSamplerAdvanced` | `inputs.seed` |

## 本地降级引擎

当 ComfyUI 不可达时，自动降级为 Pillow 本地生成：

- 根据 `seed` 生成随机渐变背景
- 在左上角绘制提示词文字
- 返回标准 PNG data URL

降级引擎确保前端在 ComfyUI 未就绪时仍能看到正常响应，不会报错。

## 项目结构

```
services/txt2img-api/
├── src/app/
│   ├── main.py          FastAPI 应用、路由、ComfyUI 生命周期管理
│   ├── models.py        Pydantic 请求/响应模型
│   └── generator.py     核心生成逻辑（ComfyUI 客户端 + 本地 stub）
├── workflows/           ComfyUI 工作流 JSON 模板
├── tests/               pytest 测试
├── pyproject.toml       项目元数据和依赖
└── pytest.ini           测试配置
```

## 与 monorepo 的关联

- 桌面端前端通过 HTTP 直接调用本服务 `http://127.0.0.1:9001/api/v1/generate`
- 生成的 PNG 位图可后续发送到 `vectorizer-api`（端口 8000）进行矢量化
