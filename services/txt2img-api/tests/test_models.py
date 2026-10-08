"""GenerationRequest 的输入校验。

提示词三个字段此前完全没有约束（无长度上限、无 strip），
裸字符串直接进入模板拼接。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import GenerationRequest


class TestTextValidation:
    def test_text_is_stripped_and_collapsed(self) -> None:
        assert GenerationRequest(text="  咖啡   Latte  ").text == "咖啡 Latte"

    def test_empty_text_is_allowed(self) -> None:
        """空 text 合法：走「只出背景 + 风格」的路径。"""
        assert GenerationRequest(text="").text == ""

    def test_text_over_max_length_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GenerationRequest(text="字" * 61)


class TestPromptValidation:
    def test_prompt_is_stripped(self) -> None:
        assert GenerationRequest(prompt="  水墨  ").prompt == "水墨"

    def test_prompt_over_max_length_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GenerationRequest(prompt="x" * 601)


class TestNegativePromptValidation:
    def test_negative_prompt_is_stripped(self) -> None:
        assert GenerationRequest(negative_prompt="  blurry  ").negative_prompt == "blurry"

    def test_negative_prompt_over_max_length_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GenerationRequest(negative_prompt="x" * 601)


class TestWorkflowValidation:
    def test_workflow_over_max_length_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GenerationRequest(workflow="w" * 65)


class TestStyleField:
    """style 是保留字段（当前不参与提示词构造），但仍应有边界。"""

    def test_default_is_default(self) -> None:
        assert GenerationRequest(style="default").style == "default"

    def test_style_over_max_length_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GenerationRequest(style="s" * 41)


class TestResolutionValidation:
    @pytest.mark.parametrize("value", ["1024x1024", "1024 x 1024", "2048X1024"])
    def test_valid_forms_normalize(self, value: str) -> None:
        expected = value.strip().lower().replace(" ", "")
        assert GenerationRequest(resolution=value).resolution == expected

    @pytest.mark.parametrize("value", ["", "invalid", "0x0", "1024", "axb", "1024x-5"])
    def test_invalid_forms_rejected(self, value: str) -> None:
        with pytest.raises(ValidationError):
            GenerationRequest(resolution=value)
