from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class VectorConfig(BaseModel):
    smooth: int = Field(default=6, ge=1, le=10)
    threshold: int = Field(default=42, ge=1, le=100)
    colors: int = Field(default=8, ge=2, le=32)


class GeneratedImageRef(BaseModel):
    artifact_id: Optional[str] = None
    image_base64: Optional[str] = None
    file_path: Optional[str] = None


class GenerateRequest(BaseModel):
    mode: Literal["single", "batch", "vectorize"]
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


class GenerateResponse(BaseModel):
    png: str
    svg: str
    metadata: dict
