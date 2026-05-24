from __future__ import annotations

import base64
import hashlib
import importlib
import io
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

import cv2

REMBG_MODEL_NAME = "isnet-general-use"
REMBG_MODEL_FILENAME = f"{REMBG_MODEL_NAME}.onnx"
REMBG_MODEL_MD5 = "fc16ebd8b0c10d971d3513d564d01e29"

_REMBG_REMOVE = None
_REMBG_NEW_SESSION = None
_REMBG_SESSION = None
_REMBG_MODEL_CHECKED = False


def decode_base64_image(data: str) -> bytes:
    data = data.strip()
    if data.startswith("data:"):
        _, payload = data.split(",", 1)
    else:
        payload = data
    return base64.b64decode(payload)


def image_bytes_to_pil(image_bytes: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        return img
    except Exception as exc:
        raise ValueError("Cannot decode image bytes. Please upload a valid PNG/JPG.") from exc


def pil_to_data_url(img: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    mime = "image/png" if fmt.upper() == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{b64}"


def pil_to_rgb_np(img: Image.Image) -> np.ndarray:
    if img.mode != "RGB":
        img = img.convert("RGB")
    return np.array(img)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _rembg_model_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "models" / "rembg"
    return Path(__file__).resolve().parents[1] / "models" / "rembg"


def _rembg_model_path() -> Path:
    return _rembg_model_dir() / REMBG_MODEL_FILENAME


def _file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_local_rembg_model() -> Path:
    global _REMBG_MODEL_CHECKED

    model_path = _rembg_model_path()
    if not model_path.is_file():
        raise RuntimeError(
            f"Offline rembg model not found: {model_path}. "
            f"Place {REMBG_MODEL_FILENAME} in {_rembg_model_dir()} before starting vectorizer-api."
        )
    if not _REMBG_MODEL_CHECKED:
        actual_md5 = _file_md5(model_path)
        if actual_md5.lower() != REMBG_MODEL_MD5:
            raise RuntimeError(
                f"Offline rembg model checksum mismatch: {model_path}. "
                f"Expected md5 {REMBG_MODEL_MD5}, got {actual_md5}."
            )
        _REMBG_MODEL_CHECKED = True
    return model_path


def _load_rembg():
    global _REMBG_REMOVE, _REMBG_NEW_SESSION

    if _REMBG_REMOVE is not None and _REMBG_NEW_SESSION is not None:
        return _REMBG_REMOVE, _REMBG_NEW_SESSION

    try:
        importlib.import_module("onnxruntime")
    except Exception as exc:
        raise RuntimeError(
            'onnxruntime is not installed. Please install CPU support with "pip install rembg[cpu]".'
        ) from exc

    try:
        rembg_module = importlib.import_module("rembg")
    except Exception as exc:
        raise RuntimeError(
            'rembg is not available. Please install backend dependencies with "pip install -r requirements.txt".'
        ) from exc

    _REMBG_REMOVE = getattr(rembg_module, "remove")
    _REMBG_NEW_SESSION = getattr(rembg_module, "new_session")
    return _REMBG_REMOVE, _REMBG_NEW_SESSION


def _get_rembg_session():
    global _REMBG_SESSION

    if _REMBG_SESSION is None:
        model_path = _ensure_local_rembg_model()
        os.environ["U2NET_HOME"] = str(model_path.parent)
        _, new_session = _load_rembg()
        try:
            _REMBG_SESSION = new_session(REMBG_MODEL_NAME)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to initialize rembg with local {REMBG_MODEL_NAME} model. "
                'Install CPU support with "pip install rembg[cpu]" or GPU support with "pip install rembg[gpu]".'
            ) from exc
    return _REMBG_SESSION


def remove_background_with_rembg(img: Image.Image) -> Image.Image:
    source = img.convert("RGBA")
    session = _get_rembg_session()
    remove, _ = _load_rembg()
    try:
        result = remove(
            source,
            session=session,
            post_process_mask=True,
            alpha_matting=True,
            alpha_matting_foreground_threshold=240,
            alpha_matting_background_threshold=10,
            alpha_matting_erode_size=10,
        )
    except RuntimeError:
        raise
    except Exception:
        try:
            result = remove(source, session=session, post_process_mask=True)
        except Exception as exc:
            raise RuntimeError(f"Failed to remove image background with rembg: {exc}") from exc

    if isinstance(result, Image.Image):
        return result.convert("RGBA")
    if isinstance(result, bytes):
        return image_bytes_to_pil(result).convert("RGBA")
    raise RuntimeError("rembg returned an unsupported image type.")


def remove_edge_connected_white(
    img: Image.Image,
    white_value_threshold: int = 245,
    white_saturation_threshold: int = 20,
) -> Image.Image:
    rgba = img.convert("RGBA")
    arr = np.array(rgba)
    rgb = arr[:, :, :3]

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    sat = hsv[:, :, 1]
    val = hsv[:, :, 2]

    white_mask = (val >= white_value_threshold) & (sat <= white_saturation_threshold)
    if not np.any(white_mask):
        return rgba

    white_u8 = (white_mask.astype(np.uint8)) * 255
    num_labels, labels = cv2.connectedComponents(white_u8)
    if num_labels <= 1:
        return rgba

    border_labels: set[int] = set()
    border_labels.update(np.unique(labels[0, :]).tolist())
    border_labels.update(np.unique(labels[-1, :]).tolist())
    border_labels.update(np.unique(labels[:, 0]).tolist())
    border_labels.update(np.unique(labels[:, -1]).tolist())
    border_labels.discard(0)
    if not border_labels:
        return rgba

    edge_bg_mask = np.isin(labels, list(border_labels))
    out = arr.copy()
    out[edge_bg_mask, 3] = 0
    return Image.fromarray(out, mode="RGBA")


def denoise_preserve_edges(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    arr = np.array(rgba)
    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]

    filtered = cv2.bilateralFilter(rgb, d=5, sigmaColor=40, sigmaSpace=40)
    merged = np.dstack([filtered, alpha])
    return Image.fromarray(merged, mode="RGBA")


def crop_to_subject(img: Image.Image, alpha_threshold: int = 8, padding: int = 8) -> Image.Image:
    rgba = img.convert("RGBA")
    arr = np.array(rgba)
    alpha = arr[:, :, 3]
    ys, xs = np.where(alpha > alpha_threshold)
    if len(xs) == 0 or len(ys) == 0:
        return rgba

    left = max(0, int(xs.min()) - padding)
    top = max(0, int(ys.min()) - padding)
    right = min(rgba.width, int(xs.max()) + padding + 1)
    bottom = min(rgba.height, int(ys.max()) + padding + 1)
    return rgba.crop((left, top, right, bottom))


def preserve_antialias_edges(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    arr = np.array(rgba)
    alpha = arr[:, :, 3]
    soft_alpha = cv2.GaussianBlur(alpha, (0, 0), sigmaX=0.6, sigmaY=0.6)
    arr[:, :, 3] = np.maximum(alpha, soft_alpha).astype(np.uint8)
    return Image.fromarray(arr, mode="RGBA")


def quantize_colors(img: Image.Image, color_count: int) -> Image.Image:
    rgba = img.convert("RGBA")
    rgb = rgba.convert("RGB")
    quantized = rgb.quantize(colors=max(2, min(64, color_count)), method=Image.MEDIANCUT)
    rgb_q = quantized.convert("RGB")
    out = Image.new("RGBA", rgba.size)
    out.paste(rgb_q, (0, 0))
    out.putalpha(rgba.getchannel("A"))
    return out


def calculate_png_transparency(img: Image.Image) -> float:
    rgba = img.convert("RGBA")
    alpha = np.array(rgba.getchannel("A"), dtype=np.uint8)
    if alpha.size == 0:
        return 0.0
    return round((1.0 - (float(np.mean(alpha)) / 255.0)) * 100.0, 1)


def preprocess_image(image_bytes: bytes, vector: dict[str, Any]) -> dict[str, Any]:
    img = image_bytes_to_pil(image_bytes)

    remove_bg = bool(vector.get("remove_edge_white_background", True))
    color_precision = max(2, min(64, _safe_int(vector.get("color_precision"), 8)))

    if remove_bg:
        img = remove_background_with_rembg(img)
    else:
        img = img.convert("RGBA")

    img = denoise_preserve_edges(img)
    img = preserve_antialias_edges(img)
    img = crop_to_subject(img)
    img = quantize_colors(img, color_precision)
    png_transparency = calculate_png_transparency(img)

    return {
        "transparent_image": img,
        "transparent_png": pil_to_data_url(img, fmt="PNG"),
        "size": {"width": img.width, "height": img.height},
        "png_transparency": png_transparency,
    }
