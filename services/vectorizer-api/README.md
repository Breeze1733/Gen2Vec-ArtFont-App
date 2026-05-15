# FR3 Intelligent Vectorization API

基于需求文档“基于开源文生图模型的矢量艺术字生成应用”的 FR3 模块实现，提供 Python HTTP REST API。

## 功能

- 接收透明 PNG（或 JPG）艺术字位图 + 前端矢量化参数
- 使用 `OpenCV + scikit-image` 做图像清洗和颜色分层聚类
- 按颜色层调用 `vtracer` 执行平滑路径追踪
- 使用 `svgwrite` 组装标准 SVG DOM（含 `viewBox`、分组）
- 回渲染 SVG 得到 PNG 预览，并计算轮廓偏差指标（IoU + Chamfer）

## 接口

- `GET /healthz`
- `POST /api/v1/generate`

请求体示例（`mode=vectorize`，用户上传）：

```json
{
  "mode": "vectorize",
  "source_type": "upload",
  "resolution": "1024 x 1024",
  "vector": {
    "smooth": 6,
    "threshold": 42,
    "colors": 8
  },
  "image_base64": "data:image/png;base64,....",
  "image_name": "input.png"
}
```

请求体示例（`mode=vectorize`，系统生成位图）：

```json
{
  "mode": "vectorize",
  "source_type": "generated",
  "vector": {
    "smooth": 6,
    "threshold": 42,
    "colors": 8
  },
  "generated_image": {
    "image_base64": "data:image/png;base64,...."
  }
}
```

`generated_image` 目前支持：
- `image_base64`
- `file_path`
- `artifact_id`（字段已预留，解析器待接入生成模块资产仓库）

响应体：

- `png`: `data:image/png;base64,...`（SVG 回渲染预览）
- `svg`: 标准 SVG 文本
- `metadata`: 分层信息、参数、质量指标

## 本地运行

```bash
cd services/vectorizer-api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## 与桌面端联调

PowerShell:

```powershell
cd apps/desktop
npm install
npm run electron:dev
```
