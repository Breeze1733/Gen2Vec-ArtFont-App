"""四场景验收脚本的共享库：HTTP / 断言 / 进度 / 后端生命周期 / 图像 / SVG。

设计约定
--------
* **不跨服务 import**：两个服务的包都叫 `app`、各有独立 venv，脱离包上下文无法加载。
  本文件复刻所需常量，并用 `contract_guard()` 检测源码漂移。
* **每行输出都 flush**：脚本总耗时约 20 分钟，用户必须随时看到进度。
* **stub 一律硬拒绝**：ComfyUI 不可用时后端会静默回落到 Pillow stub，
  不拦就会「测试全绿但什么都没生成」。
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import requests

# ── 常量：复刻自 services/txt2img-api/app/generator.py，由 contract_guard() 守卫 ──

TXT2IMG_PORT = 9001
VECTORIZER_PORT = 8000
DEFAULT_COMFYUI_HOST = "http://127.0.0.1:8188"

# generator.py:_ROUTE_CHAINS
ROUTE_CHAINS: dict[str, list[str]] = {
    "chinese": ["qwen_image_2512_gguf", "test_z_image_turbo"],
    "english": ["flux_schnell", "test_z_image_turbo"],
    "mixed": ["test_z_image_turbo"],
}

# generator.py:_QWEN_RESOLUTIONS / _FLUX_RESOLUTIONS
QWEN_RESOLUTIONS = [
    (1328, 1328), (1664, 928), (928, 1664),
    (1472, 1104), (1104, 1472), (1584, 1056), (1056, 1584),
]
FLUX_RESOLUTIONS = [
    (1024, 1024), (1344, 768), (768, 1344),
    (1152, 896), (896, 1152), (1216, 832), (832, 1216),
]

# generator.py 里 stub 与 ComfyUI 成功路径的 metadata 差异
STUB_ENGINE = "local-studio"

DATA_URL_PNG = "data:image/png;base64,"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_GENERATOR_PY = _REPO_ROOT / "services" / "txt2img-api" / "app" / "generator.py"


# ── 进度输出 ──


def say(msg: str) -> None:
    """立即输出（不缓冲），保证用户实时看到进度。"""
    print(msg, flush=True)


def hr(char: str = "=", width: int = 60) -> None:
    say(char * width)


class Heartbeat:
    """长请求期间每 interval 秒打印一次已等待时间。

    单条生成要 91-285 秒，安静等待会让用户以为脚本卡死。
    """

    def __init__(self, label: str, interval: float = 15.0) -> None:
        self._label = label
        self._interval = interval
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._t0 = 0.0

    def __enter__(self) -> "Heartbeat":
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> bool:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        return False

    def _run(self) -> None:
        n = 0
        while not self._stop.wait(self._interval):
            n += 1
            say(f"      ... {self._label} 已等待 {int(time.monotonic() - self._t0)}s")

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._t0


# ── 结果收集 ──

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"


@dataclass
class Check:
    label: str
    status: str
    detail: str = ""


@dataclass
class ScenarioResult:
    name: str
    status: str = PASS
    checks: list[Check] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    error: str = ""
    elapsed: float = 0.0

    def record(self, ok: bool, label: str, detail: str = "", warn: bool = False) -> bool:
        status = PASS if ok else (WARN if warn else FAIL)
        if not ok and not warn:
            self.status = FAIL
        self.checks.append(Check(label, status, detail))
        suffix = f"  ({detail})" if detail else ""
        say(f"  [{status}] {label}{suffix}")
        return ok

    def warn(self, label: str, detail: str = "") -> None:
        self.checks.append(Check(label, WARN, detail))
        suffix = f"  ({detail})" if detail else ""
        say(f"  [WARN] {label}{suffix}")

    def skip(self, label: str, detail: str = "") -> None:
        self.checks.append(Check(label, SKIP, detail))
        suffix = f"  ({detail})" if detail else ""
        say(f"  [SKIP] {label}{suffix}")

    def fail(self, label: str, detail: str = "") -> None:
        self.status = FAIL
        self.checks.append(Check(label, FAIL, detail))
        suffix = f"  ({detail})" if detail else ""
        say(f"  [FAIL] {label}{suffix}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "elapsed": round(self.elapsed, 1),
            "error": self.error,
            "artifacts": self.artifacts,
            "checks": [{"label": c.label, "status": c.status, "detail": c.detail} for c in self.checks],
        }


# ── HTTP ──


@dataclass
class HttpResult:
    status: int
    text: str
    elapsed: float

    def json(self) -> Any:
        try:
            return json.loads(self.text)
        except Exception:
            return None


def post_json(url: str, payload: dict, timeout: float = 1800.0) -> HttpResult:
    t0 = time.monotonic()
    r = requests.post(url, json=payload, timeout=timeout)
    return HttpResult(r.status_code, r.text, time.monotonic() - t0)


def post_raw(url: str, data: bytes, content_type: str = "application/json",
             timeout: float = 60.0) -> HttpResult:
    t0 = time.monotonic()
    r = requests.post(url, data=data, headers={"Content-Type": content_type}, timeout=timeout)
    return HttpResult(r.status_code, r.text, time.monotonic() - t0)


def get_json(url: str, timeout: float = 10.0) -> HttpResult:
    t0 = time.monotonic()
    r = requests.get(url, timeout=timeout)
    return HttpResult(r.status_code, r.text, time.monotonic() - t0)


def is_up(base: str, timeout: float = 3.0) -> bool:
    try:
        return requests.get(f"{base}/healthz", timeout=timeout).status_code == 200
    except Exception:
        return False


# ── 422 / 400 契约断言 ──


def detail_is_array(r: HttpResult) -> bool:
    """pydantic 校验失败：detail 是数组。"""
    body = r.json()
    return isinstance(body, dict) and isinstance(body.get("detail"), list)


def detail_is_string(r: HttpResult) -> bool:
    """HTTPException：detail 是字符串。"""
    body = r.json()
    return isinstance(body, dict) and isinstance(body.get("detail"), str)


def first_error_type(r: HttpResult) -> Optional[str]:
    body = r.json()
    if isinstance(body, dict) and isinstance(body.get("detail"), list) and body["detail"]:
        return body["detail"][0].get("type")
    return None


def detail_text(r: HttpResult) -> str:
    body = r.json()
    if isinstance(body, dict):
        d = body.get("detail")
        if isinstance(d, str):
            return d
        if isinstance(d, list) and d:
            return json.dumps(d[0], ensure_ascii=False)
    return r.text[:200]


# ── 图像 ──


def decode_data_url(s: str) -> bytes:
    """接受带或不带 `data:image/png;base64,` 前缀。"""
    payload = s.split(",", 1)[1] if s.startswith("data:") else s
    return base64.b64decode(payload)


def png_size(raw: bytes) -> tuple[int, int]:
    """从 PNG 的 IHDR 直接读宽高（不依赖 PIL）。"""
    if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    w = int.from_bytes(raw[16:20], "big")
    h = int.from_bytes(raw[20:24], "big")
    return w, h


def is_png(raw: bytes) -> bool:
    return raw[:8] == b"\x89PNG\r\n\x1a\n"


def save_b64_png(data_url: str, path: Path) -> tuple[int, int]:
    raw = decode_data_url(data_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return png_size(raw)


# ── stub 检测（核心防线）──


STUB_MARKERS = {
    "engine": STUB_ENGINE,
    "fallback_tier": -1,
    "workflow_used": "",
    "prompt_synthesis.applied": False,
}


def stub_reasons(meta: dict, payload: Optional[dict] = None) -> list[str]:
    """返回「这是 stub 产物」的证据列表；空列表表示确实走了 ComfyUI。"""
    reasons: list[str] = []
    if meta.get("engine") == STUB_ENGINE:
        reasons.append(f'engine == "{STUB_ENGINE}"')
    if meta.get("engine") != "comfyui":
        reasons.append(f'engine != "comfyui"（实际 {meta.get("engine")!r}）')
    if "comfyui_prompt_id" not in meta:
        reasons.append("缺 comfyui_prompt_id")
    if meta.get("fallback_tier") == -1:
        reasons.append("fallback_tier == -1")
    if meta.get("workflow_used") == "":
        reasons.append("workflow_used 为空")
    if isinstance(meta.get("prompt_synthesis"), dict) and meta["prompt_synthesis"].get("applied") is False:
        reasons.append("prompt_synthesis.applied == False")
    if payload is not None and not payload.get("workflow_api"):
        reasons.append("响应顶层 workflow_api 为空")
    return reasons


# ── 从 workflow_api 提取 latent 尺寸 ──

_LATENT_CLASSES = ("EmptyLatentImage", "EmptySD3LatentImage")


def latent_size(workflow_api: dict) -> Optional[tuple[int, int]]:
    for node in (workflow_api or {}).values():
        if node.get("class_type") in _LATENT_CLASSES:
            ins = node.get("inputs", {})
            w, h = ins.get("width"), ins.get("height")
            if isinstance(w, int) and isinstance(h, int):
                return w, h
    return None


# ── SVG ──


def svg_structural_checks(svg_text: str) -> tuple[bool, str, int]:
    """不含渲染的纯结构校验。返回 (ok, 说明, path 数量)。"""
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(svg_text)
    except Exception as exc:
        return False, f"XML 解析失败: {exc}", 0

    if not root.tag.endswith("svg"):
        return False, f"根元素不是 <svg>（实际 {root.tag}）", 0

    vb = root.get("viewBox")
    if not vb:
        return False, "缺 viewBox", 0
    try:
        nums = [float(x) for x in re.split(r"[\s,]+", vb.strip()) if x]
    except ValueError:
        return False, f"viewBox 不可解析: {vb!r}", 0
    if len(nums) != 4 or nums[2] <= 0 or nums[3] <= 0:
        return False, f"viewBox 非法: {vb!r}", 0

    if "<image" in svg_text:
        return False, "含 <image>（位图伪装）", 0
    if "data:image" in svg_text or "base64" in svg_text:
        return False, "含 base64 位图数据", 0

    paths = root.iter("{http://www.w3.org/2000/svg}path")
    n_paths = sum(1 for _ in paths)
    if n_paths == 0:
        return False, "没有任何 <path>", 0

    return True, "ok", n_paths


def svg_bbox_area(svg_text: str) -> float:
    """解析所有 <path d="..."> 的数字，返回粗略包围盒面积（几何非退化检查）。"""
    xs: list[float] = []
    ys: list[float] = []
    for d in re.findall(r'\sd="([^"]+)"', svg_text):
        nums = [float(x) for x in re.findall(r"-?\d+\.?\d*", d) if x not in ("", "-")]
        xs.extend(nums[0::2])
        ys.extend(nums[1::2])
    if len(xs) < 2 or len(ys) < 2:
        return 0.0
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def render_svg(svg_text: str, width: int) -> Optional[bytes]:
    """把 SVG 渲染成 PNG。

    优先 `resvg_py` —— 与 vectorizer 现在的实现一致（见
    `services/vectorizer-api/app/vectorization.py:_svg_to_png_bytes`），
    它是 Rust 自包含 wheel，不依赖 cairo 原生库，交付环境 pip 装得上。
    cairosvg 仅作兜底（旧版本用的是它）。
    """
    try:
        import resvg_py  # type: ignore[import-not-found]

        return bytes(resvg_py.svg_to_bytes(svg_string=svg_text, width=width, height=None))
    except Exception:
        pass
    try:
        import cairosvg

        return cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), output_width=width)
    except Exception:
        return None


def render_coverage(png_bytes: bytes) -> float:
    """渲染结果里「非透明像素」的占比。0 表示什么都没画出来。"""
    import io as _io

    from PIL import Image
    import numpy as np

    img = Image.open(_io.BytesIO(png_bytes)).convert("RGBA")
    arr = np.array(img)
    alpha = arr[..., 3]
    return float((alpha > 8).mean())


# ── 后端生命周期 ──


def _venv_python(svc: str) -> Optional[Path]:
    p = _REPO_ROOT / "services" / svc / ".venv" / "Scripts" / "python.exe"
    return p if p.exists() else None


def _dist_exe(svc: str) -> Optional[Path]:
    d = _REPO_ROOT / "services" / svc / "dist"
    if not d.is_dir():
        return None
    for pat in ("*backend.exe", "*.exe"):
        hits = sorted(d.glob(pat))
        if hits:
            return hits[0]
    return None


class BackendManager:
    """先探测、探测不到才自拉起；谁拉起谁清理。"""

    def __init__(self, txt2img_base: str, vectorizer_base: str,
                 attach_only: bool, keep: bool, log_dir: Path) -> None:
        self.txt2img_base = txt2img_base
        self.vectorizer_base = vectorizer_base
        self.attach_only = attach_only
        self.keep = keep
        self.log_dir = log_dir
        self._spawned: list[tuple[str, subprocess.Popen]] = []
        self._logs: list[Any] = []

    def ensure(self, name: str, base: str, svc: str, port: int, timeout: float = 120.0) -> bool:
        if is_up(base):
            say(f"[环境] {name} 已在运行（端口 {port}）— 附着，退出时不关闭")
            return True
        if self.attach_only:
            say(f"[环境] {name} 未运行，且指定了 --attach")
            return False

        cmd, cwd = self._build_command(svc, port)
        if cmd is None:
            say(f"[环境] {name} 既没在运行，也找不到可执行文件（.venv 与 dist 都没有）")
            return False

        say(f"[环境] 启动 {name} ... {' '.join(str(c) for c in cmd)}")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log = open(self.log_dir / f"{svc}.log", "w", encoding="utf-8")
        self._logs.append(log)
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
                                creationflags=flags)  # type: ignore[attr-defined]
        self._spawned.append((name, proc))
        say(f"[环境] {name} pid={proc.pid}")

        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            if is_up(base):
                say(f"[环境] {name} 就绪（{time.monotonic() - t0:.0f}s）")
                return True
            if proc.poll() is not None:
                say(f"[环境] {name} 启动后立即退出（exit={proc.returncode}），见 {self.log_dir / f'{svc}.log'}")
                return False
            time.sleep(1.0)
        say(f"[环境] {name} 在 {timeout:.0f}s 内未就绪")
        return False

    @staticmethod
    def _build_command(svc: str, port: int) -> tuple[Optional[list[str]], Path]:
        svc_dir = _REPO_ROOT / "services" / svc
        py = _venv_python(svc)
        if py:
            return (
                [str(py), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
                svc_dir,
            )
        exe = _dist_exe(svc)
        if exe:
            return ([str(exe), "--host", "127.0.0.1", "--port", str(port)], exe.parent)
        return None, svc_dir

    def cleanup(self) -> None:
        for log in self._logs:
            try:
                log.close()
            except Exception:
                pass
        if not self._spawned:
            return
        if self.keep:
            say("[环境] --keep：保留本次自拉起的后端进程")
            return
        for name, proc in self._spawned:
            if proc.poll() is not None:
                continue
            say(f"[环境] 关闭 {name}（pid={proc.pid}）...")
            # 先试优雅退出
            try:
                requests.post(
                    f"{self.txt2img_base if 'txt2img' in name else self.vectorizer_base}/shutdown",
                    timeout=5,
                )
            except Exception:
                pass
            time.sleep(0.5)
            if proc.poll() is None and sys.platform == "win32":
                # /shutdown 内部走 os._exit(0)，绕过 atexit 与 _cleanup_comfyui，
                # 所以必须 taskkill /T 杀整棵进程树才能连带回收 ComfyUI。
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                   capture_output=True, timeout=20)
                except Exception:
                    pass
            elif proc.poll() is None:
                proc.terminate()


# ── ComfyUI 门禁 ──


def comfyui_ready(host: str = DEFAULT_COMFYUI_HOST, timeout: float = 5.0) -> bool:
    try:
        return requests.get(f"{host.rstrip('/')}/system_stats", timeout=timeout).status_code == 200
    except Exception:
        return False


def wait_comfyui(host: str = DEFAULT_COMFYUI_HOST, timeout: float = 300.0) -> bool:
    """等 ComfyUI 就绪，期间打印已等待秒数（冷启动可能 1-3 分钟）。"""
    t0 = time.monotonic()
    last = -1
    while time.monotonic() - t0 < timeout:
        if comfyui_ready(host):
            say(f"[环境] ComfyUI 就绪（{time.monotonic() - t0:.0f}s）")
            return True
        sec = int(time.monotonic() - t0)
        if sec // 10 != last // 10:
            say(f"[环境] 等待 ComfyUI 就绪 ... {sec}s（冷启动可能 1-3 分钟，请稍候）")
            last = sec
        time.sleep(2.0)
    return False


def comfyui_gate(scenario: ScenarioResult, host: str = DEFAULT_COMFYUI_HOST,
                 timeout: float = 300.0) -> bool:
    """生成场景的前置门禁：ComfyUI 未就绪就拒绝跑，避免静默走 stub 导致假通过。"""
    if comfyui_ready(host):
        say(f"  [gate] ComfyUI 就绪 {host}")
        return True
    say(f"  [gate] ComfyUI 未就绪，等待中（最多 {timeout:.0f}s）...")
    if wait_comfyui(host, timeout):
        return True
    scenario.fail(
        "ComfyUI 门禁",
        "ComfyUI 未就绪，拒绝在 stub 模式下跑生成场景"
        "（否则后端会静默回落 local-studio，测试将假通过）",
    )
    return False


# ── fixture 解析（沿用 run-acceptance.ps1 的 ` | ` 风格 + 第 6 列期望值）──


def split_prompt_line(line: str) -> list[str]:
    line = line.replace("﻿", "").replace("｜", "|")
    line = re.sub(r"\t\|", "|", line).replace("|\t", "|")
    line = line.strip()
    if not line or line.startswith("#"):
        return []
    return [p.strip() for p in line.split("|")]


def parse_routes_fixture(path: Path) -> list[dict[str, str]]:
    """每行：text | prompt | negative | seed | resolution | expected_workflow | expected_profile"""
    rows: list[dict[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        parts = split_prompt_line(raw)
        if not parts:
            continue
        while len(parts) < 7:
            parts.append("")
        rows.append({
            "text": parts[0],
            "prompt": parts[1],
            "negative": parts[2],
            "seed": parts[3] or "0",
            "resolution": parts[4] or "1024 x 1024",
            "expected_workflow": parts[5],
            "expected_profile": parts[6],
        })
    return rows


# ── 漂移守卫 ──


def contract_guard() -> list[str]:
    """检查复刻的常量是否与 generator.py 源码一致。不一致只 WARN，不 FAIL。

    真正的判定靠运行期的 workflow_used 断言——那是更强的信号。
    """
    warnings: list[str] = []
    if not _GENERATOR_PY.exists():
        return ["找不到 generator.py，跳过常量漂移检查"]

    src = _GENERATOR_PY.read_text(encoding="utf-8")
    for chain, names in ROUTE_CHAINS.items():
        for name in names:
            if f'"{name}"' not in src:
                warnings.append(f"generator.py 里找不到工作流名 {name!r}（{chain} 链）")
    if "_ROUTE_CHAINS" not in src:
        warnings.append("generator.py 里找不到 _ROUTE_CHAINS")
    if "_QWEN_RESOLUTIONS" not in src:
        warnings.append("generator.py 里找不到 _QWEN_RESOLUTIONS")
    return warnings
