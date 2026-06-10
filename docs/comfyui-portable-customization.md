# ComfyUI 便携包 — 下载后修改清单

执行时机：用户已通过以下脚本下载完毕之后：
- `download-comfyui-engine.ps1`（ComfyUI 便携包 + ComfyUI-GGUF + ComfyUI-Inspyrenet-Rembg 自定义节点）
- `download-models.ps1`（模型文件）

| # | 类别 | 操作 | 目标路径 |
|---|------|------|----------|
| 1 | 文件覆盖 | 仓库 `services/txt2img-api/custom_nodes/comfyui-inspyrenet-rembg/__init__.py` → 覆盖便携包 `ComfyUI/custom_nodes/comfyui-inspyrenet-rembg/__init__.py` | 修复带连字符目录名的相对导入失败 |
| 2 | 文件覆盖 | 仓库 `services/txt2img-api/custom_nodes/comfyui-inspyrenet-rembg/Inspyrenet_Rembg.py` → 覆盖便携包 `ComfyUI/custom_nodes/comfyui-inspyrenet-rembg/Inspyrenet_Rembg.py` | 添加模型路径 + numba 缓存环境变量，修正 import 顺序 |
| 3 | pip 安装 | `python_embeded\python.exe -m pip install transparent-background gguf protobuf` | transparent-background → InspyrenetRembg 背景移除；gguf + protobuf → ComfyUI-GGUF 加载 Qwen-Image GGUF |

## 不需要手动安装的包

用户在执行步骤 3 的 pip 命令后，`transparent-background` 和 `gguf` 的**传递依赖会被 pip 自动安装**，无需手动逐个列出。以下解释项目开发环境中多出的包从何而来，帮助判断哪些不属于核心管线。

### pip 自动拉取的依赖（用户无需关心）

`pip install transparent-background` 会自动安装以下依赖（含版本号截至 2026-06）：

| 包 | 来自 | 说明 |
|----|------|------|
| `pymatting` | transparent-background | 图像 alpha 抠图 |
| `numba` / `llvmlite` | pymatting | JIT 编译抠图算法（InspyrenetRembg 已含 monkey-patch 解决 MAX_PATH 问题） |
| `albumentations` / `albucore` | transparent-background | 图像增强管线 |
| `opencv-python-headless` (cv2) | transparent-background | 图像处理 |
| `timm` | transparent-background | PyTorch 图像模型库 |
| `easydict` | transparent-background | 配置字典 |
| `gdown` / `wget` | transparent-background | 模型下载（仅首次运行使用，我们通过环境变量 `TRANSPARENT_BACKGROUND_FILE_PATH` 绕过） |
| `simsimd` | albucore/albumentations 加速 | SIMD 向量计算加速 |
| `kornia_rs` | kornia 加速 | 计算机视觉加速 |

`pip install gguf` 的依赖（`numpy`、`pyyaml`、`requests`、`tqdm`）和 `protobuf` 已在 ComfyUI 便携包基础环境中存在或与上述重合。

### 来自 ComfyUI-Manager 的依赖（不需要）

开发环境中的项目 ComfyUI 额外安装了 `ComfyUI-Manager`（交互式节点管理器），引入了约 20 个额外包。**工作流管线完全不使用这些包**，用户无需安装：

| 包 | 说明 |
|----|------|
| `GitPython` / `gitdb` / `smmap` | Git 仓库操作（Manager 用于安装/更新节点） |
| `PyGithub` / `PyJWT` | GitHub API 客户端 |
| `matrix-nio` / `nacl` / `unpaddedbase64` | Matrix 聊天协议（Manager 的通知功能） |
| `cryptography` / `pycryptodome` | 加密（Matrix 等依赖） |
| `beautifulsoup4` / `soupsieve` / `chardet` | HTML 解析 / 编码检测（Manager 网页抓取） |
| `jsonschema` / `referencing` / `rpds` | JSON Schema 校验 |
| `h2` / `hpack` / `hyperframe` | HTTP/2 协议 |
| `python_socks` / `aiohttp_socks` / `PySocks` | SOCKS 代理 |
| `toml` | TOML 配置文件解析 |

### 其他开发便利包（不需要）

| 包 | 说明 |
|----|------|
| `uv` | Python 包管理器（CI/开发使用，运行时不需要） |
| `stringzilla` | 字符串处理加速（某依赖的可选加速，不影响功能） |
| `aiofiles` | 异步文件 IO（某依赖的可选加速） |

### 自定义节点：哪些是管线必需的

`download-comfyui-engine.ps1` 仅安装管线必需的两个自定义节点：

| 节点 | 用途 | 工作流 |
|------|------|--------|
| `ComfyUI-GGUF` | 加载 Qwen-Image GGUF 量化模型 | `qwen_image_2512_gguf` |
| `comfyui-inspyrenet-rembg` | Inspyrenet 背景移除 | 全部 3 个工作流 |

以下节点仅存在于开发环境的项目 ComfyUI 中，**不被工作流管线使用，也不会被下载脚本安装**：

- `ComfyUI-Manager` — 交互式节点管理器，运行时不需要
- `rgthree-comfy` — 通用工具节点集，工作流未引用
- `rembg-comfyui-node-better` — 另一套基于 `rembg` 的背景移除节点，工作流未引用
