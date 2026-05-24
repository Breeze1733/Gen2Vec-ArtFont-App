from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import VectorizeRequest, VectorizeResponse
from .image_processing import decode_base64_image, preprocess_image
from .vectorization import vectorize_image

app = FastAPI(
    title="Vectorizer API",
    version="0.2.0",
    description="Bitmap-to-SVG vectorization backend service based on OpenCV + scikit-image + vtracer + svgwrite.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_vectorize_image(payload: VectorizeRequest) -> tuple[bytes, str | None, str]:
    # Resolve bitmap bytes from either user upload or generated-pipeline source.
    if payload.source_type == "upload":
        if not payload.image_base64:
            raise HTTPException(status_code=400, detail="source_type=upload requires image_base64.")
        try:
            return decode_base64_image(payload.image_base64), payload.image_name, "upload:image_base64"
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid image_base64: {exc}") from exc

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
        path = Path(generated.file_path).expanduser()
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=400, detail="generated.file_path does not exist or is not a file.")
        try:
            return path.read_bytes(), payload.image_name or path.name, "generated:file_path"
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to read generated.file_path: {exc}") from exc

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
