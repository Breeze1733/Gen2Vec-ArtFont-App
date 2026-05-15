from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import GenerateRequest, GenerateResponse
from .vectorizer import decode_base64_image, vectorize_art_text

app = FastAPI(
    title="FR3 Intelligent Vectorization API",
    version="0.1.0",
    description="Vector art text backend service based on OpenCV + scikit-image + vtracer + svgwrite.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _parse_resolution(resolution: str) -> tuple[int, int]:
    raw = resolution.strip().lower().replace(" ", "")
    width_str, height_str = raw.split("x", 1)
    return int(width_str), int(height_str)


def _create_mock_result(payload: GenerateRequest) -> GenerateResponse:
    width, height = _parse_resolution(payload.resolution)
    title = payload.text or "艺术字"
    subtitle = payload.prompt or "FR3 vectorization mock"
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0f766e"/>
      <stop offset="100%" stop-color="#14b8a6"/>
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" fill="#f8fafc"/>
  <text x="50%" y="45%" text-anchor="middle" fill="url(#g)" font-size="{max(42, width // 9)}" font-weight="700">{title}</text>
  <text x="50%" y="60%" text-anchor="middle" fill="#334155" font-size="{max(20, width // 24)}">{subtitle}</text>
</svg>"""
    png = "data:image/png;base64," + base64.b64encode(b"mock-png").decode("ascii")
    metadata = {
        "engine": "mock",
        "mode": payload.mode,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return GenerateResponse(png=png, svg=svg, metadata=metadata)


def _resolve_vectorize_image(payload: GenerateRequest) -> tuple[bytes, str | None, str]:
    if payload.source_type == "upload":
        if not payload.image_base64:
            raise HTTPException(
                status_code=400,
                detail="source_type=upload requires image_base64.",
            )
        try:
            return decode_base64_image(payload.image_base64), payload.image_name, "upload:image_base64"
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid image_base64: {exc}") from exc

    # source_type == generated
    generated = payload.generated_image
    if not generated:
        raise HTTPException(
            status_code=400,
            detail="source_type=generated requires generated_image object.",
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
        path = Path(generated.file_path).expanduser()
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=400, detail="generated.file_path does not exist or is not a file.")
        try:
            return path.read_bytes(), payload.image_name or path.name, "generated:file_path"
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to read generated.file_path: {exc}") from exc

    if generated.artifact_id:
        raise HTTPException(
            status_code=501,
            detail=(
                "generated.artifact_id resolver is reserved but not implemented yet. "
                "Please provide generated.image_base64 or generated.file_path for now."
            ),
        )

    raise HTTPException(
        status_code=400,
        detail=(
            "generated_image must provide one of: image_base64, file_path, artifact_id."
        ),
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "service": "fr3-intelligent-vectorization"}


@app.post("/api/v1/generate", response_model=GenerateResponse)
def generate(payload: GenerateRequest) -> GenerateResponse:
    if payload.mode != "vectorize":
        return _create_mock_result(payload)
    image_bytes, source_image_name, source_channel = _resolve_vectorize_image(payload)

    try:
        output = vectorize_art_text(image_bytes=image_bytes, vector=payload.vector.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=f"Vectorization failed: {exc}") from exc

    output["metadata"].update(
        {
            "mode": payload.mode,
            "source_type": payload.source_type,
            "source_channel": source_channel,
            "source_image_name": source_image_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return GenerateResponse(**output)
