# ComfyUI 便携包 — 下载后修改清单

执行时机：用户已通过以下脚本下载完毕之后：
- `download-comfyui-engine.ps1`（ComfyUI 便携包）
- 节点下载脚本（`comfyui-inspyrenet-rembg` 等自定义节点）
- `download-models.ps1`（模型文件）

| # | 类别 | 操作 | 目标路径 |
|---|------|------|----------|
| 1 | 文件覆盖 | 仓库 `services/txt2img-api/custom_nodes/comfyui-inspyrenet-rembg/__init__.py` → 覆盖便携包 `ComfyUI/custom_nodes/comfyui-inspyrenet-rembg/__init__.py` | 修复带连字符目录名的相对导入失败 |
| 2 | 文件覆盖 | 仓库 `services/txt2img-api/custom_nodes/comfyui-inspyrenet-rembg/Inspyrenet_Rembg.py` → 覆盖便携包 `ComfyUI/custom_nodes/comfyui-inspyrenet-rembg/Inspyrenet_Rembg.py` | 添加模型路径 + numba 缓存环境变量，修正 import 顺序 |
| 3 | pip 安装 | `python_embeded\python.exe -m pip install transparent-background` | 安装 Inspyrenet 所需的 Python 依赖 |
