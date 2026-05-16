from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class GenerationRequest(BaseModel):
    prompt: str = Field(min_length=1, description="Text prompt for image generation")
    negative_prompt: str = ""
    resolution: str = "1024 x 1024"
    seed: int = 0
    style: str = "default"
    format: Literal["PNG", "PNG + SVG"] = "PNG"
    workflow: str = Field(default="", description="Workflow filename (without path/extension), e.g. 'test_z_image_turbo'. Falls back to WORKFLOW_PATH env var or txt2img_api.json")

    @field_validator("resolution")
    @classmethod
    def normalize_resolution(cls, value: str) -> str:
        normalized = value.strip().lower().replace(" ", "")
        parts = normalized.split("x")
        if len(parts) != 2:
            raise ValueError("resolution format must be like 1024x1024")
        width, height = parts
        if not width.isdigit() or not height.isdigit():
            raise ValueError("resolution width/height must be integer")
        if int(width) <= 0 or int(height) <= 0:
            raise ValueError("resolution width/height must be > 0")
        return normalized


class GenerationResponse(BaseModel):
    image_base64: str
    image_name: str
    metadata: dict