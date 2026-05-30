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
    "deformed text, blurry text, low quality, jpeg artifacts, "
    "watermark, text signature, messy background, cluttered layout"
)


def _build_text_art_prompt(text: str, style_prompt: str) -> str:
    """Build an optimized Flux.1 prompt for text art generation.

    Detects text content type (Chinese / English / numbers / mixed)
    and injects targeted quality keywords for each scenario.
    """
    if not text.strip():
        return style_prompt

    has_chinese = bool(re.search(r"[一-鿿]", text))
    has_english = bool(re.search(r"[a-zA-Z]{2,}", text))
    has_number = bool(re.search(r"\d", text))

    parts = ["masterpiece typography design"]

    # Text specification — language-aware
    if has_chinese and has_english:
        parts.append(
            f'bilingual text "{text}", '
            "accurate Chinese character strokes, complete radicals, "
            "crisp English letterforms, perfect typography"
        )
    elif has_chinese:
        parts.append(
            f'Chinese text "{text}", '
            "perfect character strokes, accurate calligraphy structure, "
            "no broken strokes, no missing radicals, correct Chinese characters"
        )
    elif has_english:
        parts.append(
            f'text "{text}", '
            "crisp typography, perfect letterforms, clean kerning, "
            "well-proportioned spacing"
        )
    else:
        parts.append(f'text "{text}"')

    if has_number:
        parts.append("bold clear numbers, accurate digits")

    # Style injection
    if style_prompt.strip():
        parts.append(style_prompt.strip())

    # Universal quality suffix
    parts.append("clean composition, high contrast, sharp details, 4K, professional design")

    return ", ".join(parts)


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

    # ── CLIPTextEncode / CLIPTextEncodeFlux (positive / negative) ──
    positive_prompt = _build_text_art_prompt(request.text, request.prompt)
    negative_prompt = _build_negative_prompt(request.negative_prompt)
    clip_nodes = _find_nodes_by_class(patched, "CLIPTextEncode")
    clip_nodes += _find_nodes_by_class(patched, "CLIPTextEncodeFlux")
    for i, (nid, node) in enumerate(clip_nodes):
        if i == 0:
            node["inputs"]["text"] = positive_prompt
        elif i == 1:
            node["inputs"]["text"] = negative_prompt

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


# 工作流降级链：按优先级依次尝试，全部失败后用本地 stub
_WORKFLOW_FALLBACK_CHAIN = ["flux_schnell", "test_z_image_turbo"]


def generate_artwork(request: GenerationRequest) -> GenerationArtifact:
    """依次尝试工作流降级链，全部失败则用本地 Pillow stub。

    - 用户显式指定了 workflow → 只尝试那一个
    - 未指定 → 按 _WORKFLOW_FALLBACK_CHAIN 顺序降级
    """
    workflows_to_try: list[str]
    if request.workflow:
        workflows_to_try = [request.workflow]
    else:
        workflows_to_try = list(_WORKFLOW_FALLBACK_CHAIN)

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
