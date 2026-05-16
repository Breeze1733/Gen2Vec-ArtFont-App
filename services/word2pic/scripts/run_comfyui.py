
from pathlib import Path
import os
import subprocess
import sys

# 激活 uv 环境（假设已在 .venv 下）
def activate_venv():
    project_root = Path(__file__).resolve().parents[1]
    venv_activate = project_root / '.venv' / 'Scripts' / 'activate'
    if not venv_activate.with_suffix('.bat').exists() and not venv_activate.with_suffix('.ps1').exists():
        print("[警告] 未找到虚拟环境 .venv，请先用 uv 创建环境！")
    else:
        print("[提示] 请确保已在 .venv 环境下运行本脚本。")

# ComfyUI 启动脚本路径（fp16加速）
project_root = Path(__file__).resolve().parents[1]
COMFYUI_BAT = os.path.join(
    project_root,
    'ComfyUI_windows_portable_nvidia',
    'ComfyUI_windows_portable',
    'run_nvidia_gpu_fast_fp16_accumulation.bat'
)

if not os.path.exists(COMFYUI_BAT):
    raise FileNotFoundError(f"未找到启动脚本: {COMFYUI_BAT}")

activate_venv()
print(f"启动 ComfyUI: {COMFYUI_BAT}")
subprocess.Popen([COMFYUI_BAT], shell=True)
print("ComfyUI 已尝试启动，请检查命令行窗口或任务管理器。")
