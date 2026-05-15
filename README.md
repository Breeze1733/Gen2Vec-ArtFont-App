# 矢量艺术字生成应用

基于开源文生图模型与计算机视觉算法的本地化艺术字工具仓库。  
当前已包含：

- Electron + Vue 桌面端（单条生成 / 批量生成 / 图片矢量化界面）
- Python FR3 智能矢量化后端（HTTP REST API）

## 项目结构

```text
Development-Training/
├─ apps/
│  └─ desktop/                  # Electron + Vue 桌面端
├─ services/
│  └─ vectorizer-api/           # FR3 智能矢量化后端（FastAPI）
├─ workflows/                   # 文生图工作流与模型流程配置
├─ packages/                    # 共享包（类型/工具/SDK/UI，预留）
├─ docs/                        # 需求、接口、设计说明（预留）
├─ scripts/                     # 开发/构建/发布脚本（预留）
└─ README.md
```

## FR3 智能矢量化引擎（已实现）

后端路径：`services/vectorizer-api`

核心能力：

- 输入透明 PNG/JPG 艺术字位图 + 矢量化控制参数
- `OpenCV + scikit-image` 做图像清洗与颜色分层聚类
- 按层调用 `vtracer` 进行路径追踪与平滑拟合
- 使用 `svgwrite` 组装标准 SVG（含 `viewBox` 和分组）
- 回渲染 PNG 预览并输出轮廓偏差指标

输入来源已支持两类：

- `source_type=upload`：用户上传位图
- `source_type=generated`：系统生成位图（支持 `image_base64` / `file_path`；`artifact_id` 已预留）

接口：

- `GET /healthz`
- `POST /api/v1/generate`

详细接口说明见 [services/vectorizer-api/README.md](./services/vectorizer-api/README.md)。

## 快速启动联调

启动后端监听端口

```powershell
cd services/vectorizer-api
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

启动桌面版前端

```powershell
cd apps/desktop
npm install
npm run electron:dev
```

说明：
- 桌面端默认直连 `http://127.0.0.1:8000/api/v1/generate`
- 如需切换后端地址，可再设置 `ART_TEXT_BACKEND_URL` 覆盖默认值

## 当前状态

- `single` / `batch` 在后端仍为 mock 返回（用于前端联调）
- `vectorize` 已接入真实 FR3 矢量化流水线
- “系统生成位图 -> 资产ID解析”通道字段已预留，解析器待接入生成模块

## 目录职责约定

- `docs`：产品文档、需求文档、API 文档、联调说明
- `packages`：跨应用复用的共享代码（SDK、类型、工具）
- `scripts`：一键启动、构建、发布、批处理等自动化脚本
