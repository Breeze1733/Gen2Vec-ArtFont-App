from __future__ import annotations

import base64
import copy
import io
import json
import os
import random
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from PIL import Image, ImageDraw, ImageFont

from .models import GenerationRequest


# ── Default node ID mappings (fallback when class_type scanning fails) ──
DEFAULT_NODE_IDS: dict[str, str] = {
    "checkpoint": "4",
    "empty_latent": "5",
    "positive": "6",
    "negative": "7",
    "sampler": "3",
    "vae_decode": "8",
    "save_image": "9",
}


# ── Environment variable defaults ──
_ENV_COMFYUI_HOST = "COMFYUI_HOST"
_ENV_POLL_TIMEOUT = "COMFYUI_POLL_TIMEOUT"
_ENV_POLL_INTERVAL = "COMFYUI_POLL_INTERVAL"
_ENV_WORKFLOW_PATH = "WORKFLOW_PATH"

_DEFAULT_COMFYUI_HOST = "http://127.0.0.1:8188"
_DEFAULT_POLL_TIMEOUT = 120
_DEFAULT_POLL_INTERVAL = 1.0


@dataclass(frozen=True)
class GenerationArtifact:
    image_base64: str
    image_name: str
    metadata: dict


# ── Workflow helpers ──


def _resolve_workflow_path(workflow_name: str = "") -> Path:
    """Return absolute path to the workflow JSON template.

    Priority:
      1. WORKFLOW_PATH env var (highest, for dev overrides)
      2. ``workflow_name`` from request → ``workflows/{name}.json``
      3. Default: ``workflows/flux_schnell.json``
    """
    env_path = os.environ.get(_ENV_WORKFLOW_PATH)
    if env_path:
        return Path(env_path).expanduser().resolve()

    project_root = Path(__file__).resolve().parents[2]
    workflows_dir = project_root / "workflows"

    if workflow_name:
        name = workflow_name if workflow_name.endswith(".json") else f"{workflow_name}.json"
        return workflows_dir / name

    return workflows_dir / "flux_schnell.json"


def _load_workflow(path: Path) -> dict:
    """Load and validate a ComfyUI API-format workflow JSON."""
    if not path.exists():
        raise FileNotFoundError(f"Workflow file not found: {path}")

    raw = path.read_text(encoding="utf-8")
    workflow = json.loads(raw)

    if not isinstance(workflow, dict):
        raise ValueError("Workflow must be a JSON object (dict of node_id -> node)")

    for node_id, node in workflow.items():
        if not isinstance(node, dict) or "class_type" not in node:
            raise ValueError(f"Node {node_id!r} is missing 'class_type' — not an API-format workflow.")
        if "inputs" not in node:
            raise ValueError(f"Node {node_id!r} is missing 'inputs' — not an API-format workflow.")

    return workflow


def _find_nodes_by_class(workflow: dict, class_type: str) -> list[tuple[str, dict]]:
    """Scan all workflow entries and return (node_id, node_data) for matching class_type."""
    return [(nid, node) for nid, node in workflow.items() if node.get("class_type") == class_type]


# ── Prompt template engine ──

# 文本艺术字常见缺陷的默认负面提示词
_DEFAULT_NEGATIVE = (
    "broken strokes, missing strokes, wrong characters, garbled text, "
    "duplicate characters, repeated characters, extra character, wrong character count, "
    "deformed text, blurry text, low quality, jpeg artifacts, "
    "watermark, text signature, messy background, cluttered layout"
)


def _detect_workflow_model(workflow: dict) -> str:
    """Detect which model family a workflow targets.

    Returns 'flux' if the workflow uses DualCLIPLoader + CLIPTextEncodeFlux,
    'zimage' if it uses CLIPLoader(type=lumina2),
    'qwen_image' if it uses CLIPLoader(type=qwen_image), otherwise 'unknown'.
    """
    for node in workflow.values():
        ct = node.get("class_type", "")
        if ct == "DualCLIPLoader":
            return "flux"
        if ct == "CLIPLoader":
            clip_type = node.get("inputs", {}).get("type", "")
            if clip_type == "lumina2":
                return "zimage"
            if clip_type == "qwen_image":
                return "qwen_image"
    return "unknown"


def _build_flux_prompt(text: str, style_prompt: str) -> str:
    """Build Flux.1 prompt — text accuracy guard only, style from user."""
    if not text.strip():
        return style_prompt

    has_chinese = bool(re.search(r"[一-鿿]", text))
    has_english = bool(re.search(r"[a-zA-Z]{2,}", text))
    has_number = bool(re.search(r"\d", text))

    parts = []

    if has_chinese:
        cn_chars = re.findall(r"[一-鿿]", text)
        cn_count = len(cn_chars)
        char_list = " ".join(cn_chars)
        parts.append(
            f'Chinese text "{char_list}", exactly {cn_count} characters, '
            "accurate strokes, complete radicals, "
            "no missing character, no extra character, no repeated character"
        )
        if has_english:
            parts.append("crisp letterforms, perfect typography")
    elif has_english:
        parts.append(
            f'text "{text}", crisp typography, perfect letterforms, no duplicate letters'
        )
    else:
        parts.append(f'text "{text}"')

    if has_number:
        parts.append("accurate digits, no repeated digits")

    if style_prompt.strip():
        parts.append(style_prompt.strip())

    return ", ".join(parts) if parts else style_prompt


def _build_zimage_prompt(text: str, style_prompt: str) -> str:
    """Build Z-Image prompt — text accuracy guard only, style from user."""
    if not text.strip():
        return style_prompt

    has_chinese = bool(re.search(r"[一-鿿]", text))
    has_english = bool(re.search(r"[a-zA-Z]{2,}", text))
    has_number = bool(re.search(r"\d", text))

    parts = []

    if has_chinese:
        cn_chars = re.findall(r"[一-鿿]", text)
        cn_count = len(cn_chars)
        char_list = " ".join(cn_chars)
        parts.append(
            f'文字内容为"{char_list}"，不多不少正好{cn_count}个字，'
            "不丢字不缺字，不重字不多字，每个字笔画完整结构正确"
        )
        if has_english:
            parts.append(f'同时包含英文"{text}"，字母清晰比例正确')
    elif has_english:
        parts.append(f'文字内容为"{text}"，字母清晰，间距合理，不重复不遗漏')
    else:
        parts.append(f'文字内容为"{text}"')

    if has_number:
        parts.append("数字大小比例正确，清晰可辨，不重不漏")

    if style_prompt.strip():
        parts.append(style_prompt.strip())

    return "，".join(parts) if parts else style_prompt


def _build_text_art_prompt(text: str, style_prompt: str, model: str = "unknown") -> str:
    """Dispatch to the right prompt builder based on detected model family."""
    if model in ("flux", "unknown"):
        return _build_flux_prompt(text, style_prompt)
    elif model in ("zimage", "qwen_image"):
        return _build_zimage_prompt(text, style_prompt)


def _build_negative_prompt(user_negative: str = "") -> str:
    """Merge user negative prompt with text-art-specific default negatives."""
    if user_negative.strip():
        return f"{_DEFAULT_NEGATIVE}, {user_negative.strip()}"
    return _DEFAULT_NEGATIVE


def _patch_workflow(workflow: dict, request: GenerationRequest) -> dict:
    """Deep-copy workflow and inject user parameters by scanning class_type.

    Patching rules:
      - First CLIPTextEncode / CLIPTextEncodeFlux  → positive prompt
      - Second CLIPTextEncode                        → negative prompt
      - EmptyLatentImage / SD3                       → width, height
      - KSampler / KSamplerAdvanced                  → seed
    """
    patched = copy.deepcopy(workflow)

    # ── Detect model family for prompt templating ──
    model = _detect_workflow_model(patched)

    # ── CLIPTextEncode / CLIPTextEncodeFlux (positive / negative) ──
    positive_prompt = _build_text_art_prompt(request.text, request.prompt, model)
    negative_prompt = _build_negative_prompt(request.negative_prompt)
    clip_nodes = _find_nodes_by_class(patched, "CLIPTextEncode")
    clip_nodes += _find_nodes_by_class(patched, "CLIPTextEncodeFlux")
    for i, (nid, node) in enumerate(clip_nodes):
        prompt_text = positive_prompt if i == 0 else negative_prompt
        if node.get("class_type") == "CLIPTextEncodeFlux":
            node["inputs"]["clip_l"] = prompt_text
            node["inputs"]["t5xxl"] = prompt_text
        else:
            node["inputs"]["text"] = prompt_text

    # ── EmptyLatentImage / EmptySD3LatentImage (resolution) ──
    latent_nodes = _find_nodes_by_class(patched, "EmptyLatentImage")
    latent_nodes += _find_nodes_by_class(patched, "EmptySD3LatentImage")
    w, h = _parse_resolution(request.resolution)
    for _nid, node in latent_nodes:
        node["inputs"]["width"] = w
        node["inputs"]["height"] = h

    # ── KSampler (seed) ──
    sampler_nodes = _find_nodes_by_class(patched, "KSampler")
    sampler_nodes += _find_nodes_by_class(patched, "KSamplerAdvanced")
    for _nid, node in sampler_nodes:
        node["inputs"]["seed"] = request.seed

    return patched


# ── Warmup ──


def warmup_comfyui_connection() -> None:
    """Quick connectivity check so the first generate call doesn't wait for startup."""
    host = os.environ.get(_ENV_COMFYUI_HOST, _DEFAULT_COMFYUI_HOST).rstrip("/")
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{host}/system_stats")
            if resp.status_code == 200:
                logger = __import__("logging").getLogger(__name__)
                logger.info("ComfyUI connection verified at %s", host)
    except Exception:
        pass  # ComfyUI may still be starting — that's fine


# ── ComfyUI API interaction ──


def _call_comfyui_api(request: GenerationRequest, workflow: dict) -> Optional[GenerationArtifact]:
    """Submit patched workflow to ComfyUI, poll for result, return artifact.

    Returns None on any failure (connection, timeout, execution error)
    so the caller can fall back to the local stub.
    """
    host = os.environ.get(_ENV_COMFYUI_HOST, _DEFAULT_COMFYUI_HOST).rstrip("/")
    timeout = int(os.environ.get(_ENV_POLL_TIMEOUT, str(_DEFAULT_POLL_TIMEOUT)))
    interval = float(os.environ.get(_ENV_POLL_INTERVAL, str(_DEFAULT_POLL_INTERVAL)))

    try:
        with httpx.Client(timeout=30.0) as client:
            # 1. Patch and submit
            client_id = str(uuid.uuid4())
            patched = _patch_workflow(workflow, request)
            submit_payload = {"prompt": patched, "client_id": client_id}

            submit_resp = client.post(f"{host}/prompt", json=submit_payload)
            if submit_resp.is_error:
                return None
            prompt_id = submit_resp.json().get("prompt_id")
            if not prompt_id:
                return None

            # 2. Poll history for completion
            deadline = time.monotonic() + timeout
            history = None
            while time.monotonic() < deadline:
                hist_resp = client.get(f"{host}/history/{prompt_id}")
                if hist_resp.status_code == 200:
                    data = hist_resp.json()
                    entry = data.get(prompt_id)
                    if entry and entry.get("status", {}).get("completed"):
                        history = entry
                        break
                time.sleep(interval)

            if history is None:
                return None  # timeout

            # 3. Extract image info from SaveImage output
            save_nodes = _find_nodes_by_class(patched, "SaveImage")
            if not save_nodes:
                return None
            save_node_id = save_nodes[0][0]

            outputs = history.get("outputs", {})
            node_outputs = outputs.get(save_node_id, {})
            images = node_outputs.get("images", [])
            if not images:
                return None

            img_info = images[0]
            filename = img_info["filename"]
            subfolder = img_info.get("subfolder", "")
            img_type = img_info.get("type", "output")

            # 4. Download actual image bytes
            view_resp = client.get(
                f"{host}/view",
                params={"filename": filename, "type": img_type, "subfolder": subfolder},
            )
            view_resp.raise_for_status()
            image_bytes = view_resp.content

            # 5. Encode to base64 data URL
            b64 = base64.b64encode(image_bytes).decode("ascii")
            image_base64 = f"data:image/png;base64,{b64}"

            # 6. Build metadata
            slug = re.sub(r"[^\w一-鿿]+", "-", request.prompt.strip(), flags=re.UNICODE).strip("-")
            image_name = f"{slug or 'txt2img-generated'}.png"
            w, h = _parse_resolution(request.resolution)

            metadata: dict[str, Any] = {
                "engine": "comfyui",
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "resolution": request.resolution,
                "seed": request.seed,
                "style": request.style,
                "format": request.format,
                "canvas": {"width": w, "height": h},
                "comfyui_prompt_id": prompt_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "artifact": {"image_name": image_name, "byte_length": len(image_bytes)},
            }

            return GenerationArtifact(image_base64=image_base64, image_name=image_name, metadata=metadata)

    except Exception:
        return None


# ── Local stub (fallback) ──


def _local_stub_generate(request: GenerationRequest) -> GenerationArtifact:
    from hashlib import sha256

    w, h = _parse_resolution(request.resolution)

    seed_value = request.seed or int.from_bytes(sha256(request.prompt.encode()).digest()[:8], "big")
    rng = random.Random(seed_value)

    def _random_color():
        return tuple(int(c * 255) for c in (rng.random(), rng.random(), rng.random()))

    top = _random_color()
    bottom = _random_color()

    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for y in range(h):
        ratio = y / max(1, h - 1)
        color = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        draw.line((0, y, w, y), fill=color)

    try:
        font = ImageFont.truetype("arial.ttf", size=max(20, w // 24))
    except Exception:
        font = ImageFont.load_default()
    draw.text((16, 16), request.prompt[:80], font=font, fill=(255, 255, 255))

    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    png_bytes = buf.getvalue()
    image_base64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")

    slug = re.sub(r"[^\w一-鿿]+", "-", request.prompt.strip(), flags=re.UNICODE).strip("-")
    image_name = f"{slug or 'txt2img-generated'}.png"

    metadata: dict[str, Any] = {
        "engine": "local-studio",
        "prompt": request.prompt,
        "negative_prompt": request.negative_prompt,
        "resolution": request.resolution,
        "seed": seed_value,
        "style": request.style,
        "format": request.format,
        "canvas": {"width": w, "height": h},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifact": {"image_name": image_name, "byte_length": len(png_bytes)},
    }

    return GenerationArtifact(image_base64=image_base64, image_name=image_name, metadata=metadata)


# ── Resolution parser ──


def _parse_resolution(resolution: str) -> tuple[int, int]:
    """Parse '1024x1024' or '1024 x 1024' into (width, height)."""
    parts = resolution.strip().lower().replace(" ", "").split("x")
    if len(parts) != 2:
        return 1024, 1024
    try:
        w, h = int(parts[0]), int(parts[1])
        return (w, h) if w > 0 and h > 0 else (1024, 1024)
    except ValueError:
        return 1024, 1024


# ── Public entry point ──


# 工作流降级链：按内容类型选择优先级
_CHINESE_FALLBACK = ["qwen_image_2512_gguf", "test_z_image_turbo"]
_ENGLISH_FALLBACK = ["flux_schnell", "test_z_image_turbo"]


def _is_primarily_chinese(text: str) -> bool:
    """Return True if the text has more Chinese characters than non-Chinese."""
    if not text.strip():
        return False
    cn = len(re.findall(r"[一-鿿]", text))
    return cn > 0 and cn >= len(text.strip()) * 0.5


def generate_artwork(request: GenerationRequest) -> GenerationArtifact:
    """依次尝试工作流降级链，全部失败则用本地 Pillow stub。

    - 用户显式指定了 workflow → 只尝试那一个
    - 中文为主 → Qwen-Image → Z-Image
    - 英文/其他 → Flux → Z-Image
    """
    workflows_to_try: list[str]
    if request.workflow:
        workflows_to_try = [request.workflow]
    elif _is_primarily_chinese(request.text):
        workflows_to_try = list(_CHINESE_FALLBACK)
    else:
        workflows_to_try = list(_ENGLISH_FALLBACK)

    for name in workflows_to_try:
        try:
            workflow_path = _resolve_workflow_path(name)
            workflow = _load_workflow(workflow_path)
            result = _call_comfyui_api(request, workflow)
            if result is not None:
                return result
        except Exception:
            continue

    return _local_stub_generate(request)
