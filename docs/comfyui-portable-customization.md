# ComfyUI 便携包修改清单

本文档记录从一个干净的 ComfyUI 便携包到 Gen2Vec ArtFont 可用状态所需的全部修改，供自动化脚本使用。

**适用场景**：用户已通过 `download-comfyui-engine.ps1` 下载解压了 ComfyUI 引擎，并执行了 `download-models.ps1` 下载了所有模型文件。

---

## 1. 自定义节点安装

### 1.1 comfyui-inspyrenet-rembg

将 `comfyui-inspyrenet-rembg/` 目录放置到：

```
ComfyUI/custom_nodes/comfyui-inspyrenet-rembg/
```

### 1.2 修复 __init__.py（相对导入 → 绝对导入）

**原因**：目录名包含连字符 `-`，ComfyUI 的 `load_custom_node()` 将完整路径作为模块名时，Python 无法解析 `from .xxx import` 形式的相对导入。

**文件**：`comfyui-inspyrenet-rembg/__init__.py`

**修改**：

```diff
-from .Inspyrenet_Rembg import InspyrenetRembg, InspyrenetRembgAdvanced
+import sys
+import os
+sys.path.insert(0, os.path.dirname(__file__))
+from Inspyrenet_Rembg import InspyrenetRembg, InspyrenetRembgAdvanced
```

NODE_CLASS_MAPPINGS 和 NODE_DISPLAY_NAME_MAPPINGS 保持不变。

### 1.3 增强 Inspyrenet_Rembg.py（模型路径指向 models/）

**原因**：默认情况下 `transparent-background` 库将模型下载到 `~/.transparent-background/`，不便统一管理。通过设置环境变量将模型路径指向 ComfyUI 的 `models/inspyrenet/`，便于模型下载脚本统一预置。

**文件**：`comfyui-inspyrenet-rembg/Inspyrenet_Rembg.py`

**修改**：在 `import tqdm` 之后、`# Tensor to PIL` 之前插入：

```python
import os

# 将 Inspyrenet 模型目录指向 ComfyUI/models/inspyrenet/
# 方便模型下载脚本统一管理，用户可预置模型避免首次运行时联网下载
_CUSTOM_NODE_DIR = os.path.dirname(os.path.abspath(__file__))
_COMFYUI_DIR = os.path.dirname(os.path.dirname(_CUSTOM_NODE_DIR))
_INSPYRENET_MODEL_DIR = os.path.join(_COMFYUI_DIR, "models", "inspyrenet")

if "TRANSPARENT_BACKGROUND_FILE_PATH" not in os.environ:
    os.environ["TRANSPARENT_BACKGROUND_FILE_PATH"] = _INSPYRENET_MODEL_DIR
```

## 2. Python 依赖安装

在 `python_embeded/` 中安装 `transparent-background`：

```powershell
.\python_embeded\python.exe -m pip install transparent-background
```

该包及其依赖会自动安装到 `python_embeded/Lib/site-packages/`。

安装的主要包：

| 包 | 版本 |
|---|---|
| transparent-background | 1.3.4 |
| timm | 1.0.27 |
| opencv-python | 4.13+ |
| opencv-python-headless | 4.13+ |
| pymatting | 1.1.15 |
| numba | 0.65+ |
| llvmlite | 0.47+ |
| albumentations | 2.0+ |

## 3. 模型文件预置

### 3.1 路径

```
ComfyUI/models/inspyrenet/.transparent-background/ckpt_base.pth
```

### 3.2 说明

- 文件大小约 170MB
- `transparent-background` 库首次调用 `Remover()` 时，会自动在此目录下创建 `.transparent-background/` 并复制 `config.yaml`
- 如果模型文件已存在且 MD5 正确，则跳过下载
- 模型下载源：GitHub Releases (`https://github.com/plemeri/transparent-background/releases/download/1.2.12/ckpt_base.pth`)
- 如需镜像，首次运行生成的 `config.yaml` 中的 `url` 字段可修改后重新指向镜像地址

### 3.3 目录结构（最终）

```
ComfyUI/models/inspyrenet/
└── .transparent-background/
    ├── config.yaml        # 首次运行自动生成，含下载 URL 和 MD5
    └── ckpt_base.pth      # 预置或首次运行时自动下载
```

## 4. 脚本执行顺序建议

```powershell
# 1. 下载引擎
.\download-comfyui-engine.ps1

# 2. 安装自定义节点文件（拷贝 comfyui-inspyrenet-rembg/ 到 custom_nodes/）

# 3. 应用代码修复（步骤 1.2、1.3）

# 4. 安装 Python 依赖
.\python_embeded\python.exe -m pip install transparent-background

# 5. 下载模型文件（含 ckpt_base.pth）
.\download-models.ps1
```

步骤 2-3 的具体实现由修改脚本负责，本清单作为修改内容的完整记录。
