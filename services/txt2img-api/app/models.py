from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# 输入长度上限。text 是「艺术字要画的字」，远短于风格描述与负面词。
_MAX_TEXT = 60
_MAX_PROMPT = 600
_MAX_NEGATIVE = 600
_MAX_WORKFLOW = 64
_MAX_STYLE = 40
_MAX_RESOLUTION = 32


class GenerationRequest(BaseModel):
    text: str = Field(
        default="",
        max_length=_MAX_TEXT,
        description="Text content to render (Chinese, English, numbers). Empty is allowed.",
    )
    prompt: str = Field(
        default="",
        max_length=_MAX_PROMPT,
        description="Style description (e.g. 'calligraphy, gold gradient')",
    )
    negative_prompt: str = Field(default="", max_length=_MAX_NEGATIVE)
    resolution: str = Field(default="1024 x 1024", max_length=_MAX_RESOLUTION)
    seed: int = 0
    style: str = Field(
        default="default",
        max_length=_MAX_STYLE,
        description="Reserved. Currently recorded in metadata only; it does not affect generation.",
    )
    format: Literal["PNG", "PNG + SVG"] = "PNG"
    workflow: str = Field(
        default="",
        max_length=_MAX_WORKFLOW,
        description=(
            "Workflow filename (without path/extension), e.g. 'flux_schnell'. "
            "Empty falls back to content-based routing; WORKFLOW_PATH env var overrides both."
        ),
    )

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        """strip 并把内部空白折叠为单空格——提示词以此为准渲染。"""
        return " ".join(value.split())

    @field_validator("prompt", "negative_prompt", "style")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

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
    workflow_api: Optional[dict] = None
    model_dependencies: Optional[dict] = None
