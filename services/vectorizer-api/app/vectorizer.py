from __future__ import annotations

import base64
import io
import os
import tempfile
import time
from typing import Any

import cv2
import numpy as np
from PIL import Image
from skimage.metrics import peak_signal_noise_ratio as psnr
from skimage.metrics import structural_similarity as ssim

try:
    import cairosvg
except Exception:  # pragma: no cover
    cairosvg = None

try:
    import vtracer
except Exception:  # pragma: no cover
    vtracer = None


# Fully aligned with app.py preset idea.
PRESET_CONFIG: dict[str, dict[str, int]] = {
    "clean": {"cp": 3, "fs": 15, "ct": 60, "lt": 12, "ld": 20, "scale": 2},
    "balanced": {"cp": 5, "fs": 6, "ct": 45, "lt": 5, "ld": 10, "scale": 2},
    "detailed": {"cp": 6, "fs": 2, "ct": 30, "lt": 3, "ld": 4, "scale": 3},
    "ultra": {"cp": 8, "fs": 1, "ct": 20, "lt": 2, "ld": 2, "scale": 3},
}


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def decode_base64_image(data: str) -> bytes:
    data = data.strip()
    if data.startswith("data:"):
        _, payload = data.split(",", 1)
    else:
        payload = data
    return base64.b64decode(payload)


def _resolve_vector_params(vector: dict[str, Any]) -> dict[str, int | str]:
    preset = str(vector.get("preset", "balanced")).lower()
    if preset not in PRESET_CONFIG:
        preset = "balanced"

    defaults = PRESET_CONFIG[preset]
    cp = _safe_int(vector.get("color_precision"), defaults["cp"])
    fs = _safe_int(vector.get("filter_speckle"), defaults["fs"])
    ct = _safe_int(vector.get("corner_threshold"), defaults["ct"])
    lt = _safe_int(vector.get("length_threshold"), defaults["lt"])
    ld = _safe_int(vector.get("layer_difference"), defaults["ld"])
    scale = _safe_int(vector.get("scale"), defaults["scale"])

    return {
        "preset": preset,
        "cp": max(1, min(8, cp)),
        "fs": max(0, min(64, fs)),
        "ct": max(1, min(180, ct)),
        "lt": max(1, min(64, lt)),
        "ld": max(1, min(64, ld)),
        "scale": max(1, min(4, scale)),
    }


def _pil_open_from_bytes(image_bytes: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
        return img
    except Exception as exc:
        raise ValueError("Cannot decode image bytes. Please upload a valid PNG/JPG.") from exc


def _pil_to_rgb_np(img: Image.Image) -> np.ndarray:
    if img.mode != "RGB":
        img = img.convert("RGB")
    return np.array(img)


def _svg_to_png_bytes(svg_text: str, width: int | None = None) -> bytes:
    if cairosvg is None:
        raise RuntimeError("cairosvg is not installed. Cannot generate preview PNG.")
    return cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), output_width=width)


def _png_bytes_to_data_url(png_bytes: bytes) -> str:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _compute_quality_metrics(original_rgb: np.ndarray, vector_rgb: np.ndarray) -> dict[str, float]:
    if vector_rgb.shape != original_rgb.shape:
        vector_rgb = cv2.resize(vector_rgb, (original_rgb.shape[1], original_rgb.shape[0]), interpolation=cv2.INTER_AREA)

    results: dict[str, float] = {}
    try:
        try:
            results["ssim"] = float(ssim(original_rgb, vector_rgb, channel_axis=2, data_range=255))
        except TypeError:
            results["ssim"] = float(ssim(original_rgb, vector_rgb, multichannel=True, data_range=255))
    except Exception:
        results["ssim"] = 0.0

    try:
        results["psnr"] = float(psnr(original_rgb, vector_rgb, data_range=255))
    except Exception:
        results["psnr"] = 0.0

    try:
        results["mse"] = float(np.mean((original_rgb.astype(float) - vector_rgb.astype(float)) ** 2))
    except Exception:
        results["mse"] = float("inf")

    ssim_val = results.get("ssim", 0.0)
    psnr_val = results.get("psnr", 0.0)
    if ssim_val >= 0.94:
        score = ssim_val * 100.0
    else:
        score = ssim_val * 60.0 + min(psnr_val * 2.5, 25.0)
    results["score"] = round(max(0.0, min(100.0, score)), 4)
    return results


def vectorize_art_text(image_bytes: bytes, vector: dict[str, Any]) -> dict[str, Any]:
    if vtracer is None:
        raise RuntimeError("vtracer is not installed. Please install dependencies first.")

    t0 = time.perf_counter()
    params = _resolve_vector_params(vector)
    evaluate_quality = bool(vector.get("evaluate_quality", True))

    # 1) PIL decode, aligned with app.py.
    original_img = _pil_open_from_bytes(image_bytes)
    original_width, original_height = original_img.size
    original_rgb = _pil_to_rgb_np(original_img)

    # 2) Preset-driven scale strategy, aligned with app.py.
    scale = int(params["scale"])
    if original_width > 3000:
        scale = max(1, scale // 2)

    with tempfile.TemporaryDirectory(prefix="vectorize-api-") as tmp:
        input_png_path = os.path.join(tmp, "input.png")
        output_svg_path = os.path.join(tmp, "output.svg")

        work_img = original_img
        if scale > 1:
            new_size = (int(original_width * scale), int(original_height * scale))
            work_img = original_img.resize(new_size, Image.Resampling.LANCZOS)
        work_img.save(input_png_path, "PNG")

        # 3) vtracer conversion, same parameter semantics as app.py.
        if hasattr(vtracer, "convert_image_to_svg_py"):
            vtracer.convert_image_to_svg_py(
                input_png_path,
                output_svg_path,
                colormode="color",
                hierarchical="stacked",
                mode="spline",
                filter_speckle=int(params["fs"]),
                color_precision=int(params["cp"]),
                layer_difference=int(params["ld"]),
                corner_threshold=int(params["ct"]),
                length_threshold=int(params["lt"]),
                max_iterations=10,
                splice_threshold=45,
                path_precision=4,
            )
        elif hasattr(vtracer, "convert_image_to_svg"):
            vtracer.convert_image_to_svg(
                input_path=input_png_path,
                output_path=output_svg_path,
                colormode="color",
                hierarchical="stacked",
                mode="spline",
                filter_speckle=int(params["fs"]),
                color_precision=int(params["cp"]),
                layer_difference=int(params["ld"]),
                corner_threshold=int(params["ct"]),
                length_threshold=int(params["lt"]),
                max_iterations=10,
                splice_threshold=45,
                path_precision=4,
            )
        else:
            raise RuntimeError("No supported vtracer conversion function found in current binding.")

        with open(output_svg_path, "r", encoding="utf-8") as f:
            svg_text = f.read()
        svg_size_kb = round(os.path.getsize(output_svg_path) / 1024.0, 3)

        # 4) Render SVG preview PNG and evaluate.
        preview_png_bytes = _svg_to_png_bytes(svg_text, width=original_width)

    preview_data_url = _png_bytes_to_data_url(preview_png_bytes)
    preview_bgr = cv2.imdecode(np.frombuffer(preview_png_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if preview_bgr is None:
        raise RuntimeError("Failed to decode rendered preview PNG.")
    preview_rgb = cv2.cvtColor(preview_bgr, cv2.COLOR_BGR2RGB)

    quality = _compute_quality_metrics(original_rgb, preview_rgb) if evaluate_quality else {}
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    metadata = {
        "engine": "vectorizer-api-app-py-replica",
        "params": {
            "preset": params["preset"],
            "color_precision": int(params["cp"]),
            "filter_speckle": int(params["fs"]),
            "corner_threshold": int(params["ct"]),
            "length_threshold": int(params["lt"]),
            "layer_difference": int(params["ld"]),
            "scale": scale,
            "evaluate_quality": evaluate_quality,
        },
        "canvas": {
            "width": int(original_width),
            "height": int(original_height),
            "viewBox": f"0 0 {int(original_width)} {int(original_height)}",
        },
        "stats": {
            "elapsed_ms": elapsed_ms,
            "svg_size_kb": svg_size_kb,
            "preview_png_size_kb": round(len(preview_png_bytes) / 1024.0, 3),
        },
        "quality": quality,
    }
    return {"png": preview_data_url, "svg": svg_text, "metadata": metadata}
