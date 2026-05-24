from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class VectorConfig(BaseModel):
    # Frontend vectorization controls (6 params + 4 presets).
    preset: Literal["clean", "balanced", "detailed", "ultra"] = "balanced"
    color_precision: int | None = Field(default=None, ge=1, le=8)
    filter_speckle: int | None = Field(default=None, ge=0, le=64)
    corner_threshold: int | None = Field(default=None, ge=1, le=180)
    length_threshold: int | None = Field(default=None, ge=1, le=64)
    layer_difference: int | None = Field(default=None, ge=1, le=64)
    scale: int | None = Field(default=None, ge=1, le=4, description="upscale factor")
    evaluate_quality: bool = True


class GeneratedImageRef(BaseModel):
    # Generated-image source (reserved for pipeline handoff).
    artifact_id: Optional[str] = None
    image_base64: Optional[str] = None
    file_path: Optional[str] = None


class VectorizeRequest(BaseModel):
    # "upload": user-provided bitmap; "generated": pipeline-produced bitmap.
    source_type: Literal["upload", "generated"] = "upload"
    text: str = ""
    prompt: str = ""
    negative: str = ""
    resolution: str = "1024 x 1024"
    format: str = "PNG + SVG"
    seed: int = 0
    vector: VectorConfig = Field(default_factory=VectorConfig)
    image_base64: Optional[str] = None
    image_name: Optional[str] = None
    generated_image: Optional[GeneratedImageRef] = None

    @field_validator("resolution")
    @classmethod
    def validate_resolution(cls, value: str) -> str:
        # Normalize resolution like "1024 x 1024" -> "1024x1024".
        value = value.strip().lower().replace(" ", "")
        parts = value.split("x")
        if len(parts) != 2:
            raise ValueError("resolution format must be like 1024x1024")
        width, height = parts
        if not (width.isdigit() and height.isdigit()):
            raise ValueError("resolution width/height must be integer")
        if int(width) <= 0 or int(height) <= 0:
            raise ValueError("resolution width/height must be > 0")
        return value


class VectorizeResponse(BaseModel):
    # PNG preview (data URL), SVG text and structured metadata.
    png: str
    svg: str
    metadata: dict
