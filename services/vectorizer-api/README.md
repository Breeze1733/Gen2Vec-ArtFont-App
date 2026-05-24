# Vectorizer API

该服务仅负责“位图 -> SVG 矢量图”转换。

## 接口

- `GET /healthz`
- `POST /api/v1/vectorize`（已实现）

## 矢量化参数约定（6参数 + 4预设）

预设：

- `clean`
- `balanced`
- `detailed`
- `ultra`

6个底层参数：

- `color_precision`
- `filter_speckle`
- `corner_threshold`
- `length_threshold`
- `layer_difference`
- `scale`：输入图上采样倍率

说明：当传入 `preset` 时，默认采用预设参数；前端若同时传上这 6 参数，则按传入值覆盖对应预设项。

背景透明处理参数（默认开启）：

- `remove_edge_white_background`：是否使用本地 `rembg` 模型移除背景（默认 `true`）
- `white_value_threshold`：前端兼容保留字段，当前不参与 `rembg` 背景移除
- `white_saturation_threshold`：前端兼容保留字段，当前不参与 `rembg` 背景移除

## rembg 离线模型

后端强制使用 `isnet-general-use` 模型，并只从本地加载，不会在运行时下载模型。

开发运行时请放置：

- `services/vectorizer-api/models/rembg/isnet-general-use.onnx`

打包运行时请放置：

- `dist/models/rembg/isnet-general-use.onnx`

模型 MD5 必须是：

- `fc16ebd8b0c10d971d3513d564d01e29`

CPU/GPU 由 `onnxruntime` provider 自动选择：安装 `rembg[cpu]` 时使用 CPU，安装 `rembg[gpu]` 且环境可用时优先 GPU 并回退 CPU。

## `POST /api/v1/vectorize` 示例

用户上传位图：

```json
{
  "source_type": "upload",
  "vector": {
    "preset": "balanced",
    "color_precision": 5,
    "filter_speckle": 6,
    "corner_threshold": 45,
    "length_threshold": 5,
    "layer_difference": 10,
    "scale": 2,
    "evaluate_quality": true,
    "remove_edge_white_background": true,
    "white_value_threshold": 245,
    "white_saturation_threshold": 20
  },
  "image_base64": "data:image/png;base64,....",
  "image_name": "input.png"
}
```

系统生成位图：

```json
{
  "source_type": "generated",
  "vector": {
    "preset": "detailed",
    "color_precision": 6,
    "filter_speckle": 2,
    "corner_threshold": 30,
    "length_threshold": 3,
    "layer_difference": 4,
    "scale": 3,
    "evaluate_quality": true,
    "remove_edge_white_background": true,
    "white_value_threshold": 245,
    "white_saturation_threshold": 20
  },
  "generated_image": {
    "image_base64": "data:image/png;base64,...."
  }
}
```

## 响应

- `png`：SVG 回渲染 PNG 预览（data URL）
- `svg`：标准 SVG 文本
- `metadata`：参数、耗时、文件大小等运行信息

说明：`evaluate_quality` 字段当前仅保留前端兼容，不参与后端评分计算。

## 本地运行

```bash
cd services/vectorizer-api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 打包为 EXE（Windows）

在 `services/vectorizer-api` 目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-backend-exe.ps1
```

打包成功后产物在：

- `services/vectorizer-api/dist/vectorizer-backend.exe`

## 别人怎么用打包好的后端

### 方式 1：命令行启动（推荐）

```powershell
.\vectorizer-backend.exe --host 127.0.0.1 --port 8000
```

### 方式 2：双击脚本启动

双击：

- `services/vectorizer-api/scripts/start-backend.bat`

它会自动启动后端监听 `127.0.0.1:8000`。

### 联调说明

桌面端默认请求 `http://127.0.0.1:8000/api/v1`，因此只要 exe 运行中，前端矢量化功能即可直接调用。
