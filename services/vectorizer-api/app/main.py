from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import VectorizeRequest, VectorizeResponse
from .image_processing import decode_base64_image, preprocess_image
from .vectorization import vectorize_image

app = FastAPI(
    title="Vectorizer API",
    version="1.0.0",
    description="Bitmap-to-SVG vectorization backend service based on OpenCV + scikit-image + vtracer + svgwrite.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _read_image_path(file_path: str, channel: str, image_name: str | None = None) -> tuple[bytes, str | None, str]:
    # Read bitmap bytes from a local path. Desktop/CLI use this path-first handoff
    # to avoid sending large base64 payloads between generation and vectorization.
    path = Path(file_path).expanduser()
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=400, detail=f"{channel} does not exist or is not a file.")
    try:
        return path.read_bytes(), image_name or path.name, channel
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read {channel}: {exc}") from exc


def _resolve_vectorize_image(payload: VectorizeRequest) -> tuple[bytes, str | None, str]:
    # Resolve bitmap bytes from either user upload or generated-pipeline source.
    if payload.source_type == "upload":
        if payload.image_path:
            return _read_image_path(payload.image_path, "upload:image_path", payload.image_name)
        if not payload.image_base64:
            raise HTTPException(status_code=400, detail="source_type=upload requires image_base64 or image_path.")
        try:
            return decode_base64_image(payload.image_base64), payload.image_name, "upload:image_base64"
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid image_base64: {exc}") from exc

    if payload.image_path:
        return _read_image_path(payload.image_path, "generated:image_path", payload.image_name)

    if payload.image_base64:
        try:
            return (
                decode_base64_image(payload.image_base64),
                payload.image_name,
                "generated:image_base64",
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid image_base64: {exc}") from exc

    generated = payload.generated_image
    if not generated:
        raise HTTPException(
            status_code=400,
            detail="source_type=generated requires image_base64 or generated_image object.",
        )

    if generated.image_base64:
        try:
            return (
                decode_base64_image(generated.image_base64),
                payload.image_name or generated.artifact_id,
                "generated:image_base64",
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid generated.image_base64: {exc}") from exc

    if generated.file_path:
        return _read_image_path(
            generated.file_path,
            "generated:file_path",
            payload.image_name or generated.artifact_id,
        )

    if generated.artifact_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "generated.artifact_id is not supported by vectorizer-api. "
                "Please provide generated.image_base64 or generated.file_path."
            ),
        )

    raise HTTPException(
        status_code=400,
        detail="generated_image must provide one of: image_base64, file_path, artifact_id.",
    )


@app.get("/healthz")
def healthz() -> dict:
    # Health probe for desktop startup checks.
    return {"ok": True, "service": "vectorizer-api"}


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


@app.post("/api/v1/vectorize", response_model=VectorizeResponse)
def vectorize(payload: VectorizeRequest) -> VectorizeResponse:
    # Main FR3 endpoint: preprocess -> transparent PNG -> SVG -> preview PNG.
    image_bytes, source_image_name, source_channel = _resolve_vectorize_image(payload)

    try:
        processed = preprocess_image(image_bytes=image_bytes, vector=payload.vector.model_dump())
        output = vectorize_image(transparent_image=processed["transparent_image"], vector=payload.vector.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Vectorization failed: {exc}") from exc

    output["metadata"].update(
        {
            "source_type": payload.source_type,
            "source_channel": source_channel,
            "source_image_name": source_image_name,
            "generation": {
                "text": payload.text or "",
                "prompt": payload.prompt or "",
                "negative": payload.negative or "",
                "resolution": payload.resolution or "",
                "seed": payload.seed if payload.seed else 0,
            },
            "preprocess": {
                "transparent_size": processed["size"],
                "png_transparency": processed.get("png_transparency"),
            },
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    response_payload = {
        "transparent_png": processed["transparent_png"],
        "preview_png": output["preview_png"],
        "png": output["preview_png"],
        "svg": output["svg"],
        "metadata": output["metadata"],
    }
    return VectorizeResponse(**response_payload)
