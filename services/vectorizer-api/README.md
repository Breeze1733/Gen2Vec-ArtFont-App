# vectorizer-api

位图矢量化后端。把用户上传或文生图生成的 PNG / JPG 艺术字图像处理为透明 PNG、SVG 矢量图与 SVG 回渲染预览图。

**职责边界**：本服务只负责**位图到矢量图的转换与质量评估**；艺术字位图的生成由 [`txt2img-api`](../txt2img-api/README.md) 独立完成。

---

## 架构

```text
POST /api/v1/vectorize
  │
  ├─ 图片来源解析（上传 / 流水线传入）
  │
  ├─ 透明背景处理 ──→ OpenCV 预处理 ──→ 颜色量化
  │
  ├─ vtracer 路径追踪 ──→ 语义图层重组 ──→ SVG
  │
  └─ SVG 回渲染 PNG ──→ 保真度评估 ──→ 元数据与质量指标
```

---

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/healthz` | 健康检查 |
| `POST` | `/shutdown` | 关闭后端进程 |
| `POST` | `/api/v1/vectorize` | 位图转透明 PNG + SVG |

桌面端与 CLI 默认调用 `http://127.0.0.1:8000/api/v1/vectorize`。

### `GET /healthz`

```json
{ "ok": true, "service": "vectorizer-api" }
```

### `POST /shutdown`

关闭服务进程，返回确认信息。

### `POST /api/v1/vectorize`

#### 请求体

用户上传图片：

```json
{
  "source_type": "upload",
  "image_base64": "data:image/png;base64,...",
  "image_name": "input.png",
  "vector": { "preset": "balanced" }
}
```

文生图流水线传入：

```json
{
  "source_type": "generated",
  "text": "七里香",
  "prompt": "清新国风、墨绿色金边",
  "resolution": "1024x1024",
  "seed": 42,
  "vector": { "preset": "detailed" },
  "generated_image": { "file_path": "outputs/task_xxx/original.png" }
}
```

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `source_type` | enum | `upload` | `upload`（用户上传）/ `generated`（流水线产出） |
| `text` | string | `""` | 文字内容，写入元数据 |
| `prompt` | string | `""` | 风格描述，写入元数据 |
| `negative` | string | `""` | 负面提示词，写入元数据 |
| `resolution` | string | `1024 x 1024` | 分辨率，格式 `宽x高` |
| `format` | string | `PNG + SVG` | 输出格式 |
| `seed` | int / null | `null` | 随机种子 |
| `vector` | object | `{preset: "balanced"}` | 矢量化参数，见[矢量化参数](#矢量化参数) |
| `image_base64` | string / null | `null` | 上传图片的 base64 |
| `image_path` | string / null | `null` | 上传图片的路径 |
| `image_name` | string / null | `null` | 原文件名，用于命名任务目录 |
| `generated_image` | object / null | `null` | 流水线图片引用（`artifact_id` / `image_base64` / `file_path`） |

#### 响应

```json
{
  "transparent_png": "data:image/png;base64,...",
  "preview_png": "data:image/png;base64,...",
  "png": "data:image/png;base64,...",
  "svg": "<svg ...></svg>",
  "metadata": {
    "engine": "vectorizer-api-split-pipeline",
    "preprocess": {
      "transparent_size": { "width": 1024, "height": 1024 },
      "png_transparency": 72.4
    },
    "quality": { "svg_fidelity": 94.7 }
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `transparent_png` | 透明背景 PNG，data URL |
| `preview_png` | SVG 回渲染预览 PNG，data URL |
| `png` | 处理后的前景位图，data URL |
| `svg` | SVG 矢量图文本 |
| `metadata.preprocess.png_transparency` | PNG 透明度（百分数） |
| `metadata.quality.svg_fidelity` | SVG 还原度（百分数），可用于赛题「矢量还原度」验收 |

---

## 快速开始

### 依赖

| 组件 | 要求 |
| --- | --- |
| Python | 3.13+ |
| uv | 推荐（也可用 pip） |

### 安装与启动

```powershell
cd services\vectorizer-api
uv sync
uv run vectorizer-api
```

服务监听 `127.0.0.1:8000`。

没有 uv 时：

```powershell
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

> `requirements.txt` 由 `uv export` 从 `uv.lock` 生成，**请勿手改**。调整依赖请编辑 `pyproject.toml` 后执行 `uv lock` 并重新导出。

### 测试

本服务不含独立测试目录，矢量化相关的自动化验收由仓库根目录的 `tests/` 覆盖（含单图矢量化与 SVG 回渲染校验场景）。

---

## 配置

本服务**无独立环境变量**，运行期配置全部通过请求体的 `vector` 对象传入。

模型路径自动解析，无需配置：

| 运行方式 | 模型查找位置 |
| --- | --- |
| 开发（源码） | `services/vectorizer-api/models/rembg/` |
| 打包（EXE） | `<EXE 同级目录>/models/rembg/` |

服务内部会设置 `U2NET_HOME` 指向本地模型目录，确保 rembg 只从本地加载、不联网下载。

---

## 透明背景处理

入口为 `app/image_processing.py` 的 `preprocess_image()`。

处理规则：

1. 输入**已有 alpha 通道** → 直接转 `RGBA`，保留原透明信息，不重复抠图
2. 输入**无 alpha 通道**且 `remove_edge_white_background=true` → 用本地 rembg 模型移除背景
3. 对结果做边缘保留降噪、抗锯齿保留、主体裁剪与颜色量化
4. 无论是否执行背景移除，最终都计算 `PNG 透明度`

已有 alpha 通道的判定：

```python
has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
```

### PNG 透明度指标

描述输出透明 PNG 的整体透明程度，是**画布级统计值**，不是抠图质量分：

```text
png_transparency = (1 - mean(alpha) / 255) * 100
```

| 图像状态 | 结果 |
| --- | ---: |
| 全透明 | `100.0%` |
| 全不透明 | `0.0%` |
| 大量透明背景 + 少量主体 | 较高 |

> 该指标受画布尺寸与裁剪策略影响：小主体放在大透明画布中会得到更高透明度，但不等于更高抠图质量。

---

## 矢量化流程

```text
预处理后的前景位图
  → 形态学闭开滤波 + 连通域面积滤波
  → vtracer 路径追踪（三次贝塞尔拟合）
  → 语义图层解耦与拓扑分类
  → W3C SVG 组装 + Dublin Core / JSON-LD 元数据
  → resvg_py 回渲染 PNG
  → 保真度评估
```

图层分类结果：

| 图层 | 典型内容 |
| --- | --- |
| `layer-shadow` | 投影、暗色底衬 |
| `layer-stroke` | 描边、外框 |
| `layer-main-text` | 主体文字 |
| `layer-decorations` | 外围花瓣、叶片、光芒等装饰 |

分组写入 SVG 的 `<g>`，可在 Inkscape / Illustrator 中按图层单独编辑。算法细节见[算法原理说明](../../docs/算法原理说明.md#三轮廓提取与路径拟合)。

### SVG 还原度指标

将 SVG 用 `resvg_py` 回渲染为 PNG，与透明 PNG 对比，按三个子指标加权：

| 指标 | 权重 | 方法 |
| --- | ---: | --- |
| SSIM | 0.50 | 11×11 滑动窗口（小图 7×7），`data_range=255` |
| 梯度相关性 | 0.30 | Sobel 梯度图的皮尔逊相关系数，容忍 1~2px 边缘偏移 |
| 前景色分布 | 0.20 | 仅前景像素的 Lab a/b 直方图相关性 |

```text
svg_fidelity = ssim*0.50 + edge_corr*0.30 + color_corr*0.20   → 0..100
```

> 透明区域通过 alpha 掩码统一为中性灰后参与比较，因此天然接近满分；颜色对比只看前景，排除背景灰干扰。

---

## 矢量化参数

服务支持 **4 个预设 + 6 个底层参数**。传入 `preset` 加载对应默认值；请求中同时传入底层参数时以请求值覆盖。

| 预设 | 名称 | 适用场景 |
| --- | --- | --- |
| `clean` | 清爽 | 色块分明、结构简单的图，输出体积最小 |
| `balanced` | 平衡 | **默认值**，兼顾质量与体积 |
| `detailed` | 精细 | 细节丰富、需要保留较多层次 |
| `ultra` | 超清 | 追求最高还原度，输出体积最大 |

| 参数 | 范围 | 说明 |
| --- | :---: | --- |
| `color_precision` | 1–8 | 颜色聚类精度，值越高颜色分层越细 |
| `filter_speckle` | 0–64 | 小噪点过滤阈值，值越高越倾向删除小区域 |
| `corner_threshold` | 1–180 | 角点阈值，值越低越容易保留尖角 |
| `length_threshold` | 1–64 | 路径片段长度阈值，值越低细节越多 |
| `layer_difference` | 1–64 | 颜色层之间的差异阈值 |
| `scale` | 1–4 | 矢量化前的上采样倍率 |

另有 4 个开关：`evaluate_quality`、`remove_edge_white_background`、`white_value_threshold`、`white_saturation_threshold`。

各预设的具体数值与全部参数说明见[参数配置说明](../../docs/参数配置说明.md#二矢量化参数)。

---

## rembg 离线模型

固定使用 `isnet-general-use` 模型，**只从本地加载，运行时不下载**。

| 项 | 值 |
| --- | --- |
| 文件 | `isnet-general-use.onnx` |
| 大小 | 约 170 MB |
| MD5 | `FC16EBD8B0C10D971D3513D564D01E29` |
| 来源 | [danielgatis/rembg](https://github.com/danielgatis/rembg) release `v0.0.0` |

放置位置：

```text
开发：services/vectorizer-api/models/rembg/isnet-general-use.onnx
打包：dist/models/rembg/isnet-general-use.onnx
```

获取方式：

```powershell
# 单独下载
.\models\rembg\download-isnet-general-use.ps1

# 或随开发依赖一起
.\scripts\setup-deps.ps1
```

模型缺失或 MD5 校验失败时，背景移除会返回明确错误。完整依赖清单见[模型与节点依赖清单](../../docs/模型与节点依赖清单.md)。

---

## 项目结构

```text
services/vectorizer-api/
├── app/
│   ├── main.py                FastAPI 应用、路由、图片来源解析、响应组装
│   ├── models.py              Pydantic 请求 / 响应模型
│   ├── image_processing.py    图片解码、背景移除、预处理、PNG 透明度
│   └── vectorization.py       路径追踪、图层分类、SVG 组装、保真度评估
├── models/rembg/              isnet-general-use.onnx 与下载脚本
├── scripts/
│   └── build-backend-exe.ps1  PyInstaller 打包脚本
├── backend_entry.py           PyInstaller 打包入口
└── pyproject.toml / uv.lock / requirements.txt
```

---

## 打包为 EXE

```powershell
.\scripts\build-backend-exe.ps1                  # 自动检测：有 uv 用 uv，否则用 python
.\scripts\build-backend-exe.ps1 -Toolchain uv
.\scripts\build-backend-exe.ps1 -Toolchain python
```

产物：`services/vectorizer-api/dist/vectorizer-backend.exe`

打包时会把 `models/` 复制到 `dist/models/`。**模型是 EXE 的旁挂文件，不内嵌**，交付时必须与 EXE 一同分发：

```text
dist/
├── vectorizer-backend.exe
└── models/rembg/isnet-general-use.onnx
```

---

## 相关源码

| 文件 | 说明 |
| --- | --- |
| `app/main.py` | FastAPI 路由、图片来源解析、响应组装 |
| `app/models.py` | 请求 / 响应模型与参数约束 |
| `app/image_processing.py` | 图片解码、背景移除、预处理、PNG 透明度计算 |
| `app/vectorization.py` | 路径追踪、图层分类、SVG 组装、保真度评估 |
| `scripts/build-backend-exe.ps1` | PyInstaller 打包脚本 |

---

## 相关文档

| 文档 | 内容 |
| --- | --- |
| [算法原理说明](../../docs/算法原理说明.md) | 预处理、轮廓提取、颜色分层、路径拟合、回渲染对比的算法细节 |
| [参数配置说明](../../docs/参数配置说明.md) | 矢量化参数、请求字段、输出目录规则 |
| [模型与节点依赖清单](../../docs/模型与节点依赖清单.md) | 模型来源、版本、许可与部署位置 |
| [安装部署说明](../../docs/安装部署说明.md) | 交付包部署与源码部署两条路径 |

## 与 monorepo 的关联

- 桌面端与 CLI 通过 HTTP 调用本服务 `http://127.0.0.1:8000/api/v1/vectorize`
- 上游位图来自 [`txt2img-api`](../txt2img-api/README.md)（端口 9001），也可直接接收用户上传图片
