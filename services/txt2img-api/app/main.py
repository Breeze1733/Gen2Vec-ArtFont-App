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
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .generator import generate_artwork, warmup_comfyui_connection
from .models import GenerationRequest, GenerationResponse

logger = logging.getLogger(__name__)

# ComfyUI portable bundle lives as a sibling of the running EXE (frozen) or
# the service checkout root (dev). Keeping it out of `_MEIPASS` lets users
# drop a 60 GB bundle next to the EXE without bloating the frozen binary.
_ENV_COMFYUI_LAUNCHER_BAT = "COMFYUI_LAUNCHER_BAT"
# Operator override: point this at the outer directory of a ComfyUI portable
# distribution whose structure is:
#   <root>/ComfyUI_windows_portable/<launcher>.bat
# Useful when the bundle lives somewhere other than next to the EXE.
_ENV_COMFYUI_PORTABLE_ROOT = "COMFYUI_PORTABLE_ROOT"
_COMFYUI_PORTABLE_INNER = "ComfyUI_windows_portable"
_GPU_BAT = "run_nvidia_gpu_fast_fp16_accumulation.bat"
_CPU_BAT = "run_cpu.bat"
# Outer directory names we recognise for auto-discovery. Different
# distributions use slightly different folder names.
_PORTABLE_OUTER_NAMES = (
    "ComfyUI_windows_portable_nvidia",
    "ComfyUI_windows_portable",
    "ComfyUI_portable",
)

# Module-level state for the spawned ComfyUI subprocess, so the lifespan
# shutdown hook can terminate it cleanly. The lock guards concurrent
# access from the background thread and the request thread.
_comfyui_proc: subprocess.Popen | None = None
_comfyui_proc_lock = threading.Lock()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """FastAPI lifespan handler: launch ComfyUI and warm up the connection."""
    if os.environ.get("AUTO_START_COMFYUI", "1") == "1":
        _start_comfyui_background()

    # Pre-warm: try connecting to an already-running ComfyUI so the
    # first generate call doesn't pay the cold-start penalty.
    warmup_comfyui_connection()
    yield
    # Shutdown hook could be added here (e.g. terminate spawned ComfyUI).


app = FastAPI(
    title="txt2img-api",
    version="0.1.0",
    description="Text-to-image generation backend for the Development-Training workspace.",
    lifespan=lifespan,
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


def _resolve_portable_root() -> Path | None:
    """Find the outer directory of a ComfyUI portable distribution.

    Priority:
      1. ``COMFYUI_PORTABLE_ROOT`` env var (operator override)
      2. Auto-discovery: scan ``_get_executable_dir()`` for any
         name in ``_PORTABLE_OUTER_NAMES``; first match wins.

    Returns the outer directory (containing ``ComfyUI_windows_portable/``),
    or ``None`` if nothing found.
    """
    # 1. Env var override
    env_root = os.environ.get(_ENV_COMFYUI_PORTABLE_ROOT, "").strip()
    if env_root:
        root = Path(env_root).expanduser().resolve()
        if root.is_dir():
            return root
        logger.warning(
            "%s=%s does not exist or is not a directory; falling back to auto-discovery",
            _ENV_COMFYUI_PORTABLE_ROOT,
            root,
        )

    # 2. Auto-discovery
    exedir = _get_executable_dir()
    for name in _PORTABLE_OUTER_NAMES:
        candidate = exedir / name
        if candidate.is_dir():
            return candidate

    return None


def _pick_comfyui_launcher_bat() -> Path:
    """Choose the ComfyUI ``.bat`` launcher to spawn.

    Resolution order:
      1. ``COMFYUI_LAUNCHER_BAT`` env var (operator override, absolute .bat path)
      2. ``COMFYUI_PORTABLE_ROOT`` env var → ``<root>/ComfyUI_windows_portable/<bat>``
      3. Auto-discover: scan ``_get_executable_dir()`` for any
         ``_PORTABLE_OUTER_NAMES``; use first match
      4. Raise ``FileNotFoundError`` with a helpful message

    Within (2)/(3) the GPU launcher is preferred when an NVIDIA GPU is
    detected; otherwise fall back to the CPU launcher.
    """
    # 1. Operator override (absolute .bat path)
    override = os.environ.get(_ENV_COMFYUI_LAUNCHER_BAT, "").strip()
    if override:
        bat_path = Path(override).expanduser().resolve()
        if bat_path.exists():
            return bat_path
        raise FileNotFoundError(
            f"{_ENV_COMFYUI_LAUNCHER_BAT}={bat_path} does not exist"
        )

    # 2 & 3. Find the portable install root
    portable_root = _resolve_portable_root()
    if portable_root is None:
        raise FileNotFoundError(
            f"ComfyUI portable bundle not found. Set {_ENV_COMFYUI_PORTABLE_ROOT} "
            f"to a directory containing '{_COMFYUI_PORTABLE_INNER}/', or place one of "
            f"{_PORTABLE_OUTER_NAMES} next to the running EXE. "
            f"Searched: {_get_executable_dir()!s}."
        )

    # 4. Look for the launcher under portable_root/<inner>/
    portable_inner = portable_root / _COMFYUI_PORTABLE_INNER
    if not portable_inner.is_dir():
        raise FileNotFoundError(
            f"{portable_root} found but missing '{_COMFYUI_PORTABLE_INNER}/' subdir"
        )

    if _has_nvidia_gpu():
        bat = portable_inner / _GPU_BAT
        if bat.exists():
            return bat
        logger.warning("NVIDIA GPU detected but %s missing — falling back to CPU", bat)
    bat = portable_inner / _CPU_BAT
    if bat.exists():
        return bat
    raise FileNotFoundError(
        f"Neither {_GPU_BAT} nor {_CPU_BAT} found under {portable_inner}"
    )


def _start_comfyui_background(
    host: str = "127.0.0.1",
    port: int = 8188,
) -> None:
    """Launch the ComfyUI .bat launcher in a hidden background process.

    The launcher's own stdout/stderr is redirected to ``comfyui-launcher.log``
    so the user can ``tail -f`` it for progress without console spam.

    Skips spawning entirely if ``host:port`` is already accepting
    connections (a manual or orphan ComfyUI is already running); in that
    case ``_comfyui_proc`` is left as ``None`` so the lifespan shutdown
    hook does not terminate someone else's process.

    Does NOT wait for the server to be ready; request handlers should
    use ``_wait_for_comfyui_ready`` (in :mod:`app.generator`) before
    submitting a prompt.
    """
    global _comfyui_proc

    try:
        bat = _pick_comfyui_launcher_bat()
    except FileNotFoundError as exc:
        logger.warning("ComfyUI launcher not found — skipping auto-start (%s)", exc)
        return

    def _runner():
        global _comfyui_proc
        try:
            # Pre-flight: if port already accepts connections, someone
            # else is serving ComfyUI. Don't spawn a duplicate, and don't
            # save the proc handle (so _stop_comfyui doesn't kill
            # someone else's process).
            if _is_port_open(host, port, timeout=0.5):
                logger.info(
                    "ComfyUI already running at %s:%d, skipping auto-start",
                    host, port,
                )
                return

            # Capture launcher output to a log file (NOT console). The
            # user can tail -f this file to see model-loading progress.
            log_path = _get_executable_dir() / "comfyui-launcher.log"
            log_file = open(log_path, "ab", buffering=0)  # unbuffered append

            logger.info("Starting ComfyUI via launcher: %s", bat)
            logger.info("Launcher output: %s", log_path)

            with _comfyui_proc_lock:
                _comfyui_proc = subprocess.Popen(
                    [str(bat)],
                    shell=True,
                    stdout=log_file,
                    stderr=log_file,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                proc = _comfyui_proc

            # Quick health check: if the process dies within 5s, surface
            # the error immediately. Otherwise assume it's still booting
            # and let _wait_for_comfyui_ready handle the wait.
            for _ in range(5):
                time.sleep(1.0)
                if proc.poll() is not None:
                    logger.error(
                        "ComfyUI process exited prematurely with code %s. "
                        "See %s for details.",
                        proc.returncode, log_path,
                    )
                    with _comfyui_proc_lock:
                        _comfyui_proc = None
                    return
        except Exception:
            logger.exception("Failed to start ComfyUI")

    thread = threading.Thread(target=_runner, daemon=True, name="comfyui-launcher")
    thread.start()
