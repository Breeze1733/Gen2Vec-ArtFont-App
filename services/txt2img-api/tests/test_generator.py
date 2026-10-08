from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

import pytest

import app.generator as generator

from app.generator import (
    _DEFAULT_NEGATIVE,
    _FLUX_BG_SUPPRESS,
    _FLUX_PROFILE,
    _INVERSION_RULES,
    _ZIMAGE_BG_SUPPRESS,
    _ZIMAGE_PROFILE,
    _analyze_text,
    _build_flux_prompt,
    _build_negative_prompt,
    _build_zimage_prompt,
    _call_comfyui_api,
    _classify_text,
    _detect_layout_intent,
    _find_nodes_by_class,
    _invert_negative,
    _load_workflow,
    _local_stub_generate,
    _node_sort_key,
    _parse_resolution,
    _patch_workflow,
    _probe_negative_capability,
    _resolve_conditioning_nodes,
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
        """sample_request 的 text 为空，正向串 = 背景抑制 + 风格（不再短路）。"""
        patched = _patch_workflow(workflow, sample_request)
        clip_nodes = _find_nodes_by_class(patched, "CLIPTextEncode")
        text = clip_nodes[0][1]["inputs"]["text"]
        assert _ZIMAGE_BG_SUPPRESS in text
        assert "晨曦之城" in text
        assert text != "晨曦之城"

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


# ── _classify_text ──


class TestClassifyText:
    """文本分类只统计字母，数字/符号/空白不参与判定。"""

    @pytest.mark.parametrize("text", ["满庭芳", "念奴娇", "醉太平", "墨心堂"])
    def test_pure_chinese(self, text: str) -> None:
        assert _classify_text(text) == "chinese"

    @pytest.mark.parametrize("text", ["ICE CRUSH", "TECHNO CORE", "VINTAGE CAFE"])
    def test_pure_english(self, text: str) -> None:
        assert _classify_text(text) == "english"

    @pytest.mark.parametrize(
        "text",
        [
            "咖啡 Latte 2.0",
            "溯源 Source Code",
            "汇智 AI Lab",
            "灵动 UI Design",
            "冰川 Ice 100%",
        ],
    )
    def test_mixed_chinese_and_latin(self, text: str) -> None:
        assert _classify_text(text) == "mixed"

    @pytest.mark.parametrize("text", ["冰川 100%", "满庭芳 2026"])
    def test_digits_are_invisible_to_detection(self, text: str) -> None:
        """中文+数字（无拉丁字母）仍算纯中文。"""
        assert _classify_text(text) == "chinese"

    @pytest.mark.parametrize("text", ["2026", "100%", "3.14", "!!!", "", "   ", "---"])
    def test_no_letters_falls_back_to_english(self, text: str) -> None:
        """无字母（纯数字/符号/空）并入英文链，与既有行为一致。"""
        assert _classify_text(text) == "english"


# ── _analyze_text / TextAnalysis ──


class TestTextAnalysis:
    """统一文本分析：路由与模板共用的唯一真相源。

    residue 永不包含汉字，这是修复「文字被渲染两遍」的关键。
    """

    SAMPLES = [
        "满庭芳", "念奴娇", "醉太平", "墨心堂",
        "ICE CRUSH", "TECHNO CORE", "VINTAGE CAFE",
        "咖啡 Latte 2.0", "溯源 Source Code", "汇智 AI Lab",
        "灵动 UI Design", "冰川 Ice 100%", "幻影 Phantom X",
        "单依纯 X", "冰川 100%", "满庭芳 2026",
        "2026", "100%", "3.14", "!!!", "", "   ", "---",
        "咪哄之风 98% hey you", "单依纯 0 egg",
    ]

    def test_classify_is_thin_wrapper(self) -> None:
        """_classify_text 必须与 TextAnalysis.script 逐位一致。"""
        for s in self.SAMPLES:
            assert _classify_text(s) == _analyze_text(s).script, s

    def test_residue_drops_all_hanzi(self) -> None:
        assert _analyze_text("咪哄之风 98% hey you").residue == "98% hey you"

    def test_residue_of_pure_chinese_is_empty(self) -> None:
        assert _analyze_text("满庭芳").residue == ""

    def test_residue_keeps_latin_and_digits(self) -> None:
        assert _analyze_text("咖啡 Latte 2.0").residue == "Latte 2.0"
        assert _analyze_text("冰川 Ice 100%").residue == "Ice 100%"

    def test_residue_of_single_latin_letter(self) -> None:
        """缺陷 2 的窄条件：拉丁片段最长仅为 1 时，旧模板会把它丢掉。"""
        a = _analyze_text("单依纯 X")
        assert a.residue == "X"
        assert a.script == "mixed"
        assert a.max_latin_run == 1

    def test_residue_never_contains_hanzi(self) -> None:
        for s in ["咪哄之风 98% hey you", "单依纯 0 egg", "咖啡 Latte 2.0", "满庭芳"]:
            assert not re.search(r"[一-鿿]", _analyze_text(s).residue), s

    def test_hanzi_spaced_is_single_space(self) -> None:
        assert _analyze_text("咖啡 Latte 2.0").hanzi_spaced == "咖 啡"
        assert _analyze_text("咪哄之风 98% hey you").hanzi_spaced == "咪 哄 之 风"

    def test_hanzi_count(self) -> None:
        assert _analyze_text("咪哄之风 98% hey you").hanzi_count == 4
        assert _analyze_text("满庭芳").hanzi_count == 3

    def test_symbols_dedup_and_order(self) -> None:
        assert _analyze_text("100% 3.14%").symbols == ("%", ".")

    def test_symbols_empty_without_symbols(self) -> None:
        assert _analyze_text("满庭芳").symbols == ()
        assert _analyze_text("ICE CRUSH").symbols == ()

    def test_symbols_spaced(self) -> None:
        assert _analyze_text("100% 3.14%").symbols_spaced == "% ."

    def test_is_empty(self) -> None:
        assert _analyze_text("").is_empty
        assert _analyze_text("   ").is_empty
        assert not _analyze_text("满庭芳").is_empty

    def test_stripped_collapses_internal_whitespace(self) -> None:
        assert _analyze_text("  咖啡   Latte  ").stripped == "咖啡 Latte"

    def test_analysis_is_cached(self) -> None:
        assert _analyze_text("满庭芳") is _analyze_text("满庭芳")

    def test_latin_runs(self) -> None:
        a = _analyze_text("咖啡 Latte 2.0")
        assert a.latin_runs == ("Latte",)
        assert a.has_latin

    def test_digit_runs(self) -> None:
        assert _analyze_text("咖啡 Latte 2.0").digit_runs == ("2.0",)
        assert _analyze_text("满庭芳").digit_runs == ()

    def test_script_unchanged_for_digit_symbol_inputs(self) -> None:
        for s in ["2026", "100%", "3.14", "!!!", "", "   ", "---"]:
            assert _analyze_text(s).script == "english", s


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


# ── 路由分派 ──


class TestRouting:
    """混排只走 z-image 单层链；纯中文/纯英文维持原链。"""

    @staticmethod
    def _attempted_workflows(monkeypatch: pytest.MonkeyPatch, text: str) -> list[str]:
        # 打桩 ComfyUI 边界（而非断言 mock 行为），否则在装有 ComfyUI 的
        # 机器上会真的跑一次最长 900s 的生成。断言的是真实路由产物。
        monkeypatch.setattr("app.generator._call_comfyui_api", lambda request, workflow: None)
        artifact = generate_artwork(GenerationRequest(text=text, prompt="test style"))
        return artifact.metadata["attempted_workflows"]

    def test_mixed_text_targets_z_image_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._attempted_workflows(monkeypatch, "咖啡 Latte 2.0") == ["test_z_image_turbo"]

    def test_pure_chinese_targets_qwen_chain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._attempted_workflows(monkeypatch, "满庭芳") == [
            "qwen_image_2512_gguf",
            "test_z_image_turbo",
        ]

    def test_pure_english_targets_flux_chain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self._attempted_workflows(monkeypatch, "ICE CRUSH") == [
            "flux_schnell",
            "test_z_image_turbo",
        ]


class TestMixedTextPromptTemplate:
    """提示词模板跟的是「工作流」而非「路由分类」。

    这是症状 1 修复的实际机制：把混排内容路由到 z-image 之后，必须
    拿到中文模板，否则中文笔画问题原样存在。
    """

    def test_mixed_text_gets_zimage_chinese_template(self) -> None:
        workflow = _load_workflow(_resolve_workflow_path("test_z_image_turbo"))
        req = GenerationRequest(text="咖啡 Latte 2.0", prompt="咖啡质感")
        patched = _patch_workflow(workflow, req)
        text = _find_nodes_by_class(patched, "CLIPTextEncode")[0][1]["inputs"]["text"]
        assert _ZIMAGE_BG_SUPPRESS in text
        assert _FLUX_BG_SUPPRESS not in text

    def test_mixed_text_prompt_keeps_both_scripts(self) -> None:
        workflow = _load_workflow(_resolve_workflow_path("test_z_image_turbo"))
        req = GenerationRequest(text="咖啡 Latte 2.0", prompt="咖啡质感")
        patched = _patch_workflow(workflow, req)
        text = _find_nodes_by_class(patched, "CLIPTextEncode")[0][1]["inputs"]["text"]
        assert "咖 啡" in text       # 中文逐字拆开，强调字数为 2
        assert "Latte 2.0" in text   # 英文部分独立点名
        assert '"咖啡 Latte 2.0"' not in text   # 原文整串不得出现，否则汉字被画两遍


# ── Prompt profile rendering ──


class TestPromptProfileRendering:
    """profile 化渲染：段序、内容规则、布局意图。"""

    def test_style_precedes_content_and_accuracy(self) -> None:
        """段序：背景 -> 风格 -> 版式 -> 内容 -> 约束。

        用户把布局写进 prompt（不拆字段），所以「风格段提前」就是
        「用户意图排到约束之前」的落地方式。
        """
        result = _build_flux_prompt("咖啡 Latte 2.0", "咖啡质感")
        i_bg = result.index(_FLUX_BG_SUPPRESS)
        i_style = result.index("咖啡质感")
        i_content = result.index('Chinese text "咖 啡"')
        i_accuracy = result.index("crisp letterforms")
        assert i_bg < i_style < i_content < i_accuracy

    def test_full_raw_text_is_never_quoted(self) -> None:
        """缺陷 1 守门：原始文本不得作为整体引号串出现，否则汉字会被画两遍。"""
        raw = "咖啡 Latte 2.0"
        assert f'"{raw}"' not in _build_flux_prompt(raw, "咖啡质感")

        raw2 = "咪哄之风 98% hey you"
        assert f'"{raw2}"' not in _build_zimage_prompt(raw2, "酷炫")

    def test_residue_clause_names_latin_without_hanzi(self) -> None:
        result = _build_zimage_prompt("咪哄之风 98% hey you", "酷炫")
        assert '"98% hey you"' in result      # residue 点名拉丁与数字
        assert "咪 哄 之 风" in result         # 汉字逐字拆分
        assert "咪哄之风" not in result        # 原文不再整串出现

    def test_single_latin_letter_is_named(self) -> None:
        """缺陷 2：单字母此前被模板的 [a-zA-Z]{2,} 漏掉。"""
        assert '"X"' in _build_zimage_prompt("单依纯 X", "简洁")
        assert '"X"' in _build_flux_prompt("单依纯 X", "简洁")

    def test_symbol_clause_fires_for_latin_with_symbol(self) -> None:
        result = _build_zimage_prompt("ICE CRUSH 100%", "冰霜")
        assert '包含符号"%"' in result

    def test_symbol_clause_absent_without_symbols(self) -> None:
        assert "包含符号" not in _build_zimage_prompt("满庭芳", "水墨")
        assert "includes the symbol" not in _build_flux_prompt("满庭芳", "水墨")

    def test_digits_clause_suppressed_when_residue_present(self) -> None:
        """中文+数字由 residue 一次性点名，不再另起数字子句重复强调。"""
        result = _build_zimage_prompt("冰川 100%", "冰蓝")
        assert '"100%"' in result
        assert "数字大小比例正确" not in result

    def test_digits_clause_fires_for_latin_with_digits(self) -> None:
        result = _build_zimage_prompt("ICE 2026", "冰霜")
        assert "数字大小比例正确" in result

    @pytest.mark.parametrize(
        "style",
        ["居中排版", "文字放在中间", "0在底层中间 egg小字右下角", "layout: centered", "text aligned left"],
    )
    def test_neutral_layout_when_prompt_has_layout_words(self, style: str) -> None:
        result = _build_zimage_prompt("满庭芳", style)
        assert _ZIMAGE_PROFILE.layout_neutral in result
        assert _ZIMAGE_PROFILE.layout not in result

    @pytest.mark.parametrize("style", ["水墨晕染", "墨绿色金边", "neon gradient"])
    def test_default_layout_used_when_no_intent(self, style: str) -> None:
        result = _build_zimage_prompt("满庭芳", style)
        assert _ZIMAGE_PROFILE.layout in result
        assert _ZIMAGE_PROFILE.layout_neutral not in result

    def test_no_layout_clause_for_empty_text(self) -> None:
        """没有文字就无需版式引导。"""
        result = _build_flux_prompt("", "minimal")
        assert _FLUX_PROFILE.layout not in result
        assert _FLUX_PROFILE.layout_neutral not in result

    @pytest.mark.parametrize(
        ("style", "expected"),
        [
            ("居中排版", True),
            ("文字放在中间", True),
            ("0在底层中间 egg小字右下角", True),
            ("layout: centered", True),
            ("text aligned left", True),
            ("水墨晕染", False),
            ("墨绿色金边", False),
            ("neon gradient", False),
            ("", False),
        ],
    )
    def test_layout_intent_detector_table(self, style: str, expected: bool) -> None:
        assert _detect_layout_intent(style) is expected


# ── 负面词能力探测 ──


class TestNegativeCapability:
    """负面 conditioning 是否真正生效：cfg 与节点结构是与门，两者都要看。"""

    @pytest.mark.parametrize(
        ("name", "effective", "reason", "cfg", "neg_node"),
        [
            # cfg=1.0 使负面 conditioning 被忽略，尽管节点 9 是正常的文本节点
            ("flux_schnell", False, "cfg_too_low", 1.0, "9"),
            # 唯一 cfg>1 的工作流，负面真正生效
            ("qwen_image_2512_gguf", True, "ok", 2.5, "5"),
            # 负向由 ConditioningZeroOut 从正向派生，且 cfg=1
            ("test_z_image_turbo", False, "derived_from_positive", 1.0, None),
        ],
    )
    def test_real_workflows(
        self, name: str, effective: bool, reason: str, cfg: float, neg_node: str | None
    ) -> None:
        workflow = _load_workflow(_resolve_workflow_path(name))
        cap = _probe_negative_capability(workflow)
        assert cap.effective is effective
        assert cap.reason == reason
        assert cap.cfg == cfg
        assert cap.negative_node_id == neg_node

    def test_derived_from_positive_detected(self) -> None:
        workflow = _load_workflow(_resolve_workflow_path("test_z_image_turbo"))
        cap = _probe_negative_capability(workflow)
        assert cap.derived_from_positive is True
        assert cap.negative_chain_class == "ConditioningZeroOut"
        assert "derived_from_positive" in cap.blockers
        assert "cfg_too_low" in cap.blockers     # 两个原因同时存在

    @pytest.mark.parametrize(("cfg", "effective"), [(1.0, False), (1.05, False), (1.5, True), (2.5, True)])
    def test_cfg_threshold(self, cfg: float, effective: bool) -> None:
        workflow = {
            "1": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
            "3": {
                "class_type": "KSampler",
                "inputs": {"positive": ["1", 0], "negative": ["2", 0], "cfg": cfg},
            },
        }
        assert _probe_negative_capability(workflow).effective is effective

    def test_missing_cfg_is_blocked(self) -> None:
        workflow = {
            "1": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
            "3": {"class_type": "KSampler", "inputs": {"positive": ["1", 0], "negative": ["2", 0]}},
        }
        cap = _probe_negative_capability(workflow)
        assert cap.effective is False
        assert cap.reason == "cfg_too_low"

    def test_no_sampler_blocked(self) -> None:
        workflow = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}}}
        cap = _probe_negative_capability(workflow)
        assert cap.effective is False
        assert cap.reason == "no_sampler"


class TestConditioningNodeResolution:
    """节点识别顺 KSampler 连线解析，不再依赖 JSON 字典插入序。"""

    def test_sampler_link_beats_dict_order(self) -> None:
        """字典序脆弱性回归：即使 "9" 写在 "4" 之前，正负向仍按连线判定。"""
        workflow = {
            "9": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},   # 负向，却先出现
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
            "3": {
                "class_type": "KSampler",
                "inputs": {"positive": ["4", 0], "negative": ["9", 0], "cfg": 2.5},
            },
        }
        res = _resolve_conditioning_nodes(workflow)
        assert res.positive_node_id == "4"
        assert res.negative_node_id == "9"

    def test_numeric_aware_fallback_sort(self) -> None:
        """无 sampler 时按数字感知 id 序回退："57:27" 应排在 "9" 之后。"""
        assert _node_sort_key("57:27") == (57, 27)
        assert _node_sort_key("9") == (9,)
        assert _node_sort_key("9") < _node_sort_key("57:27")

        workflow = {
            "57:27": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
            "9": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        }
        res = _resolve_conditioning_nodes(workflow)
        assert res.positive_node_id == "9"
        assert res.negative_node_id == "57:27"

    def test_flux_resolution(self) -> None:
        workflow = _load_workflow(_resolve_workflow_path("flux_schnell"))
        res = _resolve_conditioning_nodes(workflow)
        assert res.positive_node_id == "4"
        assert res.negative_node_id == "9"
        assert res.derived_from_positive is False

    def test_zimage_has_no_negative_text_node(self) -> None:
        workflow = _load_workflow(_resolve_workflow_path("test_z_image_turbo"))
        res = _resolve_conditioning_nodes(workflow)
        assert res.positive_node_id == "57:27"
        assert res.negative_node_id is None
        assert res.derived_from_positive is True


# ── 负面词语义反演 ──


class TestNegativeInversion:
    """「否定 → 肯定」反演：进入正向串的只能是词表字面量，用户负面词永不注入。"""

    def test_no_rule_clause_is_affirmative(self) -> None:
        """守门：反演子句本身不得含否定词（否则等于把缺陷写进正向串）。"""
        for rule in _INVERSION_RULES:
            assert not re.search(r"\b(no|not|without)\b", rule.clause_en, re.I), rule.key
            assert not re.search(r"[无没不]", rule.clause_zh), rule.key

    def test_default_negative_injects_only_uncovered(self) -> None:
        res = _invert_negative(_DEFAULT_NEGATIVE, _ZIMAGE_PROFILE)
        assert res.clauses == ("边缘锐利、高清、矢量感清晰的字形", "画面只有字形本身，干净利落")
        assert "complex_background" in res.covered
        assert "broken_missing_strokes" in res.covered
        assert res.unmapped_terms == ()

    def test_en_profile_uses_english_clauses(self) -> None:
        res = _invert_negative("blurry text, watermark", _FLUX_PROFILE)
        assert res.clauses == (
            "sharp high-resolution edges, crisp vector-clean outlines",
            "clean unmarked typography, only the lettering itself",
        )

    def test_match_is_case_insensitive(self) -> None:
        res = _invert_negative("Blurry Text", _ZIMAGE_PROFILE)
        assert "blurry_low_quality" in res.matched

    def test_unmapped_terms_reported_and_never_injected(self) -> None:
        """守门：词表覆盖不到的用户负面词绝不进入正向串。"""
        res = _invert_negative("赛博朋克, blob", _ZIMAGE_PROFILE)
        assert res.unmapped_terms == ("赛博朋克", "blob")
        assert res.clauses == ()
        assert not any("赛博朋克" in c or "blob" in c for c in res.clauses)

    def test_clause_not_duplicated_when_already_present(self) -> None:
        clause = "边缘锐利、高清、矢量感清晰的字形"
        res = _invert_negative("blurry text", _ZIMAGE_PROFILE, already_present=f"酷炫，{clause}")
        assert clause not in res.clauses

    def test_empty_negative_yields_nothing(self) -> None:
        res = _invert_negative("", _ZIMAGE_PROFILE)
        assert res.clauses == ()
        assert res.matched == ()
        assert res.covered == ()
        assert res.unmapped_terms == ()

    def test_terms_split_on_both_punctuation_styles(self) -> None:
        res = _invert_negative("blurry text，模糊; watermark", _ZIMAGE_PROFILE)
        assert res.unmapped_terms == ()
        assert "blurry_low_quality" in res.matched
        assert "watermark" in res.matched


# ── 注入点清理 ──


class _BoomClient:
    """进入上下文成功、发起请求时失败——保证代码走到 patch 那一步才进 except。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def __enter__(self) -> "_BoomClient":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def post(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("no comfyui in tests")

    def get(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("no comfyui in tests")


class TestPatchWorkflowCleanup:
    """只写解析出的节点、不再重复 patch、clip_l 与 t5xxl 分离。"""

    def test_patch_is_idempotent(self, workflow: dict, sample_request: GenerationRequest) -> None:
        once = _patch_workflow(workflow, sample_request)
        twice = _patch_workflow(once, sample_request)
        assert once == twice

    def test_call_comfyui_api_does_not_repatch(
        self, monkeypatch: pytest.MonkeyPatch, workflow: dict
    ) -> None:
        """patch 由调用方负责；_call_comfyui_api 不得再 patch 一次。"""
        calls: list[int] = []
        real = generator._patch_workflow
        monkeypatch.setattr(
            generator,
            "_patch_workflow",
            lambda w, r, **kw: (calls.append(1), real(w, r))[1],
        )
        monkeypatch.setattr(generator.httpx, "Client", _BoomClient)

        _call_comfyui_api(GenerationRequest(text="x", prompt="y"), workflow)
        assert calls == []

    def test_unreferenced_encode_node_untouched(self, workflow: dict) -> None:
        """未接线的文本节点不得被灌入提示词。"""
        workflow = copy.deepcopy(workflow)
        workflow["extra"] = {"class_type": "CLIPTextEncode", "inputs": {"text": "KEEP"}}
        patched = _patch_workflow(workflow, GenerationRequest(text="满庭芳", prompt="水墨"))
        assert patched["extra"]["inputs"]["text"] == "KEEP"

    def test_flux_resolved_nodes_get_positive_and_negative(self) -> None:
        workflow = _load_workflow(_resolve_workflow_path("flux_schnell"))
        req = GenerationRequest(text="ICE CRUSH", prompt="frozen", negative_prompt="watermark")
        patched = _patch_workflow(workflow, req)
        pos = patched["4"]["inputs"]
        neg = patched["9"]["inputs"]
        assert _FLUX_BG_SUPPRESS in pos["t5xxl"]
        assert "watermark" in neg["t5xxl"]
        assert pos["t5xxl"] != neg["t5xxl"]

    def test_clip_l_is_short_digest_for_flux(self) -> None:
        """clip_l 只有 77 token，不能和 t5xxl 塞同一串长文本。"""
        workflow = _load_workflow(_resolve_workflow_path("flux_schnell"))
        req = GenerationRequest(text="咖啡 Latte 2.0", prompt="咖啡质感")
        patched = _patch_workflow(workflow, req)
        node = patched["4"]["inputs"]
        assert node["clip_l"] != node["t5xxl"]
        assert len(node["clip_l"]) < len(node["t5xxl"])

    def test_zimage_conditional_zero_out_untouched(self) -> None:
        """z-image 无负面文本节点：ConditioningZeroOut 不得被当作负面节点写入。"""
        workflow = _load_workflow(_resolve_workflow_path("test_z_image_turbo"))
        before = copy.deepcopy(workflow)
        req = GenerationRequest(text="满庭芳", prompt="水墨", negative_prompt="blurry")
        patched = _patch_workflow(workflow, req)
        assert patched["57:33"] == before["57:33"]


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
        assert _FLUX_BG_SUPPRESS in result

    def test_english_text_includes_bg_suppress(self) -> None:
        result = _build_flux_prompt("Hello World", "gold")
        assert _FLUX_BG_SUPPRESS in result

    def test_digits_only_includes_bg_suppress(self) -> None:
        result = _build_flux_prompt("123", "digital")
        assert _FLUX_BG_SUPPRESS in result

    def test_background_suppress_comes_before_style(self) -> None:
        result = _build_flux_prompt("测试", "neon style")
        assert result.index(_FLUX_BG_SUPPRESS) < result.index("neon style"), \
            "背景抑制应在风格提示词之前"

    def test_style_prompt_still_present(self) -> None:
        result = _build_flux_prompt("测试", "neon style")
        assert "neon style" in result

    def test_empty_text_still_suppresses_background(self) -> None:
        """空文本不再短路：下游仍要抠图，背景抑制照发。"""
        result = _build_flux_prompt("", "minimal")
        assert _FLUX_BG_SUPPRESS in result
        assert result != "minimal"
        assert result.endswith("minimal")


class TestBuildZimagePrompt:
    """Verify _build_zimage_prompt includes background suppression."""

    def test_chinese_text_includes_bg_suppress(self) -> None:
        result = _build_zimage_prompt("测试文字", "科技风")
        assert _ZIMAGE_BG_SUPPRESS in result

    def test_english_text_includes_bg_suppress(self) -> None:
        result = _build_zimage_prompt("Hello", "gold")
        assert _ZIMAGE_BG_SUPPRESS in result

    def test_background_suppress_comes_before_style(self) -> None:
        result = _build_zimage_prompt("测试", "科技风")
        assert result.index(_ZIMAGE_BG_SUPPRESS) < result.index("科技风"), \
            "背景抑制应在风格提示词之前"

    def test_style_prompt_still_present(self) -> None:
        result = _build_zimage_prompt("测试", "科技风")
        assert "科技风" in result

    def test_empty_text_still_suppresses_background(self) -> None:
        """空文本不再短路：下游仍要抠图，背景抑制照发。"""
        result = _build_zimage_prompt("", "minimal")
        assert _ZIMAGE_BG_SUPPRESS in result
        assert result != "minimal"
        assert result.endswith("minimal")


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
