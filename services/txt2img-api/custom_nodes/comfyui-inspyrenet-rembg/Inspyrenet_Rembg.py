import os
import numpy as np
import torch
from PIL import Image

# ═══════════════════════════════════════════════════════════════════
# 环境变量 + numba monkey-patch 必须在 import transparent_background
# 之前执行，否则 numba 往 site-packages __pycache__ 写内联缓存时
# 路径超 Windows MAX_PATH (260) → FileNotFoundError
# ═══════════════════════════════════════════════════════════════════
_CUSTOM_NODE_DIR = os.path.dirname(os.path.abspath(__file__))
_COMFYUI_DIR = os.path.dirname(os.path.dirname(_CUSTOM_NODE_DIR))
_INSPYRENET_MODEL_DIR = os.path.join(_COMFYUI_DIR, "models", "inspyrenet")

# 模型目录（避免首次运行从 GitHub 下载）
if "TRANSPARENT_BACKGROUND_FILE_PATH" not in os.environ:
    os.environ["TRANSPARENT_BACKGROUND_FILE_PATH"] = _INSPYRENET_MODEL_DIR

# numba 全局缓存目录（仅影响显式 API 缓存，不影响 pymatting 内联缓存）
if "NUMBA_CACHE_DIR" not in os.environ:
    os.environ["NUMBA_CACHE_DIR"] = os.path.join(_INSPYRENET_MODEL_DIR, ".numba_cache")

# ══ monkey-patch: 禁用 numba 内联文件缓存 ══
# pymatting 源码中 @njit(cache=True) 会往源码旁 __pycache__/ 写缓存，
# 该路径极易超 Windows MAX_PATH。NUMBA_CACHE_DIR 无法重定向内联缓存，
# 因此必须在 import 前将 numba.njit/jit 的 cache 参数强制改为 False。
# 副作用：首次 import 时 JIT 编译结果不持久化，下次进程重启重新编译。
try:
    import numba as _numba
    _orig_njit = _numba.njit
    _orig_jit = _numba.jit

    def _njit_nocache(*args, **kwargs):
        kwargs.pop("cache", None)
        return _orig_njit(*args, **kwargs, cache=False)

    def _jit_nocache(*args, **kwargs):
        kwargs.pop("cache", None)
        return _orig_jit(*args, **kwargs, cache=False)

    _numba.njit = _njit_nocache
    _numba.jit = _jit_nocache
except Exception:
    pass  # numba 不可用时静默跳过，不影响 transparent_background 降级

from transparent_background import Remover
from tqdm import tqdm


# Tensor to PIL
def tensor2pil(image):
    return Image.fromarray(np.clip(255. * image.cpu().numpy().squeeze(), 0, 255).astype(np.uint8))

# Convert PIL to Tensor
def pil2tensor(image):
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)

class InspyrenetRembg:
    def __init__(self):
        pass
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "torchscript_jit": (["default", "on"],)
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    FUNCTION = "remove_background"
    CATEGORY = "image"

    def remove_background(self, image, torchscript_jit):
        if (torchscript_jit == "default"):
            remover = Remover()
        else:
            remover = Remover(jit=True)
        img_list = []
        for img in tqdm(image, "Inspyrenet Rembg"):
            mid = remover.process(tensor2pil(img), type='rgba')
            out =  pil2tensor(mid)
            img_list.append(out)
        img_stack = torch.cat(img_list, dim=0)
        mask = img_stack[:, :, :, 3]
        return (img_stack, mask)
        
class InspyrenetRembgAdvanced:
    def __init__(self):
        pass
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01}),
                "torchscript_jit": (["default", "on"],)
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    FUNCTION = "remove_background"
    CATEGORY = "image"

    def remove_background(self, image, torchscript_jit, threshold):
        if (torchscript_jit == "default"):
            remover = Remover()
        else:
            remover = Remover(jit=True)
        img_list = []
        for img in tqdm(image, "Inspyrenet Rembg"):
            mid = remover.process(tensor2pil(img), type='rgba', threshold=threshold)
            out =  pil2tensor(mid)
            img_list.append(out)
        img_stack = torch.cat(img_list, dim=0)
        mask = img_stack[:, :, :, 3]
        return (img_stack, mask)