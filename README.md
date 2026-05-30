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
│  ├─ vectorizer-api/           # FR3 智能矢量化后端（FastAPI）
│  └─ txt2img-api/              # 文生图后端（FastAPI）
├─ workflows/                   # 文生图工作流与模型流程配置
├─ packages/                    # 共享包（类型/工具/SDK/UI，预留）
├─ docs/                        # 需求、接口、设计说明（预留）
├─ scripts/                     # 开发/构建/发布脚本（预留）
└─ README.md
```

## 快速启动联调

所有命令在**项目根目录**下执行。

### txt2img-api 文生图后端（端口 9001）

```powershell
cd services/txt2img-api
uv run txt2img-api
```

### 矢量化后端（端口 8000）

```powershell
cd services/vectorizer-api
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 桌面端

```powershell
cd apps/desktop
npm run electron:dev
```

桌面端默认连接 `http://127.0.0.1:8000/api/v1/vectorize`（矢量化），文生图请求默认转发到 `http://127.0.0.1:9001/api/v1/txt2img`。

可通过完整 endpoint 环境变量覆盖：

```powershell
$env:VECTORIZER_BACKEND_URL="http://127.0.0.1:8000/api/v1/vectorize"
$env:TXT2IMG_BACKEND_URL="http://127.0.0.1:9001/api/v1/txt2img"
npm run electron:dev
```