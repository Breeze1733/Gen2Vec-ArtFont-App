from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import logging
import os
import random
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
from PIL import Image, ImageDraw, ImageFont

from .models import GenerationRequest

logger = logging.getLogger(__name__)


# ── Environment variable defaults ──
_ENV_COMFYUI_HOST = "COMFYUI_HOST"
_ENV_POLL_TIMEOUT = "COMFYUI_POLL_TIMEOUT"
_ENV_POLL_INTERVAL = "COMFYUI_POLL_INTERVAL"
_ENV_WORKFLOW_PATH = "WORKFLOW_PATH"

_DEFAULT_COMFYUI_HOST = "http://127.0.0.1:8188"
_DEFAULT_POLL_TIMEOUT = 900
_DEFAULT_POLL_INTERVAL = 1.0


@dataclass(frozen=True)
class GenerationArtifact:
    image_base64: str
    image_name: str
    metadata: dict
    workflow_api: Optional[dict] = None
    model_dependencies: Optional[dict] = None


# ── Workflow helpers ──


def _resolve_workflow_path(workflow_name: str = "") -> Path:
    """Return absolute path to the workflow JSON template.

    Priority:
      1. WORKFLOW_PATH env var (highest, for dev overrides)
      2. ``workflow_name`` from request → ``workflows/{name}.json``
      3. Default: ``workflows/flux_schnell.json``
    """
    env_path = os.environ.get(_ENV_WORKFLOW_PATH)
    if env_path:
        return Path(env_path).expanduser().resolve()

    # __file__ = .../app/generator.py → .parents[1] = .../txt2img-api/
    # This is correct in both dev (project checkout) and PyInstaller-frozen
    # layouts because frozen bundles lay out the package as `app/*.py` rooted
    # at the service directory alongside the `workflows/` data folder.
    project_root = Path(__file__).resolve().parents[1]
    workflows_dir = project_root / "workflows"

    if workflow_name:
        name = workflow_name if workflow_name.endswith(".json") else f"{workflow_name}.json"
        return workflows_dir / name

    return workflows_dir / "flux_schnell.json"


def _load_workflow(path: Path) -> dict:
    """Load and validate a ComfyUI API-format workflow JSON."""
    if not path.exists():
        raise FileNotFoundError(f"Workflow file not found: {path}")

    raw = path.read_text(encoding="utf-8")
    workflow = json.loads(raw)

    if not isinstance(workflow, dict):
        raise ValueError("Workflow must be a JSON object (dict of node_id -> node)")

    for node_id, node in workflow.items():
        if not isinstance(node, dict) or "class_type" not in node:
            raise ValueError(f"Node {node_id!r} is missing 'class_type' — not an API-format workflow.")
        if "inputs" not in node:
            raise ValueError(f"Node {node_id!r} is missing 'inputs' — not an API-format workflow.")

    return workflow


def _find_nodes_by_class(workflow: dict, class_type: str) -> list[tuple[str, dict]]:
    """Scan all workflow entries and return (node_id, node_data) for matching class_type."""
    return [(nid, node) for nid, node in workflow.items() if node.get("class_type") == class_type]


# ── 文本分析：路由与提示词模板共用的唯一真相源 ──

_CJK_RE = re.compile(r"[一-鿿]")
_LATIN_RUN_RE = re.compile(r"[A-Za-z]+")
_DIGIT_RUN_RE = re.compile(r"\d+(?:[.,]\d+)*")
_WS_RE = re.compile(r"\s+")

# residue 两端需要剥离的包围分隔符（避免 ", 100% ," 这类残留）
_RESIDUE_TRIM = " \t,，、;；:：.。"

# 会被提示词单独点名的符号集。空白与字母数字不属于符号。
_NOTABLE_SYMBOLS = frozenset(
    "%.,:;!?&@#+-=/*~^|$¥€￥°·…—'\"()[]{}「」『』《》【】"
)


@dataclass(frozen=True)
class TextAnalysis:
    """一次拆分出汉字 / 拉丁 / 数字 / 符号，供路由与提示词模板共用。

    ``residue``（原文去掉全部汉字后的剩余串）是修复「文字被渲染两遍」的关键：
    它**永远不含汉字**，因此可以安全地被「同时包含」子句引用。
    """

    raw: str
    stripped: str
    hanzi: tuple[str, ...]
    latin_runs: tuple[str, ...]
    digit_runs: tuple[str, ...]
    symbols: tuple[str, ...]
    script: str

    @property
    def has_hanzi(self) -> bool:
        return bool(self.hanzi)

    @property
    def has_latin(self) -> bool:
        return bool(self.latin_runs)

    @property
    def has_digits(self) -> bool:
        return bool(self.digit_runs)

    @property
    def has_symbols(self) -> bool:
        return bool(self.symbols)

    @property
    def is_empty(self) -> bool:
        return not self.stripped

    @property
    def hanzi_count(self) -> int:
        return len(self.hanzi)

    @property
    def max_latin_run(self) -> int:
        """最长拉丁片段长度。旧模板用 ``[a-zA-Z]{2,}`` 判定，会漏掉长度为 1 的片段。"""
        return max((len(run) for run in self.latin_runs), default=0)

    @property
    def hanzi_spaced(self) -> str:
        """汉字逐字空格拆分——强制模型一个字一个字画，降低连笔与漏字。"""
        return " ".join(self.hanzi)

    @property
    def symbols_spaced(self) -> str:
        return " ".join(self.symbols)

    @property
    def residue(self) -> str:
        """原文去掉全部汉字后的剩余串（已归一化空白与两端分隔符）。

        ``"咪哄之风 98% hey you"`` -> ``"98% hey you"``
        ``"咖啡 Latte 2.0"``       -> ``"Latte 2.0"``
        ``"单依纯 X"``             -> ``"X"``
        ``"满庭芳"``               -> ``""``
        """
        s = _CJK_RE.sub("", self.stripped)
        s = _WS_RE.sub(" ", s).strip()
        return s.strip(_RESIDUE_TRIM)


@lru_cache(maxsize=256)
def _analyze_text(text: str) -> TextAnalysis:
    """纯函数，字段全为 str/tuple → 可哈希可缓存。"""
    stripped = _WS_RE.sub(" ", text.strip())

    hanzi = tuple(_CJK_RE.findall(stripped))
    latin_runs = tuple(_LATIN_RUN_RE.findall(stripped))
    digit_runs = tuple(_DIGIT_RUN_RE.findall(stripped))
    symbols = tuple(dict.fromkeys(ch for ch in stripped if ch in _NOTABLE_SYMBOLS))

    if hanzi and latin_runs:
        script = "mixed"
    elif hanzi:
        script = "chinese"
    else:
        # 纯拉丁，以及无字母（纯数字/符号/空）—— 与既有路由契约一致
        script = "english"

    return TextAnalysis(
        raw=text,
        stripped=stripped,
        hanzi=hanzi,
        latin_runs=latin_runs,
        digit_runs=digit_runs,
        symbols=symbols,
        script=script,
    )


# ── Prompt template engine ──

# 背景抑制前缀 — 要求模型生成干净、易抠图的纯色背景
_FLUX_BG_SUPPRESS = (
    "plain solid background, simple clean backdrop, "
    "no complex scene, no landscape, no environment, "
    "no indoor background, no outdoor background, "
    "no textured surface, no patterned backdrop, "
    "isolated on solid color"
)

_ZIMAGE_BG_SUPPRESS = (
    "纯色背景，简洁干净的背景，"
    "无复杂场景，无风景，无环境，"
    "无室内背景，无室外背景，"
    "无纹理背景，无图案背景"
)

# 文本艺术字常见缺陷的默认负面提示词
_DEFAULT_NEGATIVE = (
    "broken strokes, missing strokes, wrong characters, garbled text, "
    "duplicate characters, repeated characters, extra character, wrong character count, "
    "deformed text, blurry text, low quality, jpeg artifacts, "
    "watermark, text signature, "
    "messy background, cluttered layout, "
    "complex background, busy background, detailed background, "
    "scenery background, landscape background, environmental background, "
    "indoor scene, outdoor scene, gradient background, patterned texture, "
    "photographic background, realistic setting"
)


def _detect_workflow_model(workflow: dict) -> str:
    """Detect which model family a workflow targets.

    Returns 'flux' if the workflow uses DualCLIPLoader + CLIPTextEncodeFlux,
    'zimage' if it uses CLIPLoader(type=lumina2),
    'qwen_image' if it uses CLIPLoader(type=qwen_image), otherwise 'unknown'.
    """
    for node in workflow.values():
        ct = node.get("class_type", "")
        if ct == "DualCLIPLoader":
            return "flux"
        if ct == "CLIPLoader":
            clip_type = node.get("inputs", {}).get("type", "")
            if clip_type == "lumina2":
                return "zimage"
            if clip_type == "qwen_image":
                return "qwen_image"
    return "unknown"


# ── Profile 化的提示词渲染 ──
#
# 单一渲染器 + 数据化 profile：渲染流程零分支，两个模型家族的差异全部落在数据上。

# 段落顺序。布局由用户在 ``prompt`` 里自由书写（不拆字段），
# 因此「把风格段提前到内容约束之前」就是让用户意图排在固定约束前面的落地方式。
_SECTION_ORDER = ("background", "style", "layout", "content", "accuracy", "inversion")

# 版式意图关键词：命中则发中性版式段，不覆盖用户自己写的排布要求。
_LAYOUT_INTENT_RE = re.compile(
    r"布局|版式|排列|排版|居中|中间|错落|上下|左右|左上|右上|左下|右下|"
    r"角落|底层|顶层|位置|大小|倾斜|横排|竖排|"
    r"layout|arrang|centered|centred|vertical|stacked|baseline|align",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PromptRule:
    """一条提示词子句规则。

    ``section`` 决定它落在哪一段；``fires`` 决定它是否触发；
    ``suppresses`` 列出它触发时需要屏蔽的同表其他 key——例如 residue
    已经把数字点名，就不必再单独强调数字。
    """

    section: str
    key: str
    fires: Callable[[TextAnalysis], bool]
    template: str
    suppresses: tuple[str, ...] = ()


@dataclass(frozen=True)
class RenderProfile:
    key: str
    lang: str          # 'en' | 'zh' —— 同时决定反演词表取哪一语言的子句
    joiner: str
    bg_suppress: str
    layout: str
    layout_neutral: str
    rules: tuple[PromptRule, ...]


@dataclass(frozen=True)
class RenderContext:
    analysis: TextAnalysis
    style_prompt: str
    profile: RenderProfile
    layout_intent_detected: bool = False
    inverted_clauses: tuple[str, ...] = ()


_FLUX_PROFILE = RenderProfile(
    key="flux",
    lang="en",
    joiner=", ",
    bg_suppress=_FLUX_BG_SUPPRESS,
    layout=(
        "layout: centered composition, single horizontal line of lettering "
        "on one baseline, even character spacing, front-facing flat view, "
        "generous margins"
    ),
    layout_neutral="layout: follow the arrangement described in the style description above",
    rules=(
        PromptRule(
            "content", "hanzi", lambda a: a.has_hanzi,
            'Chinese text "{hanzi_spaced}", exactly {hanzi_count} characters',
        ),
        PromptRule(
            "content", "residue", lambda a: a.has_hanzi and bool(a.residue),
            'alongside additional characters "{residue}"',
            suppresses=("digits", "symbols"),
        ),
        PromptRule(
            "content", "literal", lambda a: not a.has_hanzi and bool(a.stripped),
            'text "{stripped}"',
        ),
        PromptRule(
            "content", "digits", lambda a: a.has_digits,
            "accurate digits, no repeated digits",
        ),
        PromptRule(
            "content", "symbols", lambda a: a.has_symbols,
            'includes the symbol "{symbols_spaced}" drawn accurately',
        ),
        PromptRule(
            "accuracy", "hanzi_accuracy", lambda a: a.has_hanzi,
            "accurate strokes, complete radicals, no missing character, "
            "no extra character, no repeated character",
        ),
        PromptRule(
            "accuracy", "latin_accuracy", lambda a: a.has_latin,
            "crisp letterforms, perfect typography, no duplicate letters",
        ),
    ),
)

_ZIMAGE_PROFILE = RenderProfile(
    key="zimage",
    lang="zh",
    joiner="，",
    bg_suppress=_ZIMAGE_BG_SUPPRESS,
    layout="版式：文字居中排布，单行水平排列，字距均匀，正面平视视角，四周留白充足",
    layout_neutral="版式：遵循上述风格描述中给出的排布方式",
    rules=(
        PromptRule(
            "content", "hanzi", lambda a: a.has_hanzi,
            '文字内容为"{hanzi_spaced}"，不多不少正好{hanzi_count}个字',
        ),
        PromptRule(
            "content", "residue", lambda a: a.has_hanzi and bool(a.residue),
            '同时包含"{residue}"',
            suppresses=("digits", "symbols"),
        ),
        PromptRule(
            "content", "literal", lambda a: not a.has_hanzi and bool(a.stripped),
            '文字内容为"{stripped}"',
        ),
        PromptRule(
            "content", "digits", lambda a: a.has_digits,
            "数字大小比例正确，清晰可辨，不重不漏",
        ),
        PromptRule(
            "content", "symbols", lambda a: a.has_symbols,
            '包含符号"{symbols_spaced}"，形状准确、清晰可辨',
        ),
        PromptRule(
            "accuracy", "hanzi_accuracy", lambda a: a.has_hanzi,
            "不丢字不缺字，不重字不多字，每个字笔画完整结构正确",
        ),
        PromptRule(
            "accuracy", "latin_accuracy", lambda a: a.has_latin,
            "字母与数字大小比例正确、清晰可辨，不重复不遗漏",
        ),
    ),
)

# 家族 → profile。查表取代 if/elif，顺带消除「未知 model 落到函数末尾返回 None」的隐患。
_MODEL_PROFILE: dict[str, RenderProfile] = {
    "flux": _FLUX_PROFILE,
    "zimage": _ZIMAGE_PROFILE,
    "qwen_image": _ZIMAGE_PROFILE,
    "unknown": _FLUX_PROFILE,
}


def _detect_layout_intent(style_prompt: str) -> bool:
    """用户是否已在风格描述里表达了版式意图。

    命中则发中性版式段，避免默认版式覆盖用户自己的排布要求。
    """
    return bool(_LAYOUT_INTENT_RE.search(style_prompt))


def _render_rules(section: str, ctx: RenderContext) -> list[str]:
    analysis = ctx.analysis
    suppressed: set[str] = set()
    parts: list[str] = []
    for rule in ctx.profile.rules:
        if rule.section != section or rule.key in suppressed:
            continue
        if not rule.fires(analysis):
            continue
        parts.append(
            rule.template.format(
                hanzi_spaced=analysis.hanzi_spaced,
                hanzi_count=analysis.hanzi_count,
                residue=analysis.residue,
                stripped=analysis.stripped,
                symbols_spaced=analysis.symbols_spaced,
            )
        )
        suppressed.update(rule.suppresses)
    return parts


def _render_section(key: str, ctx: RenderContext) -> list[str]:
    profile = ctx.profile
    if key == "background":
        return [profile.bg_suppress]
    if key == "style":
        style = ctx.style_prompt.strip()
        return [style] if style else []
    if key == "layout":
        if ctx.analysis.is_empty:
            return []       # 没有文字就无需版式引导
        return [profile.layout_neutral if ctx.layout_intent_detected else profile.layout]
    if key in ("content", "accuracy"):
        return _render_rules(key, ctx)
    if key == "inversion":
        return list(ctx.inverted_clauses)
    return []


def _render_prompt(ctx: RenderContext) -> str:
    parts: list[str] = []
    for key in _SECTION_ORDER:
        parts.extend(_render_section(key, ctx))
    return ctx.profile.joiner.join(p for p in parts if p)


def _render_for(
    text: str,
    style_prompt: str,
    profile: RenderProfile,
    inverted_clauses: tuple[str, ...] = (),
) -> str:
    ctx = RenderContext(
        analysis=_analyze_text(text),
        style_prompt=style_prompt,
        profile=profile,
        layout_intent_detected=_detect_layout_intent(style_prompt),
        inverted_clauses=inverted_clauses,
    )
    return _render_prompt(ctx)


def _build_flux_prompt(text: str, style_prompt: str) -> str:
    """Build Flux.1 prompt — text accuracy guard only, style from user."""
    return _render_for(text, style_prompt, _FLUX_PROFILE)


def _build_zimage_prompt(text: str, style_prompt: str) -> str:
    """Build Z-Image prompt — text accuracy guard only, style from user."""
    return _render_for(text, style_prompt, _ZIMAGE_PROFILE)


# Qwen-Image 官方支持的 7 种分辨率
_QWEN_RESOLUTIONS = [
    (1328, 1328),   # 1:1
    (1664, 928),    # 16:9
    (928, 1664),    # 9:16
    (1472, 1104),   # 4:3
    (1104, 1472),   # 3:4
    (1584, 1056),   # 3:2
    (1056, 1584),   # 2:3
]

# Flux official resolutions — all dimensions divisible by 64 (transformer requirement)
_FLUX_RESOLUTIONS = [
    (1024, 1024),   # 1:1
    (1344, 768),    # 16:9
    (768, 1344),    # 9:16
    (1152, 896),    # 4:3
    (896, 1152),    # 3:4
    (1216, 832),    # 3:2
    (832, 1216),    # 2:3
]


def _map_qwen_resolution(w: int, h: int) -> tuple[int, int]:
    """Map a requested resolution to the nearest official Qwen-Image size."""
    ratio = w / h
    return min(_QWEN_RESOLUTIONS, key=lambda r: abs(r[0] / r[1] - ratio))


def _map_flux_resolution(w: int, h: int) -> tuple[int, int]:
    """Map a requested resolution to the nearest official Flux size (all divisible by 64)."""
    ratio = w / h
    return min(_FLUX_RESOLUTIONS, key=lambda r: abs(r[0] / r[1] - ratio))


def _build_negative_prompt(user_negative: str = "") -> str:
    """Merge user negative prompt with text-art-specific default negatives."""
    if user_negative.strip():
        return f"{_DEFAULT_NEGATIVE}, {user_negative.strip()}"
    return _DEFAULT_NEGATIVE


# ── 负面 conditioning 能力探测 ──
#
# 负面提示词并非在所有工作流上都真正生效：
#   * cfg = 1 时采样器忽略负面 conditioning（flux_schnell 与 test_z_image_turbo 都是）
#   * test_z_image_turbo 结构上就没有负面文本节点（负向由 ConditioningZeroOut 从正向派生）
# 所以必须同时看 cfg 与节点结构，任一不满足都判定为「不生效」。

_SAMPLER_CLASSES = ("KSampler", "KSamplerAdvanced")
_TEXT_ENCODE_CLASSES = ("CLIPTextEncode", "CLIPTextEncodeFlux")

# conditioning 直通节点：class_type -> 用于上溯的输入字段名
_CONDITIONING_PASSTHROUGH = {"ConditioningZeroOut": "conditioning"}

# cfg <= 该值视为负面 conditioning 失效
_CFG_NEGATIVE_MIN = 1.05

_BLOCKER_ORDER = ("no_sampler", "derived_from_positive", "no_negative_text_node", "cfg_too_low")


@dataclass(frozen=True)
class _ConditioningResolution:
    positive_node_id: Optional[str]
    negative_node_id: Optional[str]      # 能承载负面文本的节点；None 表示无处可写
    negative_chain_class: Optional[str]  # negative 槽位直接指向的 class_type
    derived_from_positive: bool


@dataclass(frozen=True)
class NegativeCapability:
    has_sampler: bool
    cfg: Optional[float]
    positive_node_id: Optional[str]
    negative_node_id: Optional[str]
    negative_chain_class: Optional[str]
    derived_from_positive: bool
    effective: bool
    reason: str
    blockers: tuple[str, ...]


def _node_sort_key(node_id: str) -> tuple[int, ...]:
    """数字感知的节点排序键：``"57:27" -> (57, 27)``、``"9" -> (9,)``。

    纯字符串排序会得出 ``"57:27" < "9"``，与人类直觉相反。
    """
    return tuple(int(n) for n in re.findall(r"\d+", node_id)) or (0,)


def _ref_node_id(ref: Any) -> Optional[str]:
    """解析 ``[node_id, slot]`` 形式的连线引用。"""
    if isinstance(ref, (list, tuple)) and ref:
        return str(ref[0])
    if isinstance(ref, str):
        return ref
    return None


def _resolve_conditioning_nodes(workflow: dict) -> _ConditioningResolution:
    """解析正向 / 负向文本节点。

    主路径顺 ``KSampler.positive`` / ``.negative`` 连线解析——**不依赖 JSON 字典插入序**，
    否则一次重新导出就可能把正负向互换。无采样器时回退到数字感知的 id 序。
    """
    for node in workflow.values():
        if node.get("class_type") not in _SAMPLER_CLASSES:
            continue
        inputs = node.get("inputs", {})
        pos_id = _ref_node_id(inputs.get("positive"))
        neg_id = _ref_node_id(inputs.get("negative"))
        if pos_id is None or neg_id is None:
            continue

        neg_chain_class = workflow.get(neg_id, {}).get("class_type")

        # 沿负向链路穿过 conditioning 直通节点，直到文本编码节点或断层
        cursor: Optional[str] = neg_id
        seen: set[str] = set()
        derived = False
        while cursor and cursor not in seen:
            if cursor == pos_id:
                derived = True
                break
            seen.add(cursor)
            node_c = workflow.get(cursor, {})
            ctype = node_c.get("class_type", "")
            if ctype in _TEXT_ENCODE_CLASSES:
                break
            step = _CONDITIONING_PASSTHROUGH.get(ctype)
            if not step:
                cursor = None
                break
            cursor = _ref_node_id(node_c.get("inputs", {}).get(step))

        negative_text_node: Optional[str] = None
        if not derived and cursor and workflow.get(cursor, {}).get("class_type") in _TEXT_ENCODE_CLASSES:
            negative_text_node = cursor

        positive_text_node = (
            pos_id if workflow.get(pos_id, {}).get("class_type") in _TEXT_ENCODE_CLASSES else None
        )

        return _ConditioningResolution(
            positive_node_id=positive_text_node,
            negative_node_id=negative_text_node,
            negative_chain_class=neg_chain_class,
            derived_from_positive=derived,
        )

    # 回退：无采样器连线可用时，按数字感知 id 序取前两个文本编码节点
    text_nodes = sorted(
        (nid for nid, n in workflow.items() if n.get("class_type") in _TEXT_ENCODE_CLASSES),
        key=_node_sort_key,
    )
    return _ConditioningResolution(
        positive_node_id=text_nodes[0] if text_nodes else None,
        negative_node_id=text_nodes[1] if len(text_nodes) > 1 else None,
        negative_chain_class=None,
        derived_from_positive=False,
    )


def _probe_negative_capability(workflow: dict) -> NegativeCapability:
    """判定该工作流能否真正兑现负面提示词。"""
    res = _resolve_conditioning_nodes(workflow)
    sampler = next(
        (n for n in workflow.values() if n.get("class_type") in _SAMPLER_CLASSES), None
    )
    cfg_raw = (sampler or {}).get("inputs", {}).get("cfg")
    cfg = float(cfg_raw) if isinstance(cfg_raw, (int, float)) else None

    blockers: list[str] = []
    if sampler is None:
        blockers.append("no_sampler")
    if res.derived_from_positive:
        blockers.append("derived_from_positive")
    elif res.negative_node_id is None:
        blockers.append("no_negative_text_node")
    if cfg is None or cfg <= _CFG_NEGATIVE_MIN:
        blockers.append("cfg_too_low")

    return NegativeCapability(
        has_sampler=sampler is not None,
        cfg=cfg,
        positive_node_id=res.positive_node_id,
        negative_node_id=res.negative_node_id,
        negative_chain_class=res.negative_chain_class,
        derived_from_positive=res.derived_from_positive,
        effective=not blockers,
        reason=next((b for b in _BLOCKER_ORDER if b in blockers), "ok"),
        blockers=tuple(blockers),
    )


# ── 负面词语义反演 ──
#
# cfg=1 的工作流无法用负面 conditioning，改用「否定 -> 肯定」把负面词转成正向引导。
# 硬规则：进入正向串的字符串**只能**来自下方词表的字面量，用户负面词本身永不注入
# （把 "broken strokes" 放进正向串等于邀请模型画断裂笔画）。

@dataclass(frozen=True)
class InversionRule:
    """一条「否定 -> 肯定」反演规则。

    ``match`` 里的英文项须为小写（按小写干草堆匹配），中文项原样。
    ``covered_by`` 非空表示该语义已由正向的某一段承担，只记账、不注入。
    ``clause_en`` / ``clause_zh`` 内**禁止出现否定词**——否则等于把缺陷写进正向串。
    """

    key: str
    match: tuple[str, ...]
    clause_en: str
    clause_zh: str
    covered_by: Optional[str] = None


@dataclass(frozen=True)
class InversionResult:
    clauses: tuple[str, ...]         # 实际注入的正向子句
    matched: tuple[str, ...]         # 命中的规则 key
    covered: tuple[str, ...]         # 命中但被既有正向段覆盖
    unmapped_terms: tuple[str, ...]  # 词表未覆盖的用户词，只上报、绝不注入


_INVERSION_RULES: tuple[InversionRule, ...] = (
    # —— 已被背景抑制段覆盖，只记账不注入 ——
    InversionRule(
        key="complex_background",
        match=("complex background", "busy background", "detailed background",
               "messy background", "cluttered layout", "杂乱背景", "复杂背景"),
        clause_en="clean empty background",
        clause_zh="干净空旷的背景",
        covered_by="background",
    ),
    InversionRule(
        key="scenery_background",
        match=("scenery background", "landscape background", "environmental background",
               "photographic background", "realistic setting", "风景背景", "环境背景"),
        clause_en="abstract flat backdrop",
        clause_zh="抽象平面底",
        covered_by="background",
    ),
    InversionRule(
        key="indoor_outdoor_scene",
        match=("indoor scene", "outdoor scene", "室内场景", "室外场景"),
        clause_en="pure graphic backdrop",
        clause_zh="纯图形底",
        covered_by="background",
    ),
    InversionRule(
        key="gradient_pattern_bg",
        match=("gradient background", "patterned texture", "渐变背景", "图案背景"),
        clause_en="uniform single-color fill",
        clause_zh="均匀纯色填充",
        covered_by="background",
    ),
    # —— 已被 accuracy 段覆盖，只记账不注入 ——
    InversionRule(
        key="broken_missing_strokes",
        match=("broken strokes", "missing strokes", "断笔", "缺笔", "笔画断裂"),
        clause_en="each glyph fully formed with complete closed strokes",
        clause_zh="每个字笔画完整、结构闭合",
        covered_by="accuracy",
    ),
    InversionRule(
        key="wrong_garbled_text",
        match=("wrong characters", "garbled text", "错字", "乱码"),
        clause_en="every glyph is a correct, legible character",
        clause_zh="每个字都是正确可读的汉字",
        covered_by="accuracy",
    ),
    InversionRule(
        key="duplicate_characters",
        match=("duplicate characters", "repeated characters", "extra character",
               "wrong character count", "重字", "多字", "重复字"),
        clause_en="exactly the specified character count, each glyph appears once",
        clause_zh="字数与指定完全一致，每个字只出现一次",
        covered_by="accuracy",
    ),
    # —— 需要真正注入的正向引导 ——
    InversionRule(
        key="blurry_low_quality",
        match=("blurry text", "low quality", "jpeg artifacts", "deformed text",
               "模糊", "低清晰度", "畸变"),
        clause_en="sharp high-resolution edges, crisp vector-clean outlines",
        clause_zh="边缘锐利、高清、矢量感清晰的字形",
    ),
    InversionRule(
        key="watermark",
        match=("watermark", "text signature", "水印", "署名", "落款"),
        clause_en="clean unmarked typography, only the lettering itself",
        clause_zh="画面只有字形本身，干净利落",
    ),
    InversionRule(
        key="figurative_elements",
        match=("person", "people", "human", "face", "hand", "animal",
               "人物", "人脸", "动物"),
        clause_en="only typography in frame, pure lettering composition",
        clause_zh="画面主体只有文字，纯字形构图",
    ),
)

_NEGATIVE_TERM_SPLIT_RE = re.compile(r"[,，、;；\n]+")
_COMPARE_NORM_RE = re.compile(r"[\s,，、;；:：.。]+")


def _split_negative_terms(source: str) -> tuple[str, ...]:
    return tuple(t.strip() for t in _NEGATIVE_TERM_SPLIT_RE.split(source) if t.strip())


def _normalize_for_compare(text: str) -> str:
    return _COMPARE_NORM_RE.sub("", text.lower())


def _rule_matches(rule: InversionRule, haystack: str) -> bool:
    return any(term in haystack for term in rule.match)


def _invert_negative(
    negative_source: str,
    profile: RenderProfile,
    already_present: str = "",
) -> InversionResult:
    """把负面词表内的词反演成正向子句。

    未命中的词只上报、不注入。已由正向段覆盖的词只记账、不重复注入。
    """
    terms = _split_negative_terms(negative_source)
    if not terms:
        return InversionResult((), (), (), ())

    haystack = negative_source.lower()
    norm_present = _normalize_for_compare(already_present)
    use_en = profile.lang == "en"

    clauses: list[str] = []
    matched: list[str] = []
    covered: list[str] = []
    seen_clauses: set[str] = set()

    for rule in _INVERSION_RULES:
        if not _rule_matches(rule, haystack):
            continue
        matched.append(rule.key)
        if rule.covered_by is not None:
            covered.append(rule.key)
            continue

        clause = rule.clause_en if use_en else rule.clause_zh
        norm = _normalize_for_compare(clause)
        if norm in seen_clauses or (norm_present and norm in norm_present):
            continue
        seen_clauses.add(norm)
        clauses.append(clause)

    unmapped = tuple(
        term for term in terms
        if not any(_rule_matches(rule, term.lower()) for rule in _INVERSION_RULES)
    )

    return InversionResult(tuple(clauses), tuple(matched), tuple(covered), unmapped)


# ── 提示词方案 ──

# clip_l 是 CLIP-L 编码器（77 token），只收关键段的短摘要；全长给 t5xxl。
_CLIP_L_SECTIONS = ("background", "content", "style")
_CLIP_L_MAX_CHARS = 220


@dataclass(frozen=True)
class PromptPlan:
    """一次渲染的完整产物：正向 / 负向串与各自的 clip_l 摘要在此定下来。"""

    analysis: TextAnalysis
    profile_key: str
    positive_prompt: str
    negative_prompt: str
    clip_l_positive: str
    clip_l_negative: str
    inversion: InversionResult
    negative_strategy: str          # 'negative-conditioning' | 'positive-inversion'
    capability: Optional[NegativeCapability]
    layout_intent_detected: bool
    clip_l_token_estimate: int


def _estimate_clip_tokens(text: str) -> int:
    """CLIP BPE 的保守近似：英文按词、数字按串、其余非空白各计 1。"""
    return len(re.findall(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]", text))


def _truncate_at_boundary(text: str, limit: int, joiner: str) -> str:
    """按子句边界截断，绝不切断半个词。"""
    if len(text) <= limit:
        return text
    parts = text.split(joiner)
    out = ""
    for part in parts:
        candidate = part if not out else f"{out}{joiner}{part}"
        if len(candidate) > limit:
            break
        out = candidate
    return out or parts[0][:limit]


def _render_clip_l(ctx: RenderContext) -> str:
    """给 CLIP-L 的短摘要。t5xxl 收全长，两者不再相等。"""
    parts: list[str] = []
    for key in _CLIP_L_SECTIONS:
        parts.extend(_render_section(key, ctx))
    joined = ctx.profile.joiner.join(p for p in parts if p)
    return _truncate_at_boundary(joined, _CLIP_L_MAX_CHARS, ctx.profile.joiner)


def _plan_prompt(
    request: GenerationRequest,
    model: str,
    capability: Optional[NegativeCapability] = None,
) -> PromptPlan:
    """渲染正向 / 负向提示词，并决定负面策略。

    ``capability`` 为 None 表示未知——按「不生效」处理，把用户意图反演成正向引导，
    避免静默丢失。
    """
    profile = _MODEL_PROFILE.get(model, _FLUX_PROFILE)
    analysis = _analyze_text(request.text)
    negative_prompt = _build_negative_prompt(request.negative_prompt)

    use_inversion = capability is None or not capability.effective
    layout_intent = _detect_layout_intent(request.prompt)

    base_ctx = RenderContext(
        analysis=analysis,
        style_prompt=request.prompt,
        profile=profile,
        layout_intent_detected=layout_intent,
    )
    base_positive = _render_prompt(base_ctx)

    inversion = (
        _invert_negative(negative_prompt, profile, already_present=base_positive)
        if use_inversion
        else InversionResult((), (), (), ())
    )

    if inversion.clauses:
        ctx = RenderContext(
            analysis=analysis,
            style_prompt=request.prompt,
            profile=profile,
            layout_intent_detected=layout_intent,
            inverted_clauses=inversion.clauses,
        )
        positive_prompt = _render_prompt(ctx)
    else:
        ctx = base_ctx
        positive_prompt = base_positive

    clip_l_positive = _render_clip_l(ctx)
    return PromptPlan(
        analysis=analysis,
        profile_key=profile.key,
        positive_prompt=positive_prompt,
        negative_prompt=negative_prompt,
        clip_l_positive=clip_l_positive,
        # 负面串由 _build_negative_prompt 用 ", " 连接，故按 ", " 切子句
        clip_l_negative=_truncate_at_boundary(negative_prompt, _CLIP_L_MAX_CHARS, ", "),
        inversion=inversion,
        negative_strategy="positive-inversion" if use_inversion else "negative-conditioning",
        capability=capability,
        layout_intent_detected=layout_intent,
        clip_l_token_estimate=_estimate_clip_tokens(clip_l_positive),
    )


_SYNTHESIS_VERSION = 1


def _build_synthesis_block(plan: PromptPlan) -> dict[str, Any]:
    """记录「实际注入了什么」。

    ``positive_prompt`` 是权威值——必须与产物 ``workflow_api.json`` 里
    对应节点的内容逐字相等。
    """
    cap = plan.capability
    return {
        "version": _SYNTHESIS_VERSION,
        "applied": True,
        "profile": plan.profile_key,
        "section_order": list(_SECTION_ORDER),
        "text_profile": plan.analysis.script,
        "normalized_text": plan.analysis.stripped,
        "hanzi_count": plan.analysis.hanzi_count,
        "residue": plan.analysis.residue,
        "symbols": list(plan.analysis.symbols),
        "layout_intent_detected": plan.layout_intent_detected,
        "positive_prompt": plan.positive_prompt,
        "positive_sha256": hashlib.sha256(plan.positive_prompt.encode("utf-8")).hexdigest()[:16],
        # clip_l 只有 flux 家族在用（CLIPTextEncodeFlux 的双文本输入）。
        # 其余家族写的是单 text 输入，报告「截断风险」会误导。
        "clip_l_used": plan.profile_key == "flux",
        "clip_l": plan.clip_l_positive,
        "clip_l_token_estimate": plan.clip_l_token_estimate,
        "clip_l_truncation_risk": (
            plan.clip_l_token_estimate > 70 if plan.profile_key == "flux" else None
        ),
        "negative_strategy": plan.negative_strategy,
        "negative_written_to": cap.negative_node_id if cap else None,
        "negative_capability": (
            {
                "effective": cap.effective,
                "reason": cap.reason,
                "blockers": list(cap.blockers),
                "cfg": cap.cfg,
                "negative_node_id": cap.negative_node_id,
                "negative_chain_class": cap.negative_chain_class,
                "derived_from_positive": cap.derived_from_positive,
            }
            if cap
            else None
        ),
        "inversion": {
            "matched": list(plan.inversion.matched),
            "covered": list(plan.inversion.covered),
            "injected_clauses": list(plan.inversion.clauses),
            "unmapped_terms": list(plan.inversion.unmapped_terms),
        },
    }


def _build_stub_synthesis_block(request: GenerationRequest) -> dict[str, Any]:
    """stub 不构造提示词，但仍发同名的键，保证消费方可无条件读取。"""
    return {
        "version": _SYNTHESIS_VERSION,
        "applied": False,
        "text_profile": _analyze_text(request.text).script,
        "note": "local stub 不构造提示词，未提交 ComfyUI",
    }


def _log_prompt_plan(plan: PromptPlan, workflow_name: str) -> None:
    logger.info(
        "prompt plan: workflow=%s profile=%s text=%s strategy=%s negative_effective=%s",
        workflow_name,
        plan.profile_key,
        plan.analysis.script,
        plan.negative_strategy,
        plan.capability.effective if plan.capability else None,
    )
    if plan.inversion.unmapped_terms:
        logger.warning(
            "负面词不在反演词表内，已丢弃且不注入：%s", list(plan.inversion.unmapped_terms)
        )
    if plan.inversion.covered:
        logger.info("负面词已由既有正向段覆盖，不重复注入：%s", list(plan.inversion.covered))


def _write_text_node(node: dict, text: str, clip_l: str) -> None:
    """CLIPTextEncodeFlux 有 clip_l 与 t5xxl 两个文本输入；普通节点只有一个。"""
    if node.get("class_type") == "CLIPTextEncodeFlux":
        node["inputs"]["t5xxl"] = text
        node["inputs"]["clip_l"] = clip_l
    else:
        node["inputs"]["text"] = text


def _patch_workflow(
    workflow: dict,
    request: GenerationRequest,
    *,
    plan: Optional[PromptPlan] = None,
) -> dict:
    """Deep-copy workflow and inject user parameters.

    Patching rules:
      - 文本节点：顺 KSampler 的 ``positive`` / ``negative`` 连线解析
        （无采样器时按数字感知 id 序回退），不再依赖 JSON 字典插入序
      - CLIPTextEncodeFlux：``t5xxl`` 收全长、``clip_l`` 收短摘要
      - EmptyLatentImage / EmptySD3LatentImage → width, height
      - KSampler / KSamplerAdvanced → seed

    ``plan`` 可由调用方预先算好以避免重复渲染；为 None 时内部计算。
    """
    patched = copy.deepcopy(workflow)

    model = _detect_workflow_model(patched)
    if plan is None:
        plan = _plan_prompt(request, model, _probe_negative_capability(patched))

    # ── 文本节点（只写解析出的两个，不再「第 2 个起全灌负面」）──
    resolved = _resolve_conditioning_nodes(patched)
    if resolved.positive_node_id and resolved.positive_node_id in patched:
        _write_text_node(
            patched[resolved.positive_node_id], plan.positive_prompt, plan.clip_l_positive
        )
    if resolved.negative_node_id and resolved.negative_node_id in patched:
        # 即便 capability 判定不生效也照写：保持 workflow_api 快照的历史可比性，
        # 且将来若调高 cfg，负面立即恢复生效。不生效的事实由 metadata 记录。
        _write_text_node(
            patched[resolved.negative_node_id], plan.negative_prompt, plan.clip_l_negative
        )

    # ── EmptyLatentImage / EmptySD3LatentImage (resolution) ──
    latent_nodes = _find_nodes_by_class(patched, "EmptyLatentImage")
    latent_nodes += _find_nodes_by_class(patched, "EmptySD3LatentImage")
    w, h = _parse_resolution(request.resolution)
    if model == "qwen_image":
        w, h = _map_qwen_resolution(w, h)
    elif model == "flux":
        w, h = _map_flux_resolution(w, h)
    for _nid, node in latent_nodes:
        node["inputs"]["width"] = w
        node["inputs"]["height"] = h

    # ── KSampler (seed) ──
    sampler_nodes = _find_nodes_by_class(patched, "KSampler")
    sampler_nodes += _find_nodes_by_class(patched, "KSamplerAdvanced")
    for _nid, node in sampler_nodes:
        node["inputs"]["seed"] = request.seed

    return patched


# ── Warmup ──


def warmup_comfyui_connection() -> None:
    """Quick connectivity check so the first generate call doesn't wait for startup."""
    host = os.environ.get(_ENV_COMFYUI_HOST, _DEFAULT_COMFYUI_HOST).rstrip("/")
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{host}/system_stats")
            if resp.status_code == 200:
                logger.info("ComfyUI connection verified at %s", host)
    except Exception:
        pass  # ComfyUI may still be starting — that's fine


# ── ComfyUI API interaction ──


def _call_comfyui_api(
    request: GenerationRequest, submitted_workflow: dict
) -> Optional[GenerationArtifact]:
    """Submit an **already patched** workflow to ComfyUI, poll, return artifact.

    调用方负责 patch（见 :func:`_patch_workflow`）——本函数不再内部重复 patch。

    Returns None on any failure (connection, timeout, execution error)
    so the caller can fall back to the local stub.
    """
    host = os.environ.get(_ENV_COMFYUI_HOST, _DEFAULT_COMFYUI_HOST).rstrip("/")
    timeout = int(os.environ.get(_ENV_POLL_TIMEOUT, str(_DEFAULT_POLL_TIMEOUT)))
    interval = float(os.environ.get(_ENV_POLL_INTERVAL, str(_DEFAULT_POLL_INTERVAL)))

    try:
        with httpx.Client(timeout=30.0) as client:
            # 1. Submit
            client_id = str(uuid.uuid4())
            patched = submitted_workflow
            submit_payload = {"prompt": patched, "client_id": client_id}

            submit_resp = client.post(f"{host}/prompt", json=submit_payload)
            if submit_resp.is_error:
                logger.warning("ComfyUI /prompt returned %s: %s", submit_resp.status_code, submit_resp.text[:200])
                return None
            prompt_id = submit_resp.json().get("prompt_id")
            if not prompt_id:
                logger.warning("ComfyUI /prompt returned no prompt_id: %s", submit_resp.text[:200])
                return None

            # 2. Poll history for completion
            deadline = time.monotonic() + timeout
            history = None
            while time.monotonic() < deadline:
                hist_resp = client.get(f"{host}/history/{prompt_id}")
                if hist_resp.status_code == 200:
                    data = hist_resp.json()
                    entry = data.get(prompt_id)
                    if entry and entry.get("status", {}).get("completed"):
                        history = entry
                        break
                time.sleep(interval)

            if history is None:
                logger.warning("ComfyUI timeout waiting for prompt %s after %ss", prompt_id[:8], timeout)
                return None  # timeout

            # 3. Extract image info from SaveImage output
            save_nodes = _find_nodes_by_class(patched, "SaveImage")
            if not save_nodes:
                logger.warning("No SaveImage node found in patched workflow")
                return None
            save_node_id = save_nodes[0][0]

            outputs = history.get("outputs", {})
            node_outputs = outputs.get(save_node_id, {})
            images = node_outputs.get("images", [])
            if not images:
                logger.warning("No images in output node %s; available outputs: %s",
                               save_node_id, list(outputs.keys()))
                return None

            img_info = images[0]
            filename = img_info["filename"]
            subfolder = img_info.get("subfolder", "")
            img_type = img_info.get("type", "output")

            # 4. Download actual image bytes
            view_resp = client.get(
                f"{host}/view",
                params={"filename": filename, "type": img_type, "subfolder": subfolder},
            )
            view_resp.raise_for_status()
            image_bytes = view_resp.content

            # 5. Encode to base64 data URL
            b64 = base64.b64encode(image_bytes).decode("ascii")
            image_base64 = f"data:image/png;base64,{b64}"

            # 6. Build metadata
            slug = re.sub(r"[^\w一-鿿]+", "-", request.prompt.strip(), flags=re.UNICODE).strip("-")
            image_name = f"{slug or 'txt2img-generated'}.png"
            w, h = _parse_resolution(request.resolution)

            metadata: dict[str, Any] = {
                "engine": "comfyui",
                "prompt": request.prompt,
                "negative_prompt": request.negative_prompt,
                "resolution": request.resolution,
                "seed": request.seed,
                "style": request.style,
                "format": request.format,
                "canvas": {"width": w, "height": h},
                "comfyui_prompt_id": prompt_id,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "artifact": {"image_name": image_name, "byte_length": len(image_bytes)},
            }

            return GenerationArtifact(image_base64=image_base64, image_name=image_name, metadata=metadata)

    except Exception as exc:
        logger.warning("ComfyUI generation failed: %s", exc)
        return None


# ── Local stub (fallback) ──


def _local_stub_generate(
    request: GenerationRequest, attempted_workflows: list[str] | None = None
) -> GenerationArtifact:
    from hashlib import sha256

    w, h = _parse_resolution(request.resolution)

    seed_value = request.seed or int.from_bytes(sha256(request.prompt.encode()).digest()[:8], "big")
    rng = random.Random(seed_value)

    def _random_color():
        return tuple(int(c * 255) for c in (rng.random(), rng.random(), rng.random()))

    top = _random_color()
    bottom = _random_color()

    image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for y in range(h):
        ratio = y / max(1, h - 1)
        color = tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3))
        draw.line((0, y, w, y), fill=color)

    try:
        font = ImageFont.truetype("arial.ttf", size=max(20, w // 24))
    except Exception:
        font = ImageFont.load_default()
    draw.text((16, 16), request.prompt[:80], font=font, fill=(255, 255, 255))

    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG")
    png_bytes = buf.getvalue()
    image_base64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")

    slug = re.sub(r"[^\w一-鿿]+", "-", request.prompt.strip(), flags=re.UNICODE).strip("-")
    image_name = f"{slug or 'txt2img-generated'}.png"

    metadata: dict[str, Any] = {
        "engine": "local-studio",
        "prompt": request.prompt,
        "negative_prompt": request.negative_prompt,
        "resolution": request.resolution,
        "seed": seed_value,
        "style": request.style,
        "format": request.format,
        "canvas": {"width": w, "height": h},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifact": {"image_name": image_name, "byte_length": len(png_bytes)},
        "fallback_tier": -1,
        "workflow_used": "",
        "attempted_workflows": attempted_workflows or [],
        "prompt_synthesis": _build_stub_synthesis_block(request),
    }

    return GenerationArtifact(image_base64=image_base64, image_name=image_name, metadata=metadata)


# ── Resolution parser ──


def _parse_resolution(resolution: str) -> tuple[int, int]:
    """Parse '1024x1024' or '1024 x 1024' into (width, height)."""
    parts = resolution.strip().lower().replace(" ", "").split("x")
    if len(parts) != 2:
        return 1024, 1024
    try:
        w, h = int(parts[0]), int(parts[1])
        return (w, h) if w > 0 and h > 0 else (1024, 1024)
    except ValueError:
        return 1024, 1024


# ── Public entry point ──


# 工作流降级链：按内容类型选择优先级
_CHINESE_FALLBACK = ["qwen_image_2512_gguf", "test_z_image_turbo"]
_ENGLISH_FALLBACK = ["flux_schnell", "test_z_image_turbo"]
_MIXED_FALLBACK = ["test_z_image_turbo"]

_ROUTE_CHAINS: dict[str, list[str]] = {
    "chinese": _CHINESE_FALLBACK,
    "english": _ENGLISH_FALLBACK,
    "mixed": _MIXED_FALLBACK,
}


def _classify_text(text: str) -> str:
    """按字母构成把文本分为 'chinese' / 'english' / 'mixed'。

    只统计汉字与拉丁字母；数字、标点、符号、空白一律不参与判定，
    因此 ``冰川 100%`` 归为纯中文。无字母的输入（纯数字/符号/空）
    并入 'english'。

    判定规则由 :class:`TextAnalysis` 承载——路由与提示词模板共用同一份分析，
    不再各持一个正则。
    """
    return _analyze_text(text).script


def _extract_model_dependencies(workflow: dict, workflow_name: str = "") -> dict:
    """Scan loader nodes in a patched workflow and extract model file references."""
    models: dict[str, list[str]] = {
        "checkpoints": [],
        "unets": [],
        "clip": [],
        "vae": [],
        "loras": [],
    }

    # Class-type → input-field mapping for known loader nodes
    LOADER_FIELDS: dict[str, str] = {
        "CheckpointLoaderSimple": "ckpt_name",
        "UNETLoader": "unet_name",
        "UnetLoaderGGUF": "unet_name",
        "CLIPLoader": "clip_name",
        "DualCLIPLoader": "clip_name1",  # primary model; clip_name2 also captured
        "VAELoader": "vae_name",
        "LoraLoaderModelOnly": "lora_name",
    }

    for node in workflow.values():
        ct = node.get("class_type", "")
        field = LOADER_FIELDS.get(ct)
        if field:
            model_name = node.get("inputs", {}).get(field, "")
            if model_name and isinstance(model_name, str):
                if ct == "DualCLIPLoader":
                    models["clip"].append(model_name)
                    clip2 = node.get("inputs", {}).get("clip_name2", "")
                    if clip2 and isinstance(clip2, str):
                        models["clip"].append(clip2)
                elif ct == "LoraLoaderModelOnly":
                    models["loras"].append(model_name)
                elif ct in ("UNETLoader", "UnetLoaderGGUF", "CheckpointLoaderSimple"):
                    target = "unets" if ct != "CheckpointLoaderSimple" else "checkpoints"
                    models[target].append(model_name)
                elif ct == "VAELoader":
                    models["vae"].append(model_name)
                elif ct == "CLIPLoader":
                    models["clip"].append(model_name)

    return {
        "checkpoints": sorted(set(models["checkpoints"])),
        "unets": sorted(set(models["unets"])),
        "clip": sorted(set(models["clip"])),
        "vae": sorted(set(models["vae"])),
        "loras": sorted(set(models["loras"])),
        "workflow_name": workflow_name,
        "note": "运行时模型依赖快照；请结合交付文档中的模型清单核验。",
    }


def generate_artwork(request: GenerationRequest) -> GenerationArtifact:
    """依次尝试工作流降级链，全部失败则用本地 Pillow stub。

    - 用户显式指定了 workflow → 只尝试那一个
    - 纯中文 → Qwen-Image → Z-Image
    - 纯英文（含无字母的纯数字/符号）→ Flux → Z-Image
    - 中英混排 → Z-Image（单层，无兜底）
    """
    workflows_to_try: list[str]
    if request.workflow:
        workflows_to_try = [request.workflow]
    else:
        workflows_to_try = list(_ROUTE_CHAINS[_classify_text(request.text)])

    for idx, name in enumerate(workflows_to_try):
        try:
            workflow_path = _resolve_workflow_path(name)
            workflow = _load_workflow(workflow_path)
            model = _detect_workflow_model(workflow)
            capability = _probe_negative_capability(workflow)
            plan = _plan_prompt(request, model, capability)
            patched = _patch_workflow(workflow, request, plan=plan)
            result = _call_comfyui_api(request, patched)
            if result is not None:
                logger.info("Workflow '%s' succeeded (tier=%d)", name, idx)
                _log_prompt_plan(plan, name)
                result.metadata["fallback_tier"] = idx
                result.metadata["workflow_used"] = name
                result.metadata["attempted_workflows"] = workflows_to_try
                result.metadata["prompt_synthesis"] = _build_synthesis_block(plan)
                model_deps = _extract_model_dependencies(patched, workflow_name=name)
                return GenerationArtifact(
                    image_base64=result.image_base64,
                    image_name=result.image_name,
                    metadata=result.metadata,
                    workflow_api=patched,
                    model_dependencies=model_deps,
                )
            logger.warning("Workflow '%s' returned None, trying next", name)
        except Exception as exc:
            logger.warning("Workflow '%s' failed: %s", name, exc)
            continue

    return _local_stub_generate(request, attempted_workflows=workflows_to_try)
