# Vectorizer API

该服务仅负责“位图 -> 矢量图（SVG）”转换，不包含普通艺术字位图生成逻辑。

## 接口

- `GET /healthz`
- `POST /api/v1/vectorize`（已实现）
- `POST /api/v1/generate`（预留，占位返回 501）

## `POST /api/v1/vectorize`

请求示例（用户上传位图）：

```json
{
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

请求示例（系统生成位图）：

```json
{
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

`generated_image` 当前支持：

- `image_base64`
- `file_path`
- `artifact_id`（字段预留，解析器待接入）

响应字段：

- `png`：SVG 回渲染 PNG 预览（data URL）
- `svg`：标准 SVG 文本
- `metadata`：参数、分层信息、输入来源、质量指标

## 本地运行

```bash
cd services/vectorizer-api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
