"""
================================================================================
矢量化引擎核心模块 (Vectorization Engine)
================================================================================

本模块实现了艺术字位图到高质量 W3C 标准 SVG 矢量图的端到端转换与保真度评估流水线。

【核心算法原理与数学实现说明】

1. 图像预处理与抗锯齿轮廓边缘增强 (Image Preprocessing & Edge Refinement):
   - 形态学闭开滤波 (Morphological Filtering):
     闭运算: A • B = (A ⊕ B) ⊖ B，利用 3x3 结构元消除字符笔画内部微孔；
     开运算: A ∘ B = (A ⊖ B) ⊕ B，滤除轮廓毛刺与游离噪点。
   - 连通域拓扑几何面积滤波 (Connected Component Analysis with Stats):
     对二值前景掩模进行 8-邻域连通域标记，计算各独立连通块面积 S_i。设定动态面积阈值:
         S_min = max(2, (W × H) / D_min)
     过滤孤立微小飞溅噪点，保证矢量化轮廓的紧凑与连续。
   - 双重自适应高斯软化重映射 (Adaptive Gaussian Antialiasing Softening):
     经膨胀/腐蚀后的边缘进行两级二维高斯滤波:
         α_soft(x, y) = G_σ * α(x, y), 其中 G_σ = (1 / (2πσ²)) exp(-(x² + y²) / (2σ²))
     消除光栅位图离散网格导致的阶梯状阶跃（Stair-stepping / Jaggies）。

2. 基于三次贝塞尔样条 (Cubic Bézier Spline) 的连续路径拟合:
   - 三次贝塞尔曲线参数方程:
         B(t) = (1 - t)³ P₀ + 3(1 - t)² t P₁ + 3(1 - t) t² P₂ + t³ P₃,  t ∈ [0, 1]
     其中 P₀, P₃ 为曲线锚点 (Anchors)，P₁, P₂ 为方向控制点 (Control Points)。
   - 路径拟合优化准则:
     依据曲率特征点自适应划分段落。通过拐角阈值 θ_corner (corner_threshold) 判定转折硬角:
         cos θ = (v₁ · v₂) / (||v₁|| ||v₂||)
     若夹角变化超过阈值则保留为硬锚点，否则在连续导数约束下拟合平滑样条曲线。

3. 语义化图层解耦与拓扑分类算法 (Semantic Layer Decoupling & Topological Grouping):
   - 空间连通度与中心偏离度度量:
     设画布尺寸为 W × H，中心坐标 (C_x, C_y) = (W/2, H/2)，对角线半长 R_diag = √((W/2)² + (H/2)²)。
     对每个独立闭合路径 p，计算其包围盒质心 (c_x, c_y)，归一化中心距离:
         d_center(p) = √((c_x - C_x)² + (c_y - C_y)²) / R_diag
   - 相对面积比率:
         a_rel(p) = (w_p × h_p) / (W × H)
   - 色彩特征感知空间映射 (Perceptual Luminance & Saturation):
         Y(p) = 0.299 R + 0.587 G + 0.114 B,  V(p) = max(R,G,B) / 255
         S(p) = (max(R,G,B) - min(R,G,B)) / max(1, max(R,G,B))
   - 多层级拓扑分类规则:
     ① 投影阴影层 (layer-shadow): (Y < 0.22 或 V < 0.25) 且 a_rel < 0.70，或暗调底衬 (Y < 0.35, S < 0.25, c_y > C_y)；
     ② 散落装饰层 (layer-decorations): d_center > 0.35 且 a_rel < 0.10（外围游离花瓣、叶片、光芒等）；
     ③ 描边外框层 (layer-stroke): 底衬闭合大轮廓 (index=0 且 a_rel > 0.20) 或特征金边/高反差描边；
     ④ 文字主体层 (layer-main-text): 核心字形实体填充与主结构笔画。

4. 综合保真度评估模型 (Multi-dimensional Vector Fidelity Scoring):
   综合空间结构、边缘梯度与感知色彩三维指标计算保真度得分 (Fidelity ∈ [0, 100]):
       Fidelity = 0.50 × SSIM(I_orig, I_vec) + 0.30 × Corr(∇I_orig, ∇I_vec) + 0.20 × Corr(Hist_Lab_orig, Hist_Lab_vec)
   其中 SSIM 使用 11x11 局部窗口，Corr(∇I) 为 Sobel 边缘响应的皮尔逊相关系数。

5. W3C SVG 1.1 / 2.0 规范化与 Dublin Core / JSON-LD 双模元数据规范:
   输出符合标准 XML 语法的矢量代码，显式定义 viewBox 与尺寸，并在 <metadata> 节点内嵌入
   Dublin Core RDF 描述与结构化 JSON-LD 数据，支持主流专业矢量编辑软件无损分层导入。
================================================================================
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import re
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from typing import Any
from xml.dom import minidom

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# 注册标准 XML 命名空间，保证 SVG 导出的前缀整洁规范
ET.register_namespace("", "http://www.w3.org/2000/svg")
ET.register_namespace("inkscape", "http://www.inkscape.org/namespaces/inkscape")
ET.register_namespace("rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#")
ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
ET.register_namespace("artfont", "https://gen2vec.artfont/schema#")

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

try:
    import resvg_py
except Exception:  # pragma: no cover
    resvg_py = None

try:
    import vtracer
except Exception:  # pragma: no cover
    vtracer = None


PRESET_CONFIG: dict[str, dict[str, int]] = {
    "clean": {"cp": 2, "fs": 48, "ct": 120, "lt": 30, "ld": 38, "scale": 2},
    "balanced": {"cp": 6, "fs": 18, "ct": 70, "lt": 12, "ld": 20, "scale": 2},
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

_COORD_RE = re.compile(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?")
_TRANSLATE_RE = re.compile(r"translate\(\s*([-+]?(?:\d*\.\d+|\d+))\s*,\s*([-+]?(?:\d*\.\d+|\d+))\s*\)")

LAYER_DEFINITIONS: list[tuple[str, str]] = [
    ("layer-shadow", "投影阴影"),
    ("layer-stroke", "描边轮廓"),
    ("layer-main-text", "主体文字"),
    ("layer-decorations", "装饰图形"),
]


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


def _svg_to_png_bytes(svg_text: str, width: int | None = None, height: int | None = None) -> bytes:
    if resvg_py is None:
        raise RuntimeError("resvg-py is not installed. Cannot generate preview PNG.")
    return resvg_py.svg_to_bytes(svg_string=svg_text, width=width, height=height)


def _parse_path_bbox(d: str, transform: str = "") -> tuple[float, float, float, float]:
    tx, ty = 0.0, 0.0
    if transform:
        m = _TRANSLATE_RE.search(transform)
        if m:
            tx, ty = float(m.group(1)), float(m.group(2))
    nums = [float(x) for x in _COORD_RE.findall(d)]
    if len(nums) < 2:
        return tx, ty, tx + 1.0, ty + 1.0
    xs = [nums[i] + tx for i in range(0, len(nums) - 1, 2)]
    ys = [nums[i + 1] + ty for i in range(0, len(nums) - 1, 2)]
    if not xs or not ys:
        return tx, ty, tx + 1.0, ty + 1.0
    return min(xs), min(ys), max(xs), max(ys)


def _parse_fill_rgb(fill_str: str) -> tuple[int, int, int]:
    fill = (fill_str or "").strip()
    if fill.startswith("#"):
        h = fill.lstrip("#")
        if len(h) == 6:
            try:
                return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            except ValueError:
                pass
        elif len(h) == 3:
            try:
                return int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16)
            except ValueError:
                pass
    elif fill.startswith("rgb"):
        nums = [int(x) for x in re.findall(r"\d+", fill)]
        if len(nums) >= 3:
            return nums[0], nums[1], nums[2]
    return 128, 128, 128


def _classify_svg_path(
    path_elem: ET.Element,
    canvas_w: int,
    canvas_h: int,
    path_idx: int,
    total_paths: int,
) -> str:
    d = path_elem.get("d", "")
    tr = path_elem.get("transform", "")
    fill = path_elem.get("fill", "")

    x1, y1, x2, y2 = _parse_path_bbox(d, tr)
    pw = max(1.0, x2 - x1)
    ph = max(1.0, y2 - y1)
    rel_area = (pw * ph) / float(max(1, canvas_w * canvas_h))

    cx, cy = canvas_w / 2.0, canvas_h / 2.0
    diag = math.sqrt(cx * cx + cy * cy)
    pcx, pcy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    d_center = math.sqrt((pcx - cx) ** 2 + (pcy - cy) ** 2) / float(max(1.0, diag))

    r, g, b = _parse_fill_rgb(fill)
    lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    max_c, min_c = max(r, g, b), min(r, g, b)
    val = max_c / 255.0
    sat = (max_c - min_c) / float(max(1, max_c))

    # 1. 投影阴影判定 (暗调且位于下方或底层)
    if (lum < 0.22 or val < 0.25) and rel_area < 0.70:
        return "layer-shadow"
    if lum < 0.35 and sat < 0.25 and pcy > cy and rel_area < 0.50:
        return "layer-shadow"

    # 2. 外部散落装饰判定 (距离中心远、面积小)
    if d_center > 0.35 and rel_area < 0.10:
        return "layer-decorations"

    # 3. 描边轮廓判定 (外围底衬基底 或 特征金边/高反差描边)
    is_gold_edge = r > 180 and g > 140 and b < 90 and sat > 0.35
    is_bright_border = lum > 0.90 and sat < 0.15 and rel_area > 0.10
    is_base_chassis = path_idx == 0 and total_paths >= 3 and rel_area > 0.20
    if is_gold_edge or is_bright_border or is_base_chassis:
        return "layer-stroke"

    # 4. 默认归入主体文字层
    return "layer-main-text"


def _populate_metadata_element(meta_elem: ET.Element, metadata: dict[str, Any]) -> None:
    rdf = ET.SubElement(meta_elem, "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF")
    desc = ET.SubElement(
        rdf,
        "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description",
        {"{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about": ""},
    )

    gen = metadata.get("generation", {})
    params = metadata.get("params", {})
    quality = metadata.get("quality", {})
    stats = metadata.get("stats", {})

    source_type = metadata.get("source_type") or ("upload" if not gen.get("prompt") and not gen.get("text") else "generated")
    is_pure_vectorize = source_type == "upload"

    text = gen.get("text", "")
    prompt = gen.get("prompt", "")
    seed = gen.get("seed")
    preset = params.get("preset", "balanced")
    fidelity = quality.get("svg_fidelity")
    created_at = metadata.get("created_at") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    title = str(text or prompt or "ArtFont Vector")

    title_el = ET.SubElement(desc, "{http://purl.org/dc/elements/1.1/}title")
    title_el.text = title

    creator_el = ET.SubElement(desc, "{http://purl.org/dc/elements/1.1/}creator")
    creator_el.text = "Gen2Vec ArtFont System"

    date_el = ET.SubElement(desc, "{http://purl.org/dc/elements/1.1/}date")
    date_el.text = str(created_at)

    format_el = ET.SubElement(desc, "{http://purl.org/dc/elements/1.1/}format")
    format_el.text = "image/svg+xml"

    if text:
        t_el = ET.SubElement(desc, "{https://gen2vec.artfont/schema#}text")
        t_el.text = str(text)
    if prompt:
        p_el = ET.SubElement(desc, "{https://gen2vec.artfont/schema#}prompt")
        p_el.text = str(prompt)
    # 纯矢量化不需要 seed；文生图模式下哪怕 seed 为 0 也记录
    if not is_pure_vectorize and seed is not None:
        s_el = ET.SubElement(desc, "{https://gen2vec.artfont/schema#}seed")
        s_el.text = str(seed)

    pr_el = ET.SubElement(desc, "{https://gen2vec.artfont/schema#}preset")
    pr_el.text = str(preset)

    if fidelity is not None:
        f_el = ET.SubElement(desc, "{https://gen2vec.artfont/schema#}fidelity")
        f_el.text = f"{fidelity:.1f}"

    engine_el = ET.SubElement(desc, "{https://gen2vec.artfont/schema#}engine")
    engine_el.text = str(metadata.get("engine", "vectorizer-api"))

    # JSON-LD 结构化标签
    script = ET.SubElement(meta_elem, "script", {"type": "application/ld+json"})
    parameters = {
        "preset": preset,
        "elapsedMs": stats.get("elapsed_ms"),
    }
    if not is_pure_vectorize and seed is not None:
        parameters["seed"] = seed

    json_summary = {
        "@context": "https://schema.org",
        "@type": "VisualArtwork",
        "name": title,
        "description": prompt,
        "artform": "Vector Art",
        "artMedium": "SVG",
        "generator": {
            "@type": "SoftwareApplication",
            "name": "Gen2Vec ArtFont",
            "version": "1.0.1",
        },
        "fidelityScore": fidelity,
        "parameters": parameters,
    }
    script.text = json.dumps(json_summary, ensure_ascii=False)


def restructure_and_group_svg(
    raw_svg_text: str,
    canvas_width: int,
    canvas_height: int,
    viewbox_width: int | None = None,
    viewbox_height: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """重构 vtracer 输出的平铺 SVG，构建 W3C 规范视口、语义解耦图层与内嵌元数据。"""
    try:
        raw_root = ET.fromstring(raw_svg_text.encode("utf-8"))
    except Exception as exc:
        logger.warning("Failed to parse raw SVG XML: %s", exc)
        return raw_svg_text

    # 提取所有绘图路径
    paths = list(raw_root.findall(".//{http://www.w3.org/2000/svg}path"))
    if not paths:
        paths = list(raw_root.findall(".//path"))

    # 保留可能存在的 defs
    defs = list(raw_root.findall(".//{http://www.w3.org/2000/svg}defs")) or list(raw_root.findall(".//defs"))

    # 解析实际路径坐标系范围（如果进行了上采样 scale，坐标系为 trace 尺寸）
    raw_w_str = raw_root.get("width")
    raw_h_str = raw_root.get("height")
    vw = viewbox_width or (int(float(raw_w_str)) if raw_w_str else canvas_width)
    vh = viewbox_height or (int(float(raw_h_str)) if raw_h_str else canvas_height)
    actual_viewbox = raw_root.get("viewBox") or f"0 0 {vw} {vh}"

    new_root = ET.Element(
        "{http://www.w3.org/2000/svg}svg",
        {
            "version": "1.1",
            "viewBox": actual_viewbox,
            "width": str(canvas_width),
            "height": str(canvas_height),
        },
    )

    # 1. 注入 <metadata>
    meta_elem = ET.SubElement(new_root, "{http://www.w3.org/2000/svg}metadata", {"id": "gen2vec-metadata"})
    if metadata:
        _populate_metadata_element(meta_elem, metadata)

    # 2. 注入 defs
    for d_elem in defs:
        new_root.append(d_elem)

    # 3. 语义化图层分类
    grouped_paths: dict[str, list[ET.Element]] = {
        "layer-shadow": [],
        "layer-stroke": [],
        "layer-main-text": [],
        "layer-decorations": [],
    }

    total = len(paths)
    for idx, p in enumerate(paths):
        category = _classify_svg_path(p, vw, vh, idx, total)
        grouped_paths[category].append(p)

    # 保证主体文字层不为空（至少包含最核心组件）
    if not grouped_paths["layer-main-text"] and paths:
        for cat in ["layer-stroke", "layer-shadow", "layer-decorations"]:
            if grouped_paths[cat]:
                grouped_paths["layer-main-text"].append(grouped_paths[cat].pop(0))
                break

    # 4. 按标准 Z-Order 创建图层分组
    for layer_id, label in LAYER_DEFINITIONS:
        layer_items = grouped_paths[layer_id]
        if not layer_items:
            continue
        g_elem = ET.SubElement(
            new_root,
            "{http://www.w3.org/2000/svg}g",
            {
                "id": layer_id,
                "{http://www.inkscape.org/namespaces/inkscape}label": label,
                "{http://www.inkscape.org/namespaces/inkscape}groupmode": "layer",
            },
        )
        for item in layer_items:
            g_elem.append(item)

    # 5. 格式化输出
    xml_bytes = ET.tostring(new_root, encoding="utf-8")
    parsed = minidom.parseString(xml_bytes)
    pretty = parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
    lines = [line for line in pretty.splitlines() if line.strip()]
    return "\n".join(lines) + "\n"


def inject_svg_metadata(svg_text: str, metadata: dict[str, Any]) -> str:
    """在已生成的 SVG 文本中安全注入或刷新元数据节点。"""
    try:
        root = ET.fromstring(svg_text.encode("utf-8"))
        meta_elem = None
        for child in list(root):
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if tag == "metadata":
                meta_elem = child
                break

        if meta_elem is None:
            meta_elem = ET.Element("{http://www.w3.org/2000/svg}metadata", {"id": "gen2vec-metadata"})
            root.insert(0, meta_elem)
        else:
            meta_elem.clear()
            meta_elem.attrib["id"] = "gen2vec-metadata"

        _populate_metadata_element(meta_elem, metadata)

        xml_bytes = ET.tostring(root, encoding="utf-8")
        parsed = minidom.parseString(xml_bytes)
        pretty = parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
        lines = [line for line in pretty.splitlines() if line.strip()]
        return "\n".join(lines) + "\n"
    except Exception as exc:
        logger.warning("inject_svg_metadata failed: %s", exc)
        return svg_text


def _calculate_svg_fidelity(source_img: Image.Image, preview_png_bytes: bytes) -> float | None:
    """计算 SVG 矢量化还原度。

    - 透明背景统一填色后自动满分（透明 = 天然完美还原）。
    - 前景用 SSIM + 梯度相关性 + 前景色分布三维度评估。
    - 对比前做高斯模糊 + 大窗口 SSIM，对矢量化抗锯齿宽容。
    """
    try:
        from io import BytesIO

        from skimage.metrics import structural_similarity as ssim
        from scipy.ndimage import gaussian_filter

        # ── 1. 前景掩码 ──────────────────────────────────────────
        source_rgba = source_img.convert("RGBA")
        alpha = np.array(source_rgba)[:, :, 3]
        fg_mask = alpha >= 3

        fg_ratio = fg_mask.sum() / fg_mask.size
        if fg_ratio < 0.005:
            return 100.0  # 几乎全透明，完美匹配

        # ── 2. 对齐 + 统一背景 ────────────────────────────────────
        source_rgb = source_img.convert("RGB")
        preview_rgba = Image.open(BytesIO(preview_png_bytes)).convert("RGBA")
        if preview_rgba.size != source_rgb.size:
            preview_rgba = preview_rgba.resize(source_rgb.size, Image.Resampling.LANCZOS)
        preview_rgb = preview_rgba.convert("RGB")

        original_np = np.array(source_rgb).astype(np.float64)
        vector_np = np.array(preview_rgb).astype(np.float64)

        if 0.02 < (1 - fg_ratio) < 0.98:
            neutral = np.array([128.0, 128.0, 128.0], dtype=np.float64)
            original_np[~fg_mask] = neutral
            vector_np[~fg_mask] = neutral

        # ── 3. 高斯预模糊 ────────────────────────────────────────
        h, w = original_np.shape[:2]
        min_dim = min(h, w)
        sigma = max(0.6, min(1.2, min_dim / 800.0))
        original_blur = gaussian_filter(original_np, sigma=(sigma, sigma, 0))
        vector_blur = gaussian_filter(vector_np, sigma=(sigma, sigma, 0))

        # ── 4. SSIM（大窗口，抗局部抖动）───────────────────────────
        if min_dim >= 11:
            win_size = 11
        elif min_dim >= 7:
            win_size = 7
        elif min_dim >= 5:
            win_size = 5
        else:
            win_size = 3

        try:
            ssim_val = ssim(
                original_blur, vector_blur,
                channel_axis=2,
                win_size=win_size,
                data_range=255,
            )
        except TypeError:
            ssim_val = ssim(
                original_blur, vector_blur,
                multichannel=True,
                win_size=win_size,
                data_range=255,
            )
        ssim_val = max(0.0, float(ssim_val))

        # ── 5. 梯度相关性（替代绝对差，容忍边缘微小偏移）──────────
        from skimage.filters import sobel

        edge_orig = sobel(original_blur.mean(axis=2))
        edge_vec = sobel(vector_blur.mean(axis=2))
        edge_corr = np.corrcoef(edge_orig.flat, edge_vec.flat)[0, 1]
        if np.isnan(edge_corr):
            edge_corr = 1.0
        edge_score = max(0.0, float(edge_corr))

        # ── 6. 前景色分布（只看主体区域，排除背景灰）───────────────
        try:
            from skimage.color import rgb2lab

            s_lab = rgb2lab(original_blur / 255.0)
            v_lab = rgb2lab(vector_blur / 255.0)
            color_score = 0.0
            for ch in (1, 2):
                s_fg = s_lab[:, :, ch][fg_mask]
                v_fg = v_lab[:, :, ch][fg_mask]
                if len(s_fg) < 50:
                    color_score += 0.5
                    continue
                s_hist, _ = np.histogram(s_fg, bins=64, range=(-128, 128))
                v_hist, _ = np.histogram(v_fg, bins=64, range=(-128, 128))
                corr = np.corrcoef(s_hist, v_hist)[0, 1]
                color_score += max(0.0, corr) / 2.0
        except Exception:
            color_score = ssim_val

        # ── 7. 融合 ──────────────────────────────────────────────
        fidelity = ssim_val * 0.50 + edge_score * 0.30 + color_score * 0.20
        score = round(max(0.0, min(100.0, fidelity * 100.0)), 1)
        return score
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


def _deep_merge_metadata(target: dict[str, Any], source: dict[str, Any]) -> None:
    for k, v in source.items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_merge_metadata(target[k], v)
        else:
            target[k] = v


def vectorize_image(
    transparent_image: Image.Image,
    vector: dict[str, Any],
    metadata_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
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

        trace_w, trace_h = work_img.size

        with open(output_svg_path, "r", encoding="utf-8") as f:
            raw_svg_text = f.read()

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    actual_viewbox = f"0 0 {trace_w} {trace_h}"

    metadata: dict[str, Any] = {
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
            "viewBox": actual_viewbox,
        },
        "stats": {
            "elapsed_ms": elapsed_ms,
            "svg_size_kb": 0.0,
            "preview_png_size_kb": 0.0,
        },
        "preprocess": {
            "png_transparency": None,
        },
        "quality": {
            "svg_fidelity": 0.0,
        },
        "created_at": "",
    }

    if metadata_context:
        _deep_merge_metadata(metadata, metadata_context)

    # 重构为包含 <metadata> 与分层 <g> 图层的规范完整 SVG (viewBox 完整覆盖实际路径坐标空间)
    formatted_svg_text = restructure_and_group_svg(
        raw_svg_text,
        canvas_width=original_width,
        canvas_height=original_height,
        viewbox_width=trace_w,
        viewbox_height=trace_h,
        metadata=metadata,
    )
    svg_size_kb = round(len(formatted_svg_text.encode("utf-8")) / 1024.0, 3)
    metadata["stats"]["svg_size_kb"] = svg_size_kb

    # 基于最终完整的 SVG 使用 resvg_py 进行回渲染预览与保真度核验
    preview_png_bytes = _svg_to_png_bytes(formatted_svg_text, width=original_width, height=original_height)
    svg_fidelity = _calculate_svg_fidelity(transparent_image, preview_png_bytes)
    preview_data_url = _png_bytes_to_data_url(preview_png_bytes)

    metadata["quality"]["svg_fidelity"] = svg_fidelity
    metadata["stats"]["preview_png_size_kb"] = round(len(preview_png_bytes) / 1024.0, 3)

    return {
        "svg": formatted_svg_text,
        "preview_png": preview_data_url,
        "metadata": metadata,
    }
