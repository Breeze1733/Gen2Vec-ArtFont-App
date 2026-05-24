from __future__ import annotations

import base64
import os
import tempfile
import time
from typing import Any
from xml.dom import minidom

import numpy as np
from PIL import Image

try:
    import cairosvg
except Exception:  # pragma: no cover
    cairosvg = None

try:
    import vtracer
except Exception:  # pragma: no cover
    vtracer = None


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

        work_img = transparent_image
        if scale > 1:
            work_img = transparent_image.resize(
                (int(original_width * scale), int(original_height * scale)),
                Image.Resampling.LANCZOS,
            )
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

    metadata = {
        "engine": "vectorizer-api-split-pipeline",
        "params": {
            "preset": params["preset"],
            "color_precision": int(params["cp"]),
            "filter_speckle": int(params["fs"]),
            "corner_threshold": int(params["ct"]),
            "length_threshold": int(params["lt"]),
            "layer_difference": int(params["ld"]),
            "scale": scale,
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
        "quality": {
            "svg_fidelity": svg_fidelity,
        },
    }

    return {
        "svg": formatted_svg_text,
        "preview_png": preview_data_url,
        "metadata": metadata,
    }
