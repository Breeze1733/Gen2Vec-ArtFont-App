from __future__ import annotations

import base64
import math
import os
import tempfile
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree as ET

import cv2
import numpy as np
import svgwrite
from skimage import morphology

try:
    import cairosvg
except Exception:  # pragma: no cover
    cairosvg = None

try:
    import vtracer
except Exception:  # pragma: no cover
    vtracer = None


SVG_NS = "http://www.w3.org/2000/svg"


@dataclass
class LayerTraceResult:
    label: str
    color_hex: str
    opacity: float
    paths: list[dict[str, Any]]
    path_count: int
    pixel_coverage: int


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


def parse_image_bytes(image_bytes: bytes) -> np.ndarray:
    buf = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("Cannot decode image bytes. Please upload a valid PNG/JPG.")
    if len(img.shape) == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        b, g, r = cv2.split(img)
        a = np.full_like(b, 255)
        img = cv2.merge([b, g, r, a])
    return img


def _quantize_rgba(
    img_rgba: np.ndarray,
    n_colors: int,
    alpha_threshold: int,
) -> tuple[np.ndarray, np.ndarray]:
    alpha = img_rgba[:, :, 3]
    fg_mask = alpha > alpha_threshold
    if not np.any(fg_mask):
        raise ValueError("Image has no visible foreground after alpha thresholding.")

    rgb = cv2.cvtColor(img_rgba[:, :, :3], cv2.COLOR_BGR2RGB)
    pixels = rgb[fg_mask].astype(np.float32)
    k = max(2, min(n_colors, len(pixels)))

    criteria = (
        cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
        40,
        0.4,
    )
    _, labels, centers = cv2.kmeans(
        pixels,
        k,
        None,
        criteria,
        6,
        cv2.KMEANS_PP_CENTERS,
    )

    centers = np.clip(centers, 0, 255).astype(np.uint8)
    quantized = np.zeros_like(rgb, dtype=np.uint8)
    quantized[fg_mask] = centers[labels.flatten()]

    label_map = np.full(alpha.shape, -1, dtype=np.int32)
    label_map[fg_mask] = labels.flatten()
    return quantized, label_map


def _clean_mask(mask: np.ndarray, smooth_level: int) -> np.ndarray:
    if mask.dtype != np.uint8:
        mask = mask.astype(np.uint8)

    radius = max(1, int(smooth_level / 2))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (radius * 2 + 1, radius * 2 + 1))
    clean = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    clean = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, kernel, iterations=1)
    clean = morphology.remove_small_objects(clean > 0, min_size=max(16, radius * radius * 4))
    return (clean.astype(np.uint8)) * 255


def _to_hex_color(rgb_triplet: np.ndarray) -> str:
    r, g, b = [int(v) for v in rgb_triplet]
    return f"#{r:02x}{g:02x}{b:02x}"


def _trace_mask_with_vtracer(
    rgba_img: np.ndarray,
    smooth: int,
    threshold: int,
) -> str:
    if vtracer is None:
        raise RuntimeError("vtracer is not installed. Please install dependencies first.")

    ok, encoded = cv2.imencode(".png", cv2.cvtColor(rgba_img, cv2.COLOR_RGBA2BGRA))
    if not ok:
        raise RuntimeError("Failed to encode layer image for vector tracing.")
    raw = encoded.tobytes()

    params = {
        "img_bytes": raw,
        "img_format": "png",
        "colormode": "color",
        "hierarchical": "stacked",
        "mode": "spline",
        "filter_speckle": max(1, 8 - smooth),
        "color_precision": max(1, min(8, int(math.ceil(threshold / 16)))),
        "layer_difference": max(4, min(24, int(threshold / 5))),
        "corner_threshold": max(30, min(120, int(30 + threshold * 0.9))),
        "length_threshold": max(2.0, 8.0 - smooth * 0.5),
        "max_iterations": max(4, smooth + 4),
        "splice_threshold": max(20, min(70, 20 + threshold // 2)),
        "path_precision": max(1, min(5, int(round(smooth / 2)))),
    }

    try:
        return vtracer.convert_raw_image_to_svg(**params)
    except TypeError:
        if not hasattr(vtracer, "convert_image_to_svg"):
            raise RuntimeError(
                "Current vtracer binding does not support in-memory tracing. "
                "Please upgrade to vtracer>=0.6.11."
            )
        with tempfile.TemporaryDirectory(prefix="fr3-vtrace-") as tmp:
            input_path = os.path.join(tmp, "layer.png")
            output_path = os.path.join(tmp, "layer.svg")
            with open(input_path, "wb") as f:
                f.write(raw)

            file_params = {k: v for k, v in params.items() if k not in {"img_bytes", "img_format"}}
            file_params["input_path"] = input_path
            file_params["output_path"] = output_path
            vtracer.convert_image_to_svg(**file_params)
            with open(output_path, "r", encoding="utf-8") as f:
                return f.read()


def _parse_svg_paths(svg_string: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(svg_string)
    except ET.ParseError:
        return []

    paths: list[dict[str, Any]] = []
    for node in root.iter():
        tag = node.tag
        if isinstance(tag, str) and tag.endswith("path"):
            d = node.attrib.get("d", "").strip()
            if not d:
                continue
            entry = {
                "d": d,
                "fill": node.attrib.get("fill"),
                "fill-opacity": node.attrib.get("fill-opacity"),
                "stroke": node.attrib.get("stroke"),
                "stroke-width": node.attrib.get("stroke-width"),
                "opacity": node.attrib.get("opacity"),
            }
            paths.append(entry)
    return paths


def _build_final_svg(
    width: int,
    height: int,
    layers: list[LayerTraceResult],
) -> str:
    dwg = svgwrite.Drawing(size=(width, height), profile="full")
    dwg.attribs["viewBox"] = f"0 0 {width} {height}"
    dwg.attribs["xmlns"] = SVG_NS

    root_group = dwg.g(id="vectorized-art-text")
    for layer in layers:
        g = dwg.g(
            id=f"layer-{layer.label}",
            fill=layer.color_hex,
            opacity=f"{layer.opacity:.4f}",
        )
        for p in layer.paths:
            path_kwargs: dict[str, Any] = {"d": p["d"]}
            if p.get("fill"):
                path_kwargs["fill"] = p["fill"]
            if p.get("fill-opacity"):
                path_kwargs["fill_opacity"] = p["fill-opacity"]
            if p.get("stroke"):
                path_kwargs["stroke"] = p["stroke"]
            if p.get("stroke-width"):
                path_kwargs["stroke_width"] = p["stroke-width"]
            if p.get("opacity"):
                path_kwargs["opacity"] = p["opacity"]
            g.add(dwg.path(**path_kwargs))
        root_group.add(g)

    dwg.add(root_group)
    return dwg.tostring()


def _svg_to_png_data_url(svg_text: str, width: int, height: int) -> str:
    if cairosvg is None:
        raise RuntimeError("cairosvg is not installed. Cannot generate preview PNG.")
    png_bytes = cairosvg.svg2png(
        bytestring=svg_text.encode("utf-8"),
        output_width=width,
        output_height=height,
    )
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _png_data_url_to_rgba(png_data_url: str) -> np.ndarray:
    raw = decode_base64_image(png_data_url)
    return cv2.cvtColor(parse_image_bytes(raw), cv2.COLOR_BGRA2RGBA)


def _contour_metrics(src_rgba: np.ndarray, preview_rgba: np.ndarray, alpha_threshold: int) -> dict[str, float]:
    src_mask = (src_rgba[:, :, 3] > alpha_threshold).astype(np.uint8) * 255
    pre_mask = (preview_rgba[:, :, 3] > alpha_threshold).astype(np.uint8) * 255

    src_edge = cv2.Canny(src_mask, 50, 150)
    pre_edge = cv2.Canny(pre_mask, 50, 150)

    src_edge_bool = src_edge > 0
    pre_edge_bool = pre_edge > 0

    inter = np.logical_and(src_mask > 0, pre_mask > 0).sum()
    union = np.logical_or(src_mask > 0, pre_mask > 0).sum()
    iou = float(inter / union) if union else 1.0

    if np.any(src_edge_bool) and np.any(pre_edge_bool):
        dist_to_pre = cv2.distanceTransform((pre_edge == 0).astype(np.uint8), cv2.DIST_L2, 3)
        dist_to_src = cv2.distanceTransform((src_edge == 0).astype(np.uint8), cv2.DIST_L2, 3)
        mean_src_to_pre = float(dist_to_pre[src_edge_bool].mean())
        mean_pre_to_src = float(dist_to_src[pre_edge_bool].mean())
        chamfer = (mean_src_to_pre + mean_pre_to_src) / 2.0
    else:
        chamfer = float("inf")

    return {
        "mask_iou": round(iou, 6),
        "contour_chamfer_px": round(chamfer, 4) if math.isfinite(chamfer) else -1.0,
    }


def vectorize_art_text(image_bytes: bytes, vector: dict[str, Any]) -> dict[str, Any]:
    smooth = _safe_int(vector.get("smooth", 6), 6)
    threshold = _safe_int(vector.get("threshold", 42), 42)
    colors = _safe_int(vector.get("colors", 8), 8)
    alpha_threshold = max(1, min(220, _safe_int(vector.get("alphaThreshold", 8), 8)))

    src_bgra = parse_image_bytes(image_bytes)
    src_rgba = cv2.cvtColor(src_bgra, cv2.COLOR_BGRA2RGBA)
    height, width = src_rgba.shape[:2]

    quant_rgb, label_map = _quantize_rgba(src_rgba, colors, alpha_threshold)
    unique_labels, counts = np.unique(label_map[label_map >= 0], return_counts=True)
    ordered_labels = [int(x) for _, x in sorted(zip(counts.tolist(), unique_labels.tolist()), reverse=True)]

    layers: list[LayerTraceResult] = []
    for i, label_idx in enumerate(ordered_labels):
        layer_mask = (label_map == label_idx).astype(np.uint8) * 255
        layer_mask = _clean_mask(layer_mask, smooth)
        if np.count_nonzero(layer_mask) == 0:
            continue

        color_pixels = quant_rgb[label_map == label_idx]
        if len(color_pixels) == 0:
            continue
        layer_color = np.median(color_pixels, axis=0).astype(np.uint8)
        color_hex = _to_hex_color(layer_color)

        layer_rgba = np.zeros((height, width, 4), dtype=np.uint8)
        layer_rgba[:, :, 0] = layer_color[0]
        layer_rgba[:, :, 1] = layer_color[1]
        layer_rgba[:, :, 2] = layer_color[2]
        layer_rgba[:, :, 3] = layer_mask

        traced_svg = _trace_mask_with_vtracer(layer_rgba, smooth=smooth, threshold=threshold)
        traced_paths = _parse_svg_paths(traced_svg)
        if not traced_paths:
            continue

        coverage = int(np.count_nonzero(layer_mask))
        opacity = float(min(1.0, max(0.02, coverage / max(1, np.count_nonzero(src_rgba[:, :, 3] > alpha_threshold)))))
        layers.append(
            LayerTraceResult(
                label=f"{i:02d}",
                color_hex=color_hex,
                opacity=opacity,
                paths=traced_paths,
                path_count=len(traced_paths),
                pixel_coverage=coverage,
            )
        )

    if not layers:
        raise RuntimeError("No vector paths generated. Try increasing 'colors' or lowering 'threshold'.")

    svg_text = _build_final_svg(width=width, height=height, layers=layers)
    png_data_url = _svg_to_png_data_url(svg_text, width, height)
    preview_rgba = _png_data_url_to_rgba(png_data_url)
    metrics = _contour_metrics(src_rgba=src_rgba, preview_rgba=preview_rgba, alpha_threshold=alpha_threshold)

    metadata = {
        "engine": "fr3-intelligent-vectorization",
        "canvas": {"width": width, "height": height, "viewBox": f"0 0 {width} {height}"},
        "params": {
            "smooth": smooth,
            "threshold": threshold,
            "colors": colors,
            "alpha_threshold": alpha_threshold,
        },
        "layers": [
            {
                "id": layer.label,
                "color": layer.color_hex,
                "opacity": round(layer.opacity, 4),
                "path_count": layer.path_count,
                "pixel_coverage": layer.pixel_coverage,
            }
            for layer in layers
        ],
        "quality": metrics,
    }
    return {"png": png_data_url, "svg": svg_text, "metadata": metadata}
