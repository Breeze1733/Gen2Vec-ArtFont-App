# 提示词子系统开发者参考

面向维护 `app/generator.py` 提示词部分的人。用户视角的概述见 [../README.md](../README.md#提示词子系统)。

全部实现集中在 `app/generator.py` 一个文件。入口是 `generate_artwork()`，它按文本内容选链、算 `PromptPlan`、注入工作流、写 metadata。

```
generate_artwork(request)
  ├─ _classify_text(request.text)           -> chinese | english | mixed
  ├─ _ROUTE_CHAINS[...]                     -> 候选工作流列表
  └─ 对每个工作流:
       ├─ _detect_workflow_model(workflow)  -> flux | zimage | qwen_image | unknown
       ├─ _probe_negative_capability(wf)    -> NegativeCapability
       ├─ _plan_prompt(req, model, cap)     -> PromptPlan
       ├─ _patch_workflow(wf, req, plan=…)  -> 注入后的工作流
       ├─ _call_comfyui_api(req, patched)   -> 提交 + 轮询（不再内部 patch）
       └─ metadata["prompt_synthesis"] = _build_synthesis_block(plan)
```

---

## 1. `TextAnalysis` —— 唯一真相源

```python
@lru_cache(maxsize=256)
def _analyze_text(text: str) -> TextAnalysis
def _classify_text(text: str) -> str   # 薄封装：返回 analysis.script
```

| 字段 | 说明 |
|---|---|
| `raw` | 原样输入，仅供诊断 |
| `stripped` | `strip()` + 内部空白折叠为单空格 |
| `hanzi` | 汉字，按出现顺序，不去重 |
| `latin_runs` | `[A-Za-z]+` 连续片段，如 `("Latte",)`、`("X",)` |
| `digit_runs` | `\d+(?:[.,]\d+)*` |
| `symbols` | 去重保序，仅含 `_NOTABLE_SYMBOLS` 里的字符 |
| `script` | `chinese` / `english` / `mixed` |

派生属性：

| 属性 | 用途 |
|---|---|
| `hanzi_spaced` | `"咖 啡"` —— 逐字拆分，强制模型一个字一个字画 |
| `symbols_spaced` | `"% ."` —— 供 symbols 子句点名 |
| `max_latin_run` | 最长拉丁片段长度。旧的 `[a-zA-Z]{2,}` 判定漏掉长度为 1 的片段 |
| **`residue`** | **原文去掉全部汉字后的剩余串** |

### `residue` 为什么关键

它是「同时包含 …」子句**唯一被允许引用**的内容源，因为它永远不含汉字：

```
"咪哄之风 98% hey you"  ->  "98% hey you"
"咖啡 Latte 2.0"        ->  "Latte 2.0"
"冰川 Ice 100%"         ->  "Ice 100%"
"单依纯 X"              ->  "X"
"满庭芳"                ->  ""
```

历史缺陷：旧模板写 `f'同时包含英文"{text}"'`，`text` 是含汉字的完整原文，等于要求模型把中文再画一遍。实测 `咪哄之风 98% hey you` 出图里文字出现两次。

实现细节：先 `_CJK_RE.sub("")`，再折叠空白，最后 `strip(_RESIDUE_TRIM)` 剥掉两端包围标点（`, ， 、 ; ； : ： . 。`）。

### `script` 的判定规则（不可随意改）

```
has_hanzi and has_latin -> "mixed"
has_hanzi               -> "chinese"
otherwise               -> "english"     # 含纯拉丁与「无字母」
```

`has_latin` 用 `bool(latin_runs)`（1+ 字母），**不是** `{2,}`。改这条会同时影响路由与 `TestClassifyText` 的 21 条参数化用例。

---

## 2. `RenderProfile` / `PromptRule` —— 数据化模板

```python
@dataclass(frozen=True)
class PromptRule:
    section: str                              # 'content' | 'accuracy'
    key: str
    fires: Callable[[TextAnalysis], bool]
    template: str                             # str.format，可用占位符见下
    suppresses: tuple[str, ...] = ()          # 命中时屏蔽同表的其他 key

@dataclass(frozen=True)
class RenderProfile:
    key: str                                  # 'flux' | 'zimage'
    lang: str                                 # 'en' | 'zh'，决定反演取哪一语言的子句
    joiner: str                               # ', ' | '，'
    bg_suppress: str
    layout: str / layout_neutral: str
    rules: tuple[PromptRule, ...]
```

模板可用占位符：`{hanzi_spaced}` `{hanzi_count}` `{residue}` `{stripped}` `{symbols_spaced}`。

`_MODEL_PROFILE` 把家族映射到 profile：`flux`/`unknown` → `_FLUX_PROFILE`，`zimage`/`qwen_image` → `_ZIMAGE_PROFILE`。**注意 qwen_image 走的是中文模板**。

### 段落顺序

```python
_SECTION_ORDER = ("background", "style", "layout", "content", "accuracy", "inversion")
```

| 序 | 段 | 来源 | 说明 |
|---|---|---|---|
| 1 | background | `profile.bg_suppress` | 常发。下游 Inspyrenet 抠图需要干净背景 |
| 2 | style | `request.prompt` | **提前到这里**，因为布局指令由用户写在 prompt 里 |
| 3 | layout | `profile.layout` 或 `layout_neutral` | 空 `text` 时不发 |
| 4 | content | `rules[section=='content']` | 点名要画什么 |
| 5 | accuracy | `rules[section=='accuracy']` | 约束画得多准 |
| 6 | inversion | `plan.inversion.clauses` | 负面词反演产物 |

改顺序只需改 `_SECTION_ORDER` 这一行。

### 布局意图

`_detect_layout_intent(style_prompt)` 命中 `_LAYOUT_INTENT_RE`（`居中`、`中间`、`右下角`、`layout`、`centered`、`aligned` …）时发 `layout_neutral`，避免默认版式覆盖用户自己写的排布要求。

新增关键词时同时更新 `TestPromptProfileRendering.test_layout_intent_detector_table`。

### rules 一览

| section | key | fires | 备注 |
|---|---|---|---|
| content | `hanzi` | `has_hanzi` | 逐字空格 + 声明字数 |
| content | `residue` | `has_hanzi and residue` | **`suppresses=("digits","symbols")`** |
| content | `literal` | `not has_hanzi and stripped` | 纯拉丁/纯数字走这条 |
| content | `digits` | `has_digits` | |
| content | `symbols` | `has_symbols` | 缺陷修复：`%` 此前无人点名 |
| accuracy | `hanzi_accuracy` | `has_hanzi` | |
| accuracy | `latin_accuracy` | `has_latin` | |

`suppresses` 的效果：`冰川 100%` 由 `residue` 一次性点名 `"100%"`，不再另发数字子句重复强调。

---

## 3. `clip_l` 与 `t5xxl`

`CLIPTextEncodeFlux` 有**两个**文本输入，此前被写入同一串长文本，而 `clip_l` 只有 77 token 上限，静默截断。

现在：

- `t5xxl` ← 全长 `positive_prompt`
- `clip_l` ← `_render_clip_l(ctx)`：只取 `_CLIP_L_SECTIONS = ("background","content","style")`，join 后按**子句边界**截到 `_CLIP_L_MAX_CHARS = 220`（`_truncate_at_boundary` 绝不切半词）

`_estimate_clip_tokens` 是 CLIP BPE 的保守近似（英文按词、数字按串、其余非空白各 1）。`> 70` 记 `clip_l_truncation_risk`——**该字段仅对 flux 家族有意义**，其余家族 `clip_l_used=false`、风险值为 `null`。

> `_CLIP_L_SECTIONS` / `_CLIP_L_MAX_CHARS` 是模块常量而非 profile 字段：两个 profile 取值相同，不是族差异数据。

---

## 4. `NegativeCapability` —— 负面词能否生效

```python
effective = has_sampler
        and negative_node_id is not None
        and not derived_from_positive
        and cfg is not None and cfg > _CFG_NEGATIVE_MIN   # 1.05
```

**必须是与门**：

- 只看 `cfg` → 会漏判「cfg 正常但 negative 指向 `ConditioningZeroOut`」的工作流
- 只看节点 → 会漏判 `flux_schnell`（节点 9 看起来完全正常，但 cfg=1.0 让采样器忽略负面 conditioning）

| `reason` | 含义 |
|---|---|
| `ok` | 生效 |
| `cfg_too_low` | `cfg` 缺失或 ≤ 1.05 |
| `derived_from_positive` | 负向链路上溯到了正向自身（`ConditioningZeroOut`） |
| `no_negative_text_node` | 负向槽位指向的既不是文本编码节点，也无法上溯到 |
| `no_sampler` | 工作流里没有 `KSampler` / `KSamplerAdvanced` |

`blockers` 保留**全部**原因（z-image 同时是 `derived_from_positive` + `cfg_too_low`），`reason` 按 `_BLOCKER_ORDER` 取优先级最高的一个。

### 节点解析

`_resolve_conditioning_nodes` 主路径顺 `KSampler.inputs.positive/negative` 的 `[node_id, slot]` 连线，沿 `_CONDITIONING_PASSTHROUGH`（目前只有 `ConditioningZeroOut: conditioning`）上溯。

**不依赖 JSON 字典插入序**。`flux_schnell.json` 的节点书写顺序是 `1,2,3,4,5,6,7,9,8,10`，所以旧版「按出现顺序取第 1、第 2 个」恰好正确——从 ComfyUI 重新导出一次就会把正负向互换。

回退路径：无采样器时按 `_node_sort_key`（`re.findall(r"\d+")` 转 int 元组）取前两个文本节点。`"57:27" -> (57,27)` 因此排在 `"9" -> (9,)` 之后。

---

## 5. 负面词反演

```python
@dataclass(frozen=True)
class InversionRule:
    key: str
    match: tuple[str, ...]     # 英文项须小写；中文项原样
    clause_en: str
    clause_zh: str
    covered_by: str | None     # 'background' | 'accuracy' | None

def _invert_negative(negative_source, profile, already_present="") -> InversionResult
```

**硬规则**：

1. 进入正向串的字符串**只能**来自 `clause_en` / `clause_zh` 字面量。用户负面词本身永不注入。
2. `clause_*` 内禁止出现 `no` / `not` / `without` / `无` / `没` / `不` —— 有测试遍历全表守住。

`covered_by` 非空表示该语义已由正向的某一段承担，只记账不注入（`complex_background` 已被背景抑制段覆盖；`broken_missing_strokes` 已被 accuracy 段覆盖）。

`_invert_negative` 的三层去重：

1. 同一规则只产生一条子句
2. 两条规则子句相同只保留一条
3. 子句归一化后若已是 `already_present`（基础正向串）的子串则丢弃——防用户把风格描述抄进负面词

未命中词表的用户词进 `unmapped_terms`，**只上报**（metadata + `logger.warning`），绝不注入。

### 新增一条反演规则

1. 在 `_INVERSION_RULES` 追加 `InversionRule`
2. `match` 英文项写小写；中文项原样
3. 若该语义已被 background / accuracy 段覆盖，填 `covered_by`，不要重复注入
4. `clause_*` 写成**肯定表述**，不含否定词
5. 更新 `TestNegativeInversion` 的对应断言

---

## 6. `prompt_synthesis` metadata

`_build_synthesis_block(plan)` 产出，`generate_artwork` 在成功路径挂到 `metadata["prompt_synthesis"]`，stub 路径用 `_build_stub_synthesis_block(request)` 发精简形态。

**`positive_prompt` 是权威值**，必须与产物 `outputs/<task>/workflows/workflow_api.json` 里注入节点的内容**逐字相等**—— `TestPromptSynthesisMetadata.test_positive_prompt_matches_injected_node` 锁住这条，是整套测试里最强的一致性断言。

下游落点：`apps/cli/src/utils/output.mjs` 与 `apps/desktop/src/renderer/App.vue` 都**整体展开** metadata，所以该键出现在 `metadata.json` 的**顶层**，不在 `generation.*` 下。

---

## 7. 改动前的检查清单

- 改 `_analyze_text` 的判定规则 → 跑 `TestClassifyText`（21 条）
- 改 `_SECTION_ORDER` → 跑 `TestPromptProfileRendering.test_style_precedes_content_and_accuracy`
- 改模板文案 → 检查 `"咖 啡"`（逐字拆分）与 `"Latte 2.0"`（residue）两条既有断言
- 加工作流 → 更新 `_MODEL_PROFILE`、`download-models.ps1`、`apps/desktop/electron/main.cjs` 的模型清单（三处）
- 改 `_QWEN_RESOLUTIONS` → 同步 `tests/run-acceptance.ps1` 里硬编码的第二份副本
- 任何改动 → `cd services/txt2img-api && uv run pytest`
