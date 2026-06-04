from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.generator import (
    _DEFAULT_NEGATIVE,
    _FLUX_BG_SUPPRESS,
    _ZIMAGE_BG_SUPPRESS,
    _build_flux_prompt,
    _build_negative_prompt,
    _build_zimage_prompt,
    _call_comfyui_api,
    _find_nodes_by_class,
    _load_workflow,
    _local_stub_generate,
    _parse_resolution,
    _patch_workflow,
    _resolve_workflow_path,
    generate_artwork,
)
from app.models import GenerationRequest


# ── Fixtures ──


@pytest.fixture
def workflow() -> dict:
    """Load the bundled workflow template."""
    path = _resolve_workflow_path("test_z_image_turbo")
    return _load_workflow(path)


@pytest.fixture
def sample_request() -> GenerationRequest:
    return GenerationRequest(
        prompt="晨曦之城",
        negative_prompt="模糊, 断裂",
        resolution="1024 x 1024",
        seed=42,
        style="neon",
        format="PNG",
    )


# ── _resolve_workflow_path ──


class TestResolveWorkflowPath:
    def test_default_path_points_to_existing_file(self) -> None:
        path = _resolve_workflow_path("test_z_image_turbo")
        assert path.exists(), f"Workflow file should exist at {path}"
        assert path.suffix == ".json"

    def test_default_without_name_uses_txt2img_api(self) -> None:
        path = _resolve_workflow_path()
        assert path.name == "txt2img_api.json"

    def test_appends_json_extension(self) -> None:
        path = _resolve_workflow_path("my_workflow")
        assert path.name == "my_workflow.json"

    def test_preserves_explicit_extension(self) -> None:
        path = _resolve_workflow_path("flow.json")
        assert path.name == "flow.json"


# ── _load_workflow ──


class TestLoadWorkflow:
    def test_loads_valid_workflow(self, workflow: dict) -> None:
        assert isinstance(workflow, dict)
        assert len(workflow) > 0

    def test_every_node_has_class_type_and_inputs(self, workflow: dict) -> None:
        for node_id, node in workflow.items():
            assert "class_type" in node, f"Node {node_id} missing class_type"
            assert "inputs" in node, f"Node {node_id} missing inputs"

    def test_raises_on_missing_file(self) -> None:
        with pytest.raises(FileNotFoundError):
            _load_workflow(Path("/nonexistent/workflow.json"))

    def test_raises_on_invalid_json(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("not json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            _load_workflow(f)

    def test_raises_on_non_dict_json(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text('["not", "a", "dict"]', encoding="utf-8")
        with pytest.raises(ValueError, match="must be a JSON object"):
            _load_workflow(f)

    def test_raises_on_missing_class_type(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text('{"1": {"inputs": {}}}', encoding="utf-8")
        with pytest.raises(ValueError, match="missing 'class_type'"):
            _load_workflow(f)


# ── _find_nodes_by_class ──


class TestFindNodesByClass:
    def test_finds_clip_text_encode(self, workflow: dict) -> None:
        nodes = _find_nodes_by_class(workflow, "CLIPTextEncode")
        assert len(nodes) >= 1

    def test_finds_ksampler(self, workflow: dict) -> None:
        nodes = _find_nodes_by_class(workflow, "KSampler")
        assert len(nodes) == 1

    def test_finds_save_image(self, workflow: dict) -> None:
        nodes = _find_nodes_by_class(workflow, "SaveImage")
        assert len(nodes) == 1

    def test_finds_empty_sd3_latent(self, workflow: dict) -> None:
        nodes = _find_nodes_by_class(workflow, "EmptySD3LatentImage")
        assert len(nodes) == 1

    def test_returns_empty_for_unknown_class(self, workflow: dict) -> None:
        nodes = _find_nodes_by_class(workflow, "NonExistentNode")
        assert nodes == []

    def test_returns_node_id_and_data(self, workflow: dict) -> None:
        nodes = _find_nodes_by_class(workflow, "SaveImage")
        nid, node = nodes[0]
        assert isinstance(nid, str)
        assert node["class_type"] == "SaveImage"


# ── _patch_workflow ──


class TestPatchWorkflow:
    def test_sets_positive_prompt(self, workflow: dict, sample_request: GenerationRequest) -> None:
        patched = _patch_workflow(workflow, sample_request)
        clip_nodes = _find_nodes_by_class(patched, "CLIPTextEncode")
        assert clip_nodes[0][1]["inputs"]["text"] == "晨曦之城"

    def test_sets_seed(self, workflow: dict, sample_request: GenerationRequest) -> None:
        patched = _patch_workflow(workflow, sample_request)
        ksamplers = _find_nodes_by_class(patched, "KSampler")
        assert ksamplers[0][1]["inputs"]["seed"] == 42

    def test_sets_resolution(self, workflow: dict, sample_request: GenerationRequest) -> None:
        patched = _patch_workflow(workflow, sample_request)
        # User's workflow uses EmptySD3LatentImage
        latents = _find_nodes_by_class(patched, "EmptySD3LatentImage")
        assert latents[0][1]["inputs"]["width"] == 1024
        assert latents[0][1]["inputs"]["height"] == 1024

    def test_does_not_mutate_original(self, workflow: dict, sample_request: GenerationRequest) -> None:
        original_text = _find_nodes_by_class(workflow, "CLIPTextEncode")[0][1]["inputs"]["text"]
        _patch_workflow(workflow, sample_request)
        assert _find_nodes_by_class(workflow, "CLIPTextEncode")[0][1]["inputs"]["text"] == original_text

    def test_sets_seed_zero(self, workflow: dict) -> None:
        req = GenerationRequest(prompt="test", seed=0)
        patched = _patch_workflow(workflow, req)
        ksamplers = _find_nodes_by_class(patched, "KSampler")
        assert ksamplers[0][1]["inputs"]["seed"] == 0


# ── _parse_resolution ──


class TestParseResolution:
    @pytest.mark.parametrize(
        ("input_str", "expected"),
        [
            ("1024x1024", (1024, 1024)),
            ("1024 x 1024", (1024, 1024)),
            ("2048x1024", (2048, 1024)),
            ("1024 X 768", (1024, 768)),
            ("", (1024, 1024)),
            ("invalid", (1024, 1024)),
            ("0x0", (1024, 1024)),
        ],
    )
    def test_parses_various_formats(self, input_str: str, expected: tuple[int, int]) -> None:
        assert _parse_resolution(input_str) == expected


# ── _local_stub_generate ──


class TestLocalStubGenerate:
    def test_returns_data_url(self, sample_request: GenerationRequest) -> None:
        artifact = _local_stub_generate(sample_request)
        assert artifact.image_base64.startswith("data:image/png;base64,")

    def test_returns_png_extension(self, sample_request: GenerationRequest) -> None:
        artifact = _local_stub_generate(sample_request)
        assert artifact.image_name.endswith(".png")

    def test_includes_metadata(self, sample_request: GenerationRequest) -> None:
        artifact = _local_stub_generate(sample_request)
        assert artifact.metadata["engine"] == "local-studio"
        assert artifact.metadata["prompt"] == "晨曦之城"
        assert artifact.metadata["seed"] == 42

    def test_deterministic_seed(self) -> None:
        req = GenerationRequest(prompt="test", seed=123)
        a1 = _local_stub_generate(req)
        a2 = _local_stub_generate(req)
        assert a1.metadata["seed"] == a2.metadata["seed"] == 123

    def test_slug_contains_prompt_text(self) -> None:
        req = GenerationRequest(prompt="hello-world")
        artifact = _local_stub_generate(req)
        assert "hello-world" in artifact.image_name


# ── generate_artwork (fallback) ──


class TestGenerateArtwork:
    def test_metadata_includes_fallback_fields(self, sample_request: GenerationRequest) -> None:
        """无论走 ComfyUI 还是 stub，metadata 必须包含降级链追踪字段。"""
        artifact = generate_artwork(sample_request)
        assert artifact.image_base64.startswith("data:image/png;base64,")
        assert artifact.image_name.endswith(".png")
        assert artifact.metadata["engine"] in ("comfyui", "local-studio")
        assert "fallback_tier" in artifact.metadata
        assert "workflow_used" in artifact.metadata
        assert "attempted_workflows" in artifact.metadata

    def test_stub_metadata_matches_request(self, sample_request: GenerationRequest) -> None:
        artifact = generate_artwork(sample_request)
        assert artifact.metadata["prompt"] == "晨曦之城"
        assert artifact.metadata["seed"] == 42
        assert artifact.metadata["resolution"] == "1024x1024"


# ── Prompt template: background suppression ──


class TestDefaultNegativePrompt:
    """Verify _DEFAULT_NEGATIVE contains background-related terms."""

    def test_contains_background_terms(self) -> None:
        assert "complex background" in _DEFAULT_NEGATIVE
        assert "scenery background" in _DEFAULT_NEGATIVE
        assert "landscape background" in _DEFAULT_NEGATIVE
        assert "indoor scene" in _DEFAULT_NEGATIVE
        assert "outdoor scene" in _DEFAULT_NEGATIVE

    def test_retains_original_quality_terms(self) -> None:
        assert "broken strokes" in _DEFAULT_NEGATIVE
        assert "missing strokes" in _DEFAULT_NEGATIVE
        assert "wrong characters" in _DEFAULT_NEGATIVE
        assert "garbled text" in _DEFAULT_NEGATIVE


class TestBuildFluxPrompt:
    """Verify _build_flux_prompt includes background suppression."""

    def test_chinese_text_includes_bg_suppress(self) -> None:
        result = _build_flux_prompt("测试文字", "neon style")
        assert "plain solid background" in result
        assert "no complex scene" in result

    def test_english_text_includes_bg_suppress(self) -> None:
        result = _build_flux_prompt("Hello World", "gold")
        assert "plain solid background" in result

    def test_digits_only_includes_bg_suppress(self) -> None:
        result = _build_flux_prompt("123", "digital")
        assert "plain solid background" in result

    def test_background_suppress_comes_before_style(self) -> None:
        result = _build_flux_prompt("测试", "neon style")
        bg_pos = result.index("plain solid background")
        style_pos = result.index("neon style")
        assert bg_pos < style_pos, "背景抑制应在风格提示词之前"

    def test_style_prompt_still_present(self) -> None:
        result = _build_flux_prompt("测试", "neon style")
        assert "neon style" in result

    def test_empty_text_returns_style_only(self) -> None:
        result = _build_flux_prompt("", "minimal")
        assert result == "minimal"
        assert "plain solid background" not in result


class TestBuildZimagePrompt:
    """Verify _build_zimage_prompt includes background suppression."""

    def test_chinese_text_includes_bg_suppress(self) -> None:
        result = _build_zimage_prompt("测试文字", "科技风")
        assert "纯色背景" in result
        assert "无复杂场景" in result

    def test_english_text_includes_bg_suppress(self) -> None:
        result = _build_zimage_prompt("Hello", "gold")
        assert "纯色背景" in result

    def test_background_suppress_comes_before_style(self) -> None:
        result = _build_zimage_prompt("测试", "科技风")
        bg_pos = result.index("纯色背景")
        style_pos = result.index("科技风")
        assert bg_pos < style_pos, "背景抑制应在风格提示词之前"

    def test_style_prompt_still_present(self) -> None:
        result = _build_zimage_prompt("测试", "科技风")
        assert "科技风" in result

    def test_empty_text_returns_style_only(self) -> None:
        result = _build_zimage_prompt("", "minimal")
        assert result == "minimal"
        assert "纯色背景" not in result


class TestBuildNegativePrompt:
    """Verify _build_negative_prompt merging logic."""

    def test_returns_default_when_empty(self) -> None:
        result = _build_negative_prompt("")
        assert result == _DEFAULT_NEGATIVE

    def test_merges_user_negative(self) -> None:
        result = _build_negative_prompt("extra term")
        assert _DEFAULT_NEGATIVE in result
        assert "extra term" in result
        assert result.endswith("extra term")

    def test_trims_user_input(self) -> None:
        result = _build_negative_prompt("  padded  ")
        assert "padded" in result


# ── Module-level constants ──


class TestBackgroundSuppressConstants:
    """Verify background suppression constants are non-empty strings."""

    def test_flux_bg_suppress_is_string(self) -> None:
        assert isinstance(_FLUX_BG_SUPPRESS, str)
        assert len(_FLUX_BG_SUPPRESS) > 0

    def test_zimage_bg_suppress_is_string(self) -> None:
        assert isinstance(_ZIMAGE_BG_SUPPRESS, str)
        assert len(_ZIMAGE_BG_SUPPRESS) > 0
