from __future__ import annotations

import logging
import os
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
    )


def run() -> None:
    uvicorn.run("app.main:app", host="0.0.0.0", port=9001, reload=False)


# ── ComfyUI lifecycle ──


def _is_port_open(host: str, port: int, timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def _find_embedded_python() -> Path | None:
    """Locate the embedded Python bundled with ComfyUI portable."""
    project_root = Path(__file__).resolve().parents[2]
    candidates = [
        project_root / "ComfyUI_windows_portable_nvidia" / "ComfyUI_windows_portable" / "python_embeded" / "python.exe",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _start_comfyui_background(
    host: str = "127.0.0.1",
    port: int = 8188,
    timeout: float = 120.0,
) -> None:
    """Launch ComfyUI in a hidden process and wait for it to be ready."""
    python_exe = _find_embedded_python()
    if python_exe is None:
        logger.warning("ComfyUI embedded Python not found — skipping auto-start")
        return

    main_py = python_exe.parents[1] / "ComfyUI" / "main.py"
    if not main_py.exists():
        logger.warning("ComfyUI main.py not found at %s — skipping auto-start", main_py)
        return

    def _runner():
        try:
            logger.info("Starting ComfyUI (headless): %s", main_py)
            proc = subprocess.Popen(
                [str(python_exe), "-s", str(main_py), "--fast", "fp16_accumulation"],
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