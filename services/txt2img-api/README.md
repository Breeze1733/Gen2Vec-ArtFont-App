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

如果 `workflow` 为空，按文本内容自动路由到候选工作流（见「提示词子系统」）；`_resolve_workflow_path` 的兜底默认值是 `workflows/flux_schnell.json`。也可通过 `WORKFLOW_PATH` 环境变量完全覆盖。

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
| `COMFYUI_POLL_TIMEOUT` | `"900"` | 轮询 ComfyUI 结果的最大等待秒数 |
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
| `CLIPTextEncode` | `inputs.text` |
| `CLIPTextEncodeFlux` | `inputs.t5xxl`（全长提示词）+ `inputs.clip_l`（短摘要，≤220 字符、按子句边界截断） |
| `EmptyLatentImage` / `EmptySD3LatentImage` | `inputs.width`, `inputs.height` |
| `KSampler` / `KSamplerAdvanced` | `inputs.seed` |

**正负向节点怎么定位**：顺 `KSampler` 的 `inputs.positive` / `inputs.negative` 连线解析，并沿 `ConditioningZeroOut` 之类的 conditioning 直通节点上溯。**不按节点在 JSON 里出现的顺序**——那会让一次从 ComfyUI 的重新导出就把正负向互换。没有可用采样器连线时，回退到「数字感知的节点 id 序」取前两个文本编码节点（`57:27` 排在 `9` 之后）。解析结果只写这两个节点，其余文本节点一概不动。

## 提示词子系统

用户输入从不直接提交给模型，而是经「文本分析 → profile 渲染 → 负面词处理」三步包装。完整参考见 [docs/prompt-pipeline.md](../../docs/prompt-pipeline.md)。

### 1. 文本分析（唯一真相源）

`TextAnalysis` 一次拆分出汉字 / 拉丁片段 / 数字 / 符号，路由与模板**共用同一份分析**（此前两边各持一个正则，`[A-Za-z]` 与 `[a-zA-Z]{2,}` 不一致，导致单字母内容被判为混排却从提示词里消失）。

关键属性 `residue` = 原文去掉**全部汉字**后的剩余串：

```
"咪哄之风 98% hey you"  ->  "98% hey you"
"咖啡 Latte 2.0"        ->  "Latte 2.0"
"单依纯 X"              ->  "X"
"满庭芳"                ->  ""
```

它**永远不含汉字**，所以「同时包含 …」子句只引用它就不可能把同一批汉字描述两遍。

### 2. profile 化渲染

单一渲染器 + 数据化 profile（`_FLUX_PROFILE` / `_ZIMAGE_PROFILE`），渲染流程零分支。段落顺序：

```
background -> style -> layout -> content -> accuracy -> inversion
```

用户把布局写在 `prompt`（风格字段）里，所以**把风格段提前到内容约束之前**就是让用户意图排到约 40 词固定约束前面。若 `prompt` 里已出现版式关键词（`居中`、`中间`、`右下角`、`layout`、`aligned` 等），layout 段改发中性表述，不覆盖用户自己的排布要求。

空 `text` 不再短路：背景抑制照发（下游 Inspyrenet 抠图仍需干净背景），只是不发 layout 与 content 段。

### 3. 负面提示词：能力探测 + 语义反演

**负面 conditioning 并非在所有工作流上都生效**：

| 工作流 | cfg | 负面文本节点 | 负面词是否生效 |
|---|---|---|---|
| `qwen_image_2512_gguf` | 2.5 | 节点 `5` | ✅ 唯一生效 |
| `flux_schnell` | **1.0** | 节点 `9` | ❌ cfg=1 时采样器忽略负面 conditioning |
| `test_z_image_turbo` | **1.0** | **无** | ❌ 负向由 `ConditioningZeroOut` 从正向派生 |

`_probe_negative_capability` 把 **cfg 与节点结构做与门**判定：只看 cfg 会漏判「cfg 正常但负向指向 ConditioningZeroOut」的工作流，只看节点会漏判 flux（节点看起来完全正常）。

- **capability 生效**（仅 Qwen）→ 照常写入负面 conditioning
- **capability 不生效** → 走**双语词表的「否定 → 肯定」反演**：命中词表的负面词转成正向子句注入（`模糊` → `边缘锐利、高清、矢量感清晰的字形`）；**未命中的词只记录在 metadata 里，绝不注入**——把 `broken strokes` 放进正向串等于邀请模型画断裂笔画。

反演子句本身禁止含否定词（有测试遍历全表守住）。

### 4. `prompt_synthesis` metadata

响应 metadata 新增顶层键 `prompt_synthesis`，是「实际用了哪个模型、注入了什么」的权威记录：

| 字段 | 含义 |
|---|---|
| `positive_prompt` | **权威值**，与产物 `workflow_api.json` 里注入节点的内容逐字相等 |
| `text_profile` / `residue` / `symbols` / `hanzi_count` | 文本分析结果 |
| `section_order` / `layout_intent_detected` | 渲染决策 |
| `clip_l_used` / `clip_l_token_estimate` / `clip_l_truncation_risk` | `clip_l` 仅 flux 家族使用，其余家族 `clip_l_used=false`、风险值为 `null` |
| `negative_strategy` | `negative-conditioning` 或 `positive-inversion` |
| `negative_capability` | `effective` / `reason` / `blockers` / `cfg` / `derived_from_positive` |
| `negative_written_to` | 负面文本实际写入的节点 id；`null` 表示无处可写 |
| `inversion.unmapped_terms` | 词表未覆盖、已丢弃的用户负面词——给用户看的清单 |

本地 stub 也发同名键（`applied: false`），消费方可无条件读取。

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

- 桌面端前端通过 HTTP 直接调用本服务 `http://127.0.0.1:9001/api/v1/txt2img`
- 生成的 PNG 位图可后续发送到 `vectorizer-api`（端口 8000）进行矢量化
