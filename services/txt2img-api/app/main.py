from __future__ import annotations

import atexit
import configparser
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .generator import generate_artwork, warmup_comfyui_connection
from .models import GenerationRequest, GenerationResponse

logger = logging.getLogger(__name__)

# 存储 ComfyUI 子进程引用，用于 Ctrl+C 时自动清理
_comfyui_proc: subprocess.Popen | None = None


def _cleanup_comfyui() -> None:
    """退出时强制终止 ComfyUI 子进程树。"""
    global _comfyui_proc
    if _comfyui_proc is None or _comfyui_proc.poll() is not None:
        return
    logger.info("正在关闭 ComfyUI (pid %d)...", _comfyui_proc.pid)
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(_comfyui_proc.pid)],
            capture_output=True,
        )
    else:
        _comfyui_proc.terminate()
        try:
            _comfyui_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _comfyui_proc.kill()
            _comfyui_proc.wait(timeout=3)
    logger.info("ComfyUI 已关闭")


atexit.register(_cleanup_comfyui)

# Ctrl+C 时先清理再退出（Windows 上 atexit 也生效，这里是双保险）
def _signal_handler(signum: int, frame: object) -> None:
    _cleanup_comfyui()
    sys.exit(0)


signal.signal(signal.SIGINT, _signal_handler)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, _signal_handler)


# ComfyUI portable bundle lives as a sibling of the running EXE (frozen) or
# the service checkout root (dev). Keeping it out of `_MEIPASS` lets users
# drop a 60 GB bundle next to the EXE without bloating the frozen binary.
_ENV_COMFYUI_LAUNCHER_BAT = "COMFYUI_LAUNCHER_BAT"
_ENV_COMFYUI_NETWORK_MODE = "COMFYUI_NETWORK_MODE"
_DEFAULT_NETWORK_MODE = "offline"
_COMFYUI_PORTABLE_DIRNAME = "ComfyUI_windows_portable_nvidia"
_COMFYUI_PORTABLE_INNER = "ComfyUI_windows_portable"

app = FastAPI(
    title="txt2img-api",
    version="0.3.0",
    description="Text-to-image generation backend for the Development-Training workspace.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "service": "txt2img-api"}


@app.post("/shutdown")
def shutdown() -> dict:
    """优雅关闭服务。

    Electron / 启动管理器在退出前调用此接口，确保后端进程正常终止。
    在独立线程中延迟退出，以便 HTTP 响应能先返回给调用方。
    """

    def _shutdown() -> None:
        import time as _time
        _time.sleep(0.2)  # 等待 HTTP 响应发送完成
        os._exit(0)

    threading.Thread(target=_shutdown, daemon=True, name="shutdown").start()
    return {"ok": True, "message": "Shutting down..."}


@app.post("/api/v1/txt2img", response_model=GenerationResponse)
def generate(payload: GenerationRequest) -> GenerationResponse:
    artifact = generate_artwork(payload)
    return GenerationResponse(
        image_base64=artifact.image_base64,
        image_name=artifact.image_name,
        metadata=artifact.metadata,
        workflow_api=artifact.workflow_api,
        model_dependencies=artifact.model_dependencies,
    )


def run() -> None:
    """Entry point for ``txt2img-api`` console script (used by uv / pip)."""
    uvicorn.run(app, host="0.0.0.0", port=9001, reload=False)


# ── ComfyUI lifecycle ──


def _get_executable_dir() -> Path:
    """Return the directory containing the running binary.

    * Frozen (PyInstaller): the folder that contains ``txt2img-backend.exe``.
    * Dev: the ``txt2img-api/`` service checkout (where ``pyproject.toml`` lives).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _is_port_open(host: str, port: int, timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _has_nvidia_gpu() -> bool:
    """Return True if an NVIDIA GPU + driver is reachable on this machine."""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return False
    try:
        result = subprocess.run(
            [nvidia_smi],
            capture_output=True,
            timeout=3.0,
        )
        return result.returncode == 0
    except Exception:
        return False


def _ensure_comfyui_offline_config(portable_dir: Path) -> None:
    """Set ComfyUI-Manager ``network_mode`` before launch to skip online checks.

    Reads the existing ``config.ini`` (if any), updates only the
    ``network_mode`` key, and writes it back.  The target mode is controlled
    by the ``COMFYUI_NETWORK_MODE`` environment variable (default ``"offline"``).
    """
    network_mode = os.environ.get(_ENV_COMFYUI_NETWORK_MODE, _DEFAULT_NETWORK_MODE)
    config_path = portable_dir / "ComfyUI" / "user" / "__manager" / "config.ini"

    config = configparser.ConfigParser()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        config.read(str(config_path), encoding="utf-8")

    if not config.has_section("default"):
        config.add_section("default")

    old = config.get("default", "network_mode", fallback=None)
    if old != network_mode:
        config.set("default", "network_mode", network_mode)
        with open(str(config_path), "w", encoding="utf-8") as f:
            config.write(f)
        logger.info(
            "ComfyUI-Manager network_mode set to %r (was %r)", network_mode, old
        )


def _build_comfyui_command(portable_dir: Path) -> list[str]:
    """Build the ComfyUI command line using the embedded Python.

    Skips ``.bat`` launchers so we can inject ``--disable-api-nodes`` and
    other flags directly.
    """
    python_exe = portable_dir / "python_embeded" / "python.exe"
    if not python_exe.exists():
        raise FileNotFoundError(f"Embedded Python not found: {python_exe}")

    cmd: list[str] = [
        str(python_exe),
        "-s",
        os.path.join("ComfyUI", "main.py"),
        "--windows-standalone-build",
        "--disable-auto-launch",
        "--disable-api-nodes",
    ]

    if _has_nvidia_gpu():
        cmd.extend(["--fast", "fp16_accumulation"])
    else:
        cmd.append("--cpu")

    return cmd


def _launch_and_wait(
    cmd: Path | list[str],
    host: str,
    port: int,
    timeout: float,
    cwd: Path,
) -> None:
    """Spawn ComfyUI subprocess and poll until the API is reachable."""
    global _comfyui_proc
    try:
        if isinstance(cmd, Path):
            # .bat launcher — needs shell
            proc = subprocess.Popen(
                [str(cmd)],
                shell=True,
                cwd=str(cwd),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        else:
            # Direct command list
            proc = subprocess.Popen(
                cmd,
                shell=False,
                cwd=str(cwd),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

        _comfyui_proc = proc  # 保存引用，供 Ctrl+C 时清理

        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if _is_port_open(host, port, timeout=0.6):
                logger.info(
                    "ComfyUI is ready at %s:%d (pid %d)", host, port, proc.pid
                )
                return
            time.sleep(1.0)

        logger.warning("Timed out waiting for ComfyUI at %s:%d", host, port)
    except Exception:
        logger.exception("Failed to start ComfyUI")


def _start_comfyui_background(
    host: str = "127.0.0.1",
    port: int = 8188,
    timeout: float = 120.0,
) -> None:
    """Launch ComfyUI in a hidden process and wait for it to be ready.

    * If ``COMFYUI_LAUNCHER_BAT`` is set, that ``.bat`` is used as-is
      (operator escape hatch).
    * Otherwise the embedded ``python_embeded/python.exe`` is invoked
      directly with ``--disable-api-nodes``, and ComfyUI-Manager's
      ``config.ini`` is patched to ``network_mode = offline`` before
      launch for fast cold-start.
    """
    # ── COMFYUI_LAUNCHER_BAT override (escape hatch) ──
    override = os.environ.get(_ENV_COMFYUI_LAUNCHER_BAT, "").strip()
    if override:
        bat_path = Path(override).expanduser().resolve()
        if not bat_path.exists():
            logger.warning(
                "COMFYUI_LAUNCHER_BAT is set but file not found: %s", bat_path
            )
            return
        logger.info("Starting ComfyUI via override launcher: %s", bat_path)
        thread = threading.Thread(
            target=_launch_and_wait,
            args=(bat_path, host, port, timeout, bat_path.parent),
            daemon=True,
            name="comfyui-launcher",
        )
        thread.start()
        return

    # ── Default: locate portable bundle ──
    portable_dir = (
        _get_executable_dir() / _COMFYUI_PORTABLE_DIRNAME / _COMFYUI_PORTABLE_INNER
    )
    if not portable_dir.is_dir():
        logger.warning(
            "ComfyUI portable bundle not found at %s — skipping auto-start. "
            "Place the %s/ folder next to the running EXE "
            "(or set %s to a custom .bat).",
            portable_dir,
            _COMFYUI_PORTABLE_DIRNAME,
            _ENV_COMFYUI_LAUNCHER_BAT,
        )
        return

    # ── Patch ComfyUI-Manager config for fast offline startup ──
    try:
        _ensure_comfyui_offline_config(portable_dir)
    except Exception:
        logger.exception("Failed to patch ComfyUI-Manager config — continuing anyway")

    # ── Build command line directly (skip .bat for control over flags) ──
    try:
        cmd = _build_comfyui_command(portable_dir)
        logger.info("Starting ComfyUI: %s", " ".join(cmd))
    except FileNotFoundError as exc:
        logger.warning("Cannot build ComfyUI command: %s", exc)
        return

    thread = threading.Thread(
        target=_launch_and_wait,
        args=(cmd, host, port, timeout, portable_dir),
        daemon=True,
        name="comfyui-launcher",
    )
    thread.start()


@app.on_event("startup")
def _on_startup() -> None:
    if os.environ.get("AUTO_START_COMFYUI", "1") == "1":
        _start_comfyui_background()

    # Pre-warm: try connecting to an already-running ComfyUI so the
    # first generate call doesn't pay the cold-start penalty.
    warmup_comfyui_connection()