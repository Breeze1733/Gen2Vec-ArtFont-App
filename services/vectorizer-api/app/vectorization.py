from __future__ import annotations

import base64
import os
import sys
import tempfile
import time
from typing import Any
from xml.dom import minidom

import numpy as np
from PIL import Image

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

if sys.platform == "win32":
    _venv_scripts = os.path.join(sys.prefix, "Scripts")
    if os.path.isdir(_venv_scripts):
        os.add_dll_directory(_venv_scripts)

try:
    import cairosvg
except Exception:  # pragma: no cover
    cairosvg = None

try:
    import vtracer
except Exception:  # pragma: no cover
    vtracer = None


PRESET_CONFIG: dict[str, dict[str, int]] = {
    "clean": {"cp": 2, "fs": 48, "ct": 120, "lt": 30, "ld": 38, "scale": 2},
    "balanced": {"cp": 4, "fs": 18, "ct": 70, "lt": 12, "ld": 20, "scale": 2},
    "detailed": {"cp": 6, "fs": 2, "ct": 30, "lt": 3, "ld": 4, "scale": 3},
    "ultra": {"cp": 8, "fs": 1, "ct": 20, "lt": 2, "ld": 2, "scale": 3},
}

TRACE_CLEANUP_CONFIG: dict[str, dict[str, int | bool]] = {
    "clean": {
        "alpha_floor": 48,
        "min_area_divisor": 1500,
        "morph": 2,
        "median": True,
        "solid_alpha": True,
        "smooth_mask": True,
        "snap_near_white": True,
    },
    "balanced": {
        "alpha_floor": 28,
        "min_area_divisor": 3600,
        "morph": 1,
        "median": True,
        "solid_alpha": True,
        "smooth_mask": True,
        "snap_near_white": True,
    },
    "detailed": {
        "alpha_floor": 10,
        "min_area_divisor": 12000,
        "morph": 0,
        "median": True,
        "solid_alpha": False,
        "smooth_mask": False,
        "snap_near_white": False,
    },
    "ultra": {
        "alpha_floor": 4,
        "min_area_divisor": 24000,
        "morph": 0,
        "median": False,
        "solid_alpha": False,
        "smooth_mask": False,
        "snap_near_white": False,
    },
}


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


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


def _png_bytes_to_data_url(png_bytes: bytes) -> str:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _svg_to_png_bytes(svg_text: str, width: int | None = None) -> bytes:
    if cairosvg is None:
        raise RuntimeError("cairosvg is not installed. Cannot generate preview PNG.")
    return cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), output_width=width)


def _pretty_svg_text(svg_text: str) -> str:
    try:
        parsed = minidom.parseString(svg_text.encode("utf-8"))
        pretty = parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
        lines = [line for line in pretty.splitlines() if line.strip()]
        return "\n".join(lines) + "\n"
    except Exception:
        return svg_text


def _calculate_svg_fidelity(source_img: Image.Image, preview_png_bytes: bytes) -> float | None:
    try:
        from io import BytesIO

        source = source_img.convert("RGBA")
        preview = Image.open(BytesIO(preview_png_bytes)).convert("RGBA")
        if preview.size != source.size:
            preview = preview.resize(source.size, Image.Resampling.LANCZOS)

        src = np.array(source, dtype=np.float32)
        out = np.array(preview, dtype=np.float32)

        diff = src - out
        rgba_rmse = float(np.sqrt(np.mean(np.square(diff))))
        return round(max(0.0, 1.0 - (rgba_rmse / 255.0)) * 100.0, 1)
    except Exception:
        return None


def _remove_small_alpha_components(alpha: np.ndarray, min_area: int) -> np.ndarray:
    if cv2 is None or min_area <= 1:
        return alpha

    mask = (alpha > 0).astype(np.uint8)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if num_labels <= 1:
        return alpha

    keep = np.zeros(mask.shape, dtype=bool)
    for label in range(1, num_labels):
        if int(stats[label, cv2.CC_STAT_AREA]) >= min_area:
            keep |= labels == label

    cleaned = alpha.copy()
    cleaned[~keep] = 0
    return cleaned


def _smooth_binary_alpha(alpha: np.ndarray, alpha_floor: int) -> np.ndarray:
    if cv2 is None:
        return alpha

    mask = (alpha > 0).astype(np.uint8) * 255
    mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=1.35, sigmaY=1.35)
    _, mask = cv2.threshold(mask, 128, 255, cv2.THRESH_BINARY)

    # A second, smaller pass rounds stair-stepped edges without expanding the glyph too far.
    mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=0.55, sigmaY=0.55)
    _, mask = cv2.threshold(mask, 128, 255, cv2.THRESH_BINARY)

    out = alpha.copy()
    out[mask == 0] = 0
    out[(mask > 0) & (out < alpha_floor)] = alpha_floor
    return out


def _prepare_trace_input(img: Image.Image, params: dict[str, int | str]) -> Image.Image:
    rgba = img.convert("RGBA")
    arr = np.array(rgba)
    alpha = arr[:, :, 3].copy()
    preset = str(params["preset"])
    cleanup = TRACE_CLEANUP_CONFIG.get(preset, TRACE_CLEANUP_CONFIG["balanced"])

    alpha_floor = int(cleanup["alpha_floor"])
    alpha[alpha < alpha_floor] = 0

    if cv2 is not None:
        if bool(cleanup["median"]):
            alpha = cv2.medianBlur(alpha, 3)

        morph_iterations = int(cleanup["morph"])
        if morph_iterations > 0:
            kernel = np.ones((3, 3), np.uint8)
            mask = (alpha > 0).astype(np.uint8) * 255
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=morph_iterations)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=morph_iterations)
            alpha[mask == 0] = 0
            alpha[(mask > 0) & (alpha < alpha_floor)] = alpha_floor

        rgb = arr[:, :, :3]
        rgb = cv2.bilateralFilter(rgb, d=5, sigmaColor=32, sigmaSpace=24)
        arr[:, :, :3] = rgb

    min_area = max(2, int((rgba.width * rgba.height) / int(cleanup["min_area_divisor"])))
    alpha = _remove_small_alpha_components(alpha, min_area)

    if bool(cleanup["smooth_mask"]):
        alpha = _smooth_binary_alpha(alpha, alpha_floor)

    if bool(cleanup["solid_alpha"]):
        alpha[alpha > 0] = 255

    arr[:, :, 3] = alpha
    arr[alpha == 0, :3] = 255

    if bool(cleanup["snap_near_white"]) and cv2 is not None:
        visible = alpha > 0
        hsv = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2HSV)
        near_white = visible & (hsv[:, :, 1] <= 34) & (hsv[:, :, 2] >= 220)
        arr[near_white, :3] = 245

    return Image.fromarray(arr, mode="RGBA")


def vectorize_image(transparent_image: Image.Image, vector: dict[str, Any]) -> dict[str, Any]:
    if vtracer is None:
        raise RuntimeError("vtracer is not installed. Please install dependencies first.")

    t0 = time.perf_counter()
    params = _resolve_vector_params(vector)

    original_width, original_height = transparent_image.size

    scale = int(params["scale"])
    if original_width > 3000:
        scale = max(1, scale // 2)

    with tempfile.TemporaryDirectory(prefix="vectorize-api-") as tmp:
        input_png_path = os.path.join(tmp, "input.png")
        output_svg_path = os.path.join(tmp, "output.svg")

        work_img = _prepare_trace_input(transparent_image, params)
        if scale > 1:
            work_img = work_img.resize(
                (int(original_width * scale), int(original_height * scale)),
                Image.Resampling.LANCZOS,
            )
            work_img = _prepare_trace_input(work_img, params)
        work_img.save(input_png_path, "PNG")

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
        preview_png_bytes = _svg_to_png_bytes(svg_text, width=original_width)
        formatted_svg_text = _pretty_svg_text(svg_text)
        svg_fidelity = _calculate_svg_fidelity(transparent_image, preview_png_bytes)

    preview_data_url = _png_bytes_to_data_url(preview_png_bytes)
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    # 统一元数据格式：所有模式（单条/批量/矢量化）共用同一结构。
    # generation 字段由调用方按需填充（矢量化模式留空）。
    # source / preprocess / created_at 由 main.py 补充。
    metadata = {
        "engine": "vectorizer-api-split-pipeline",
        "source_type": "",
        "source_channel": "",
        "source_image_name": "",
        "generation": {
            "text": "",
            "prompt": "",
            "negative": "",
            "resolution": "",
            "seed": 0,
        },
        "params": {
            "preset": params["preset"],
            "color_precision": int(params["cp"]),
            "filter_speckle": int(params["fs"]),
            "corner_threshold": int(params["ct"]),
            "length_threshold": int(params["lt"]),
            "layer_difference": int(params["ld"]),
            "scale": scale,
            "trace_cleanup": {
                "alpha_floor": int(TRACE_CLEANUP_CONFIG[str(params["preset"])]["alpha_floor"]),
                "small_component_min_area": max(
                    2,
                    int(
                        (work_img.width * work_img.height)
                        / int(TRACE_CLEANUP_CONFIG[str(params["preset"])]["min_area_divisor"])
                    ),
                ),
            },
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
        "preprocess": {
            "png_transparency": None,
        },
        "quality": {
            "svg_fidelity": svg_fidelity,
        },
        "created_at": "",
    }

    return {
        "svg": formatted_svg_text,
        "preview_png": preview_data_url,
        "metadata": metadata,
    }
