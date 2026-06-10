# Vectorizer API

`vectorizer-api` 是 Gen2Vec ArtFont 的位图矢量化后端，负责把用户上传或文生图生成的 PNG/JPG 艺术字图像处理为透明 PNG、SVG 矢量图和 SVG 回渲染预览图。

服务采用 FastAPI，对外提供本地 HTTP 接口；核心流程为：

```text
输入 PNG/JPG
  -> 透明背景处理 / alpha 通道保留
  -> OpenCV 预处理
  -> vtracer 路径追踪
  -> SVG 回渲染 PNG
  -> 元数据与质量指标
```

## 功能范围

- 对无 alpha 通道的图片，可使用本地 rembg 模型进行背景移除。
- 对已有 alpha 通道的图片，直接保留原 alpha，不重复做透明化。
- 输出透明 PNG、SVG 文本、SVG 回渲染 PNG 预览和结构化 metadata。
- 记录 `PNG 透明度` 与 `SVG 还原度` 两个质量指标。

## 质量指标

### PNG 透明度

`PNG 透明度` 用于描述输出透明 PNG 的整体透明程度。它不是抠图质量分，而是基于 alpha 通道的画布级统计值。

计算位置：

```text
services/vectorizer-api/app/image_processing.py
calculate_png_transparency()
```

计算公式：

```text
png_transparency = (1 - mean(alpha) / 255) * 100
```

其中：

- `alpha` 是 RGBA 图像的 alpha 通道矩阵，取值范围为 `0..255`。
- `alpha = 0` 表示完全透明。
- `alpha = 255` 表示完全不透明。
- 输出单位为百分数，保留 1 位小数。

示例：

| 图像状态 | 结果 |
| --- | ---: |
| 全透明 | `100.0%` |
| 全不透明 | `0.0%` |
| 大量透明背景 + 少量主体 | 较高 |
| 主体占满画布 | 较低 |

注意：该指标会受到画布尺寸和裁剪策略影响。小主体放在大透明画布中会得到更高透明度，但这不等同于更高抠图质量。

### SVG 还原度

`SVG 还原度` 用于描述 SVG 回渲染 PNG 与透明 PNG 输入之间的结构相似程度。当前实现使用加权混合评分算法，综合归一化像素误差、人眼感知权重和边缘结构保留度进行评估，并以百分数输出。

计算位置：

```text
services/vectorizer-api/app/vectorization.py
_calculate_svg_fidelity()
```

计算流程：

1. 将透明 PNG 和 SVG 回渲染 PNG 都转换为 `RGB`。
2. 如果两张图尺寸不一致，将 SVG 回渲染图 resize 到原图尺寸。
3. 计算三个子指标并加权融合：
   - **NRMSE**（归一化均方根误差）：基础像素差异，比 SSIM 对矢量化平滑边缘的容忍度更高。
   - **人眼加权 NRMSE**：按像素亮度加权，暗区色差权重降低，亮区色差权重提高，更符合人眼主观感受。
   - **边缘结构保留度**：用 Sobel 算子提取边缘后比较差异，评估形状轮廓是否完整保留。
4. 三个分量加权求和后转换为 `0..100` 的百分数。

计算公式：

```text
nrmse = 1.0 - MSE(original, vector) / (255^2)
luminance = 0.299*R + 0.587*G + 0.114*B
weight = 0.3 + 0.7 * (luminance / 255)
weighted_nrmse = 1.0 - MSE(weighted_diff) / (255^2)
edge_score = 1.0 - mean(|Sobel(original) - Sobel(vector)|)
svg_fidelity = nrmse * 0.60 + weighted_nrmse * 0.25 + edge_score * 0.15
```

保留 RGB 的原因：

- 透明底艺术字的边缘抗锯齿、镂空区域和半透明阴影由人眼加权分量间接覆盖。
- 仅比较 RGB 配合亮度权重，既避免 alpha 通道噪声干扰，又能反映人眼对边缘过渡区的真实感知。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/healthz` | 健康检查 |
| `POST` | `/shutdown` | 关闭后端进程 |
| `POST` | `/api/v1/vectorize` | 位图转透明 PNG + SVG |

桌面端和 CLI 默认调用：

```text
http://127.0.0.1:8000/api/v1/vectorize
```

## 请求示例

### 用户上传图片

```json
{
  "source_type": "upload",
  "image_base64": "data:image/png;base64,...",
  "image_name": "input.png",
  "vector": {
    "preset": "balanced",
    "color_precision": 4,
    "filter_speckle": 18,
    "corner_threshold": 70,
    "length_threshold": 12,
    "layer_difference": 20,
    "scale": 2,
    "evaluate_quality": true,
    "remove_edge_white_background": true
  }
}
```

### 文生图流水线图片

```json
{
  "source_type": "generated",
  "text": "七里香",
  "prompt": "清新国风，墨绿色金边，植物叶片装饰",
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

## 响应字段

```json
{
  "transparent_png": "data:image/png;base64,...",
  "preview_png": "data:image/png;base64,...",
  "png": "data:image/png;base64,...",
  "svg": "<svg ...></svg>",
  "metadata": {
    "engine": "vectorizer-api-split-pipeline",
    "preprocess": {
      "transparent_size": {
        "width": 1024,
        "height": 1024
      },
      "png_transparency": 72.4
    },
    "quality": {
      "svg_fidelity": 94.7
    }
  }
}
```

字段说明：

- `transparent_png`：透明背景 PNG，data URL 格式。
- `preview_png` / `png`：SVG 回渲染后的 PNG 预览，data URL 格式。
- `svg`：格式化后的 SVG 文本。
- `metadata.preprocess.png_transparency`：PNG 透明度，百分数。
- `metadata.quality.svg_fidelity`：SVG 还原度，百分数。

## 透明背景处理逻辑

入口函数为 `preprocess_image()`，位于 `app/image_processing.py`。

处理规则：

1. 如果输入图片已有 alpha 通道，直接转换为 `RGBA` 并保留原图透明信息。
2. 如果输入图片没有 alpha 通道，并且 `remove_edge_white_background=true`，使用本地 rembg 模型移除背景。
3. 对 rembg 输出进行边缘保留降噪、抗锯齿保留、主体裁剪和颜色量化。
4. 无论是否执行背景移除，最终都会计算 `PNG 透明度`。

已有 alpha 通道的判定：

```python
has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
```

因此，透明 PNG 输入不会被重复抠图，但仍会参与透明度统计。

## 矢量化参数

服务支持 4 个预设和 6 个底层参数。传入 `preset` 后会加载对应默认值；如果请求中同时传入底层参数，则以请求值覆盖预设值。

| 预设 | color_precision | filter_speckle | corner_threshold | length_threshold | layer_difference | scale | 适用场景 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `clean` | 2 | 48 | 120 | 30 | 38 | 2 | 路径更少，文件更小，适合干净图形 |
| `balanced` | 4 | 18 | 70 | 12 | 20 | 2 | 默认推荐，平衡细节和体积 |
| `detailed` | 6 | 2 | 30 | 3 | 4 | 3 | 保留更多颜色层次和边缘细节 |
| `ultra` | 8 | 1 | 20 | 2 | 2 | 3 | 最大细节，文件体积也最大 |

参数含义：

- `color_precision`：颜色精度，值越高颜色分层越细。
- `filter_speckle`：小噪点过滤阈值，值越高越倾向删除小区域。
- `corner_threshold`：角点阈值，影响路径转角保留。
- `length_threshold`：路径片段长度阈值。
- `layer_difference`：颜色层之间的差异阈值。
- `scale`：矢量化前的上采样倍率。

## rembg 离线模型

后端固定使用 `isnet-general-use` 模型，并只从本地加载，不会在运行时下载模型。

开发运行时放置路径：

```text
services/vectorizer-api/models/rembg/isnet-general-use.onnx
```

打包运行时放置路径：

```text
dist/models/rembg/isnet-general-use.onnx
```

模型 MD5：

```text
fc16ebd8b0c10d971d3513d564d01e29
```

如果模型不存在或校验失败，背景移除会返回明确错误。

## 本地运行

```powershell
cd services/vectorizer-api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

健康检查：

```powershell
curl http://127.0.0.1:8000/healthz
```

## 打包为 EXE

在 `services/vectorizer-api` 目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-backend-exe.ps1
```

打包产物：

```text
services/vectorizer-api/dist/vectorizer-backend.exe
```

启动打包后的后端：

```powershell
.\vectorizer-backend.exe --host 127.0.0.1 --port 8000
```

也可以双击：

```text
services/vectorizer-api/scripts/start-backend.bat
```

## 相关源码

| 文件 | 说明 |
| --- | --- |
| `app/main.py` | FastAPI 路由、请求来源解析、响应组装 |
| `app/models.py` | Pydantic 请求/响应模型 |
| `app/image_processing.py` | 图片解码、透明背景处理、PNG 透明度计算 |
| `app/vectorization.py` | vtracer 转 SVG、SVG 回渲染、SVG 还原度计算 |
| `scripts/build-backend-exe.ps1` | PyInstaller 打包脚本 |
