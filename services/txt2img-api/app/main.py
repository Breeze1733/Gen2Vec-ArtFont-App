from __future__ import annotations

import logging
import os
import shutil
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

# ComfyUI portable bundle lives as a sibling of the running EXE (frozen) or
# the service checkout root (dev). Keeping it out of `_MEIPASS` lets users
# drop a 60 GB bundle next to the EXE without bloating the frozen binary.
_ENV_COMFYUI_LAUNCHER_BAT = "COMFYUI_LAUNCHER_BAT"
_COMFYUI_PORTABLE_DIRNAME = "ComfyUI_windows_portable_nvidia"
_COMFYUI_PORTABLE_INNER = "ComfyUI_windows_portable"
_GPU_BAT = "run_nvidia_gpu_fast_fp16_accumulation.bat"
_CPU_BAT = "run_cpu.bat"

app = FastAPI(
    title="txt2img-api",
    version="0.1.0",
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


def _find_embedded_python() -> Path | None:
    """Locate the embedded Python bundled with the ComfyUI portable release.

    Kept as a fallback path: when the user has the ``python_embeded`` layout
    but not the ``.bat`` launchers, we can still spawn ComfyUI via
    ``python.exe -s main.py`` directly.
    """
    candidates = [
        _get_executable_dir()
        / _COMFYUI_PORTABLE_DIRNAME
        / _COMFYUI_PORTABLE_INNER
        / "python_embeded"
        / "python.exe",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _pick_comfyui_launcher_bat() -> Path:
    """Choose the ComfyUI ``.bat`` launcher to spawn.

    Resolution order:
      1. ``COMFYUI_LAUNCHER_BAT`` env var (operator override, absolute path)
      2. NVIDIA GPU detected → ``run_nvidia_gpu_fast_fp16_accumulation.bat``
      3. Otherwise            → ``run_cpu.bat``
    """
    override = os.environ.get(_ENV_COMFYUI_LAUNCHER_BAT, "").strip()
    if override:
        bat_path = Path(override).expanduser().resolve()
        if bat_path.exists():
            return bat_path
        raise FileNotFoundError(
            f"COMFYUI_LAUNCHER_BAT is set to {bat_path!s} but the file does not exist"
        )

    portable_dir = (
        _get_executable_dir() / _COMFYUI_PORTABLE_DIRNAME / _COMFYUI_PORTABLE_INNER
    )
    if not portable_dir.is_dir():
        raise FileNotFoundError(
            f"ComfyUI portable bundle not found at {portable_dir!s}. "
            f"Place the {_COMFYUI_PORTABLE_DIRNAME}/ folder next to the running EXE "
            f"(or set {_ENV_COMFYUI_LAUNCHER_BAT} to a custom .bat)."
        )

    if _has_nvidia_gpu():
        bat = portable_dir / _GPU_BAT
        if bat.exists():
            return bat
        logger.warning("NVIDIA GPU detected but %s missing — falling back to CPU", bat)
    bat = portable_dir / _CPU_BAT
    if bat.exists():
        return bat
    raise FileNotFoundError(
        f"Neither {_GPU_BAT} nor {_CPU_BAT} found under {portable_dir!s}"
    )


def _start_comfyui_background(
    host: str = "127.0.0.1",
    port: int = 8188,
    timeout: float = 120.0,
) -> None:
    """Launch ComfyUI in a hidden process and wait for it to be ready.

    The bundled ``.bat`` launcher is preferred because it sets up the
    embedded Python path, environment variables, and fp16 fast-mode flags
    that match the portable distribution's expectations.
    """
    try:
        bat = _pick_comfyui_launcher_bat()
    except FileNotFoundError as exc:
        logger.warning("ComfyUI launcher not found — skipping auto-start (%s)", exc)
        return

    def _runner():
        try:
            logger.info("Starting ComfyUI via launcher: %s", bat)
            proc = subprocess.Popen(
                [str(bat)],
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

            start = time.monotonic()
            while time.monotonic() - start < timeout:
                if _is_port_open(host, port, timeout=0.6):
                    logger.info("ComfyUI is ready at %s:%d (pid %d)", host, port, proc.pid)
                    return
                time.sleep(1.0)

            logger.warning("Timed out waiting for ComfyUI at %s:%d", host, port)
        except Exception:
            logger.exception("Failed to start ComfyUI")

    thread = threading.Thread(target=_runner, daemon=True, name="comfyui-launcher")
    thread.start()


@app.on_event("startup")
def _on_startup() -> None:
    if os.environ.get("AUTO_START_COMFYUI", "1") == "1":
        _start_comfyui_background()

    # Pre-warm: try connecting to an already-running ComfyUI so the
    # first generate call doesn't pay the cold-start penalty.
    warmup_comfyui_connection()