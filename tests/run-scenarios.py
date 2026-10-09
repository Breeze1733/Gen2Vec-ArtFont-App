"""四场景验收脚本：单图矢量化 / 批量生成 / 异常输入 / SVG 打开校验。

一键运行，不需要事先打开 CLI 或桌面端 —— 后端没起就自己拉起。

    python tests/run-scenarios.py

退出码：0 全 PASS / 1 有 FAIL / 2 环境前置失败 / 3 参数错误
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 让直接 python 运行也能正常显示中文（.bat 里另有 chcp 65001）
if sys.platform == "win32":
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)  # type: ignore[attr-defined]
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:
            pass

import acceptance_common as ac  # noqa: E402

TOTAL_SCENARIOS = 4


# ══════════════════════════════════════════════════════════════════════
# 场景三：异常输入（模拟桌面端用户能做出的行为）
# ══════════════════════════════════════════════════════════════════════

def _truncated_png() -> bytes:
    """合法 PNG 头 + 少量随机字节 —— 模拟下载/复制中断的损坏文件。"""
    return b"\x89PNG\r\n\x1a\n" + bytes(range(56))


def scenario_invalid_inputs(ctx: "Context") -> ac.ScenarioResult:
    r = ac.ScenarioResult("异常输入（模拟桌面端用户行为）")
    t0 = time.monotonic()
    txt_url = f"{ctx.txt2img_base}/api/v1/txt2img"
    vec_url = f"{ctx.vectorizer_base}/api/v1/vectorize"

    ac.say("  说明：只测用户在桌面端里真的造得出来的坏输入")
    ac.say("        （桌面端表单只有非空校验，没有任何长度限制）")

    # ── txt2img：用户能造出来的坏输入 ──
    txt_cases: list[tuple[str, dict, str]] = [
        ("文字内容框粘贴 61 字（上限 60）", {"text": "字" * 61}, "string_too_long"),
        ("文字内容框粘贴 200 字", {"text": "字" * 200}, "string_too_long"),
        ("风格提示词粘贴 601 字（上限 600）", {"prompt": "x" * 601}, "string_too_long"),
        ("负面提示词粘贴 601 字（上限 600）", {"negative_prompt": "x" * 601}, "string_too_long"),
    ]
    for label, body, want_type in txt_cases:
        res = ac.post_json(txt_url, body, timeout=30)
        got = ac.first_error_type(res)
        r.record(res.status == 422 and got == want_type,
                 f"txt2img · {label}",
                 f"HTTP {res.status} detail[0].type={got!r}")

    # 自定义分辨率框填非法值（桌面端有该输入框，placeholder「例如 1400x800」）
    for value in ["abc", "0x0", "1024", "1024x-5", ""]:
        res = ac.post_json(txt_url, {"resolution": value}, timeout=30)
        ok = res.status == 422 and ac.first_error_type(res) == "value_error"
        r.record(ok, f"txt2img · 自定义分辨率填 {value!r}",
                 f"HTTP {res.status} type={ac.first_error_type(res)!r}")

    # ── 通用契约：422 的 detail 必须是数组 ──
    res = ac.post_json(txt_url, {"text": "字" * 61}, timeout=30)
    r.record(ac.detail_is_array(res), "契约 · 422 的 detail 是数组（pydantic 风格）",
             f"type={type(res.json().get('detail')).__name__ if res.json() else '?'}")

    # ── vectorizer：用户在「图片矢量化」模式上传文件 ──
    res = ac.post_json(vec_url, {
        "source_type": "upload",
        "image_base64": base64.b64encode(_truncated_png()).decode(),
        "image_name": "broken.png",
    }, timeout=60)
    r.record(res.status == 400 and "Cannot decode image bytes" in ac.detail_text(res),
             "vectorizer · 选了损坏的 PNG（截断文件）",
             f"HTTP {res.status} {ac.detail_text(res)[:60]}")

    res = ac.post_json(vec_url, {
        "source_type": "upload",
        "image_base64": base64.b64encode(b"this is not an image").decode(),
        "image_name": "renamed.txt.png",
    }, timeout=60)
    r.record(res.status == 400 and "Cannot decode image bytes" in ac.detail_text(res),
             "vectorizer · 选了改后缀的文本文件",
             f"HTTP {res.status} {ac.detail_text(res)[:60]}")

    missing = str(ctx.report_dir / "does-not-exist.png")
    res = ac.post_json(vec_url, {"source_type": "upload", "image_path": missing}, timeout=60)
    r.record(res.status == 400 and "does not exist" in ac.detail_text(res),
             "vectorizer · 矢量化时源文件已被移走",
             f"HTTP {res.status} {ac.detail_text(res)[:60]}")

    # ── 通用契约：400 的 detail 必须是字符串（HTTPException 风格）──
    r.record(ac.detail_is_string(res), "契约 · 400 的 detail 是字符串（HTTPException 风格）",
             f"type={type(res.json().get('detail')).__name__ if res.json() else '?'}")

    r.elapsed = time.monotonic() - t0
    return r


# ══════════════════════════════════════════════════════════════════════
# 生成 / 矢量化的公共步骤
# ══════════════════════════════════════════════════════════════════════

SINGLE_TEXT = "念奴娇"
SINGLE_STYLE = "三个中文艺术字，霸气狂草，黑白泼墨风格，红色飞扬线条勾勒，金戈铁马之感"


def _generate(ctx: "Context", text: str, style: str, negative: str = "",
              resolution: str = "1024 x 1024", seed: int = 0) -> tuple[ac.HttpResult, dict, dict]:
    body = {
        "text": text, "prompt": style, "negative_prompt": negative,
        "resolution": resolution, "seed": seed, "format": "PNG", "workflow": "",
    }
    with ac.Heartbeat("生成中"):
        res = ac.post_json(f"{ctx.txt2img_base}/api/v1/txt2img", body, ctx.args.gen_timeout)
    data = res.json() or {}
    return res, (data.get("metadata") or {}), data


def _vectorize(ctx: "Context", png_path: Path, name: str) -> tuple[ac.HttpResult, dict]:
    body = {
        "source_type": "upload", "image_path": str(png_path), "image_name": name,
        "vector": {"preset": "balanced"},
    }
    with ac.Heartbeat("矢量化中", interval=10.0):
        res = ac.post_json(f"{ctx.vectorizer_base}/api/v1/vectorize", body, 600.0)
    return res, (res.json() or {})


def _check_vectorize_result(r: ac.ScenarioResult, res: ac.HttpResult, payload: dict,
                            out_dir: Path, tag: str) -> str | None:
    """校验矢量化响应与产物，返回 SVG 文本（失败返回 None）。"""
    if not r.record(res.status == 200, f"{tag} · 矢量化返回 200",
                    f"HTTP {res.status} {ac.detail_text(res)[:80] if res.status != 200 else ''}"):
        return None

    for field in ("transparent_png", "preview_png", "png"):
        val = payload.get(field) or ""
        ok = isinstance(val, str) and val.startswith(ac.DATA_URL_PNG)
        r.record(ok, f"{tag} · {field} 是 data:image/png;base64")

    svg = payload.get("svg") or ""
    r.record(bool(svg) and svg.lstrip().startswith("<"),
             f"{tag} · svg 非空", f"{len(svg) / 1024:.1f} KB" if svg else "空")
    if not svg:
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        w, h = ac.save_b64_png(payload["transparent_png"], out_dir / "transparent.png")
        ac.save_b64_png(payload["preview_png"], out_dir / "preview.png")
        (out_dir / "result.svg").write_text(svg, encoding="utf-8")
        r.artifacts.append(str(out_dir / "result.svg"))
        r.record(w > 0 and h > 0, f"{tag} · 透明图可解码", f"{w}x{h}")
    except Exception as exc:
        r.fail(f"{tag} · 矢量化解码失败", str(exc)[:100])

    meta = payload.get("metadata") or {}
    q = meta.get("quality") or {}
    fid = q.get("svg_fidelity")
    if fid is None:
        r.warn(f"{tag} · svg_fidelity 为 null（允许）")
    else:
        r.record(isinstance(fid, (int, float)) and 0 <= fid <= 100,
                 f"{tag} · svg_fidelity 在 [0,100]", str(fid))
    return svg


# ══════════════════════════════════════════════════════════════════════
# 场景一：单图矢量化（念奴娇，完整链路 提示词 → 生图 → 矢量化）
# ══════════════════════════════════════════════════════════════════════


def scenario_single(ctx: "Context") -> ac.ScenarioResult:
    r = ac.ScenarioResult("单图矢量化（念奴娇 完整链路）")
    t0 = time.monotonic()
    out = ctx.report_dir / "scenarios" / "01_single"

    if not ac.comfyui_gate(r, ctx.comfyui_host):
        r.elapsed = time.monotonic() - t0
        return r

    res, meta, payload = _generate(ctx, SINGLE_TEXT, SINGLE_STYLE)
    if not r.record(res.status == 200, f"生图 200（text={SINGLE_TEXT}）",
                    f"HTTP {res.status}"):
        r.elapsed = time.monotonic() - t0
        return r

    # 必须真走 ComfyUI —— 这是防「静默走 stub 导致假通过」的核心
    reasons = ac.stub_reasons(meta, payload)
    r.record(not reasons, "真走 ComfyUI（非 stub）", "；".join(reasons) if reasons else
             f'engine={meta.get("engine")} tier={meta.get("fallback_tier")} workflow={meta.get("workflow_used")}')
    if reasons:
        r.elapsed = time.monotonic() - t0
        return r

    r.record(meta.get("workflow_used") == "qwen_image_2512_gguf",
             "路由命中 qwen（念奴娇是纯中文）", f'workflow_used={meta.get("workflow_used")}')
    syn = meta.get("prompt_synthesis") or {}
    r.record(syn.get("text_profile") == "chinese", "文本分类为 chinese",
             f'text_profile={syn.get("text_profile")}')

    lsize = ac.latent_size(payload.get("workflow_api") or {})
    r.record(lsize == (1328, 1328), "qwen 分辨率映射 1024x1024 → 1328x1328", str(lsize))

    # 产物落盘
    out.mkdir(parents=True, exist_ok=True)
    png_path = out / "original.png"
    try:
        w, h = ac.save_b64_png(payload["image_base64"], png_path)
        r.record((w, h) == lsize, "original.png 像素尺寸 == latent 尺寸", f"{w}x{h} vs {lsize}")
        r.artifacts.append(str(png_path))
    except Exception as exc:
        r.fail("original.png 落盘失败", str(exc)[:100])

    vres, vpayload = _vectorize(ctx, png_path, "single-niannujiao.png")
    svg = _check_vectorize_result(r, vres, vpayload, out, "单图")
    if svg:
        ctx.svgs.append(("01_single", svg))

    r.elapsed = time.monotonic() - t0
    return r


# ══════════════════════════════════════════════════════════════════════
# 场景二：批量生成（3 条，三条路由链全命中）
# ══════════════════════════════════════════════════════════════════════


def scenario_batch(ctx: "Context") -> ac.ScenarioResult:
    r = ac.ScenarioResult("批量生成（3 条，覆盖三条路由链）")
    t0 = time.monotonic()
    rows = ac.parse_routes_fixture(ac._REPO_ROOT / "tests" / "fixtures" / "routes.txt")
    r.record(len(rows) == 3, "fixture 解析出 3 条", f"{len(rows)} 条")
    if len(rows) != 3:
        r.elapsed = time.monotonic() - t0
        return r

    if not ac.comfyui_gate(r, ctx.comfyui_host):
        r.elapsed = time.monotonic() - t0
        return r

    root = ctx.report_dir / "scenarios" / "02_batch"
    for i, row in enumerate(rows, 1):
        text = row["text"]
        expected = row["expected_workflow"]
        ac.say(f"  --- 第 {i}/3 条：{text}  （期望 {expected}）")
        out = root / f"{i}_{text.replace(' ', '_')}"
        item_t0 = time.monotonic()

        res, meta, payload = _generate(ctx, text, row["prompt"], row["negative"], row["resolution"])
        if not r.record(res.status == 200, f"#{i} {text} · 生图 200", f"HTTP {res.status}"):
            continue

        reasons = ac.stub_reasons(meta, payload)
        if not r.record(not reasons, f"#{i} {text} · 真走 ComfyUI",
                        "；".join(reasons) if reasons else f'engine={meta.get("engine")}'):
            continue

        tier = meta.get("fallback_tier")
        r.record(tier == 0, f"#{i} {text} · 首选工作流即命中（tier=0）",
                 f"tier={tier}" if tier == 0 else
                 f"主工作流未命中，命中兜底 tier={tier}（workflow_used={meta.get('workflow_used')}）")

        got = meta.get("workflow_used")
        r.record(got == expected, f"#{i} {text} · workflow_used == {expected}",
                 f"实际 {got}")

        syn = meta.get("prompt_synthesis") or {}
        # text_profile 是「文本分类」（chinese/english/mixed），不是渲染模板名（flux/zimage）
        want_profile = row["expected_profile"]
        r.record(syn.get("text_profile") == want_profile,
                 f"#{i} {text} · 文本分类 == {want_profile}", f'实际 {syn.get("text_profile")}')

        want_latent = (1328, 1328) if expected.startswith("qwen") else (1024, 1024)
        lsize = ac.latent_size(payload.get("workflow_api") or {})
        r.record(lsize == want_latent, f"#{i} {text} · latent == {want_latent[0]}x{want_latent[1]}",
                 f"实际 {lsize}")

        out.mkdir(parents=True, exist_ok=True)
        png_path = out / "original.png"
        try:
            w, h = ac.save_b64_png(payload["image_base64"], png_path)
            r.record((w, h) == lsize, f"#{i} {text} · original.png 尺寸 == latent", f"{w}x{h}")
            (out / "metadata.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            r.artifacts.append(str(png_path))
        except Exception as exc:
            r.fail(f"#{i} {text} · original.png 落盘失败", str(exc)[:100])
            continue

        vres, vpayload = _vectorize(ctx, png_path, f"batch-{i}.png")
        svg = _check_vectorize_result(r, vres, vpayload, out, f"#{i} {text}")
        if svg:
            ctx.svgs.append((f"02_batch/{out.name}", svg))

        dt = time.monotonic() - item_t0
        ac.say(f"      [完成] 本条累计 {dt:.1f}s")
        if ctx.args.max_e2e_seconds and dt > ctx.args.max_e2e_seconds:
            r.fail(f"#{i} {text} · 耗时超阈值", f"{dt:.1f}s > {ctx.args.max_e2e_seconds}s")

    r.elapsed = time.monotonic() - t0
    return r


# ══════════════════════════════════════════════════════════════════════
# 场景四：SVG 打开校验
# ══════════════════════════════════════════════════════════════════════


def scenario_svg_open(ctx: "Context") -> ac.ScenarioResult:
    r = ac.ScenarioResult("SVG 打开校验")
    t0 = time.monotonic()
    out = ctx.report_dir / "scenarios" / "04_svg_open"

    if not r.record(bool(ctx.svgs), "有可校验的 SVG", f"{len(ctx.svgs)} 个"):
        r.elapsed = time.monotonic() - t0
        return r

    rendered_any = False
    for name, svg in ctx.svgs:
        ok, why, n_paths = ac.svg_structural_checks(svg)
        r.record(ok, f"{name} · 结构合法（XML/viewBox/矢量元素/无位图）",
                 why if not ok else f"{n_paths} 条 path")
        if not ok:
            continue

        area = ac.svg_bbox_area(svg)
        r.record(area > 0, f"{name} · path 几何包围盒非退化", f"面积 {area:.0f}")

        png = ac.render_svg(svg, 512)
        if png is None:
            continue
        rendered_any = True
        try:
            cov = ac.render_coverage(png)
        except Exception as exc:
            r.fail(f"{name} · 渲染结果不可读", str(exc)[:80])
            continue

        r.record(cov > 0.001, f"{name} · 渲染后像素非空", f"覆盖率 {cov * 100:.1f}%")
        if cov > 0.98:
            r.warn(f"{name} · 覆盖率 {cov * 100:.1f}%（可能有背景层）")
        out.mkdir(parents=True, exist_ok=True)
        stamp = out / (name.replace("/", "_") + ".render.png")
        stamp.write_bytes(png)
        r.artifacts.append(str(stamp))

    if not rendered_any:
        r.warn("渲染级校验未执行（cairosvg 不可用）—— 本次仅做结构级校验")
        r.status = ac.WARN if r.status == ac.PASS else r.status

    r.elapsed = time.monotonic() - t0
    return r


# ══════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════


class Context:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.txt2img_base = args.txt2img_base.rstrip("/")
        self.vectorizer_base = args.vectorizer_base.rstrip("/")
        self.comfyui_host = args.comfyui_host.rstrip("/")
        self.report_dir = Path(args.report_dir) if args.report_dir else (
            ac._REPO_ROOT / "outputs" / f"acceptance_{datetime.now():%Y%m%d_%H%M%S}"
        )
        self.backends: ac.BackendManager | None = None
        self.svgs: list[tuple[str, str]] = []       # (名称, svg 文本)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run-scenarios",
        description="四场景验收：单图矢量化 / 批量生成 / 异常输入 / SVG 打开校验",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--attach", action="store_true", help="只附着已运行的后端，不自行拉起")
    p.add_argument("--keep", action="store_true", help="退出时不关闭本次自行拉起的后端")
    p.add_argument("--skip-batch", action="store_true", help="跳过批量生成场景（省 ~13 分钟）")
    p.add_argument("--report-dir", default="", help="报告输出目录（默认 outputs/acceptance_<时间戳>）")
    p.add_argument("--txt2img-base", default="http://127.0.0.1:9001")
    p.add_argument("--vectorizer-base", default="http://127.0.0.1:8000")
    p.add_argument("--comfyui-host", default=ac.DEFAULT_COMFYUI_HOST)
    p.add_argument("--gen-timeout", type=float, default=1800.0, help="单次生成请求超时秒数")
    p.add_argument("--max-e2e-seconds", type=float, default=0.0,
                   help="单条端到端耗时上限（0 = 只记录不判失败，与旧脚本一致）")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    ctx = Context(args)

    ac.hr()
    ac.say(" 验收脚本 · 四场景")
    ac.hr()
    ac.say("预计总耗时约 20 分钟（其中单条生成 91-285 秒）")
    ac.say("按 Ctrl+C 可随时中断")
    ac.say("")

    # ── 依赖自检 ──
    ac.say(f"[环境] Python: {sys.executable}")
    try:
        import requests  # noqa: F401
    except Exception:
        ac.say("[环境] 缺 requests —— 请用带依赖的 Python 运行（见 tests/README.md）")
        return 2
    has_cairo = ac.render_svg(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 4 4"><path d="M0 0L4 4"/></svg>', 8
    ) is not None
    if has_cairo:
        ac.say("[环境] 依赖自检：requests OK  cairosvg OK（SVG 场景将做渲染级校验）")
    else:
        ac.say("[环境] 依赖自检：requests OK  cairosvg 缺失")
        ac.say(f"[环境]   -> SVG 场景降级为结构级校验")
        ac.say(f"[环境]   -> 补装：{sys.executable} -m pip install cairosvg")

    drift = ac.contract_guard()
    for w in drift:
        ac.say(f"[环境] WARN 常量漂移：{w}")

    # ── 后端生命周期 ──
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    ctx.backends = ac.BackendManager(
        ctx.txt2img_base, ctx.vectorizer_base, args.attach, args.keep,
        ctx.report_dir / "logs",
    )
    ac.say("")
    ok_txt = ctx.backends.ensure("txt2img-api", ctx.txt2img_base, "txt2img-api", ac.TXT2IMG_PORT)
    ok_vec = ctx.backends.ensure("vectorizer-api", ctx.vectorizer_base, "vectorizer-api", ac.VECTORIZER_PORT)
    if not (ok_txt and ok_vec):
        ac.say("")
        ac.say("[环境] 后端未就绪，无法继续。若后端已在别处运行，请加 --attach。")
        ctx.backends.cleanup()
        return 2

    if ok_txt and os.environ.get("AUTO_START_COMFYUI") == "0":
        ac.say("[环境] WARN AUTO_START_COMFYUI=0 —— ComfyUI 不会自动拉起，生成场景会失败")

    # ── 跑场景（顺序固定：场景四要吃场景一/二产出的 SVG）──
    results: list[ac.ScenarioResult] = []
    started = time.monotonic()

    plan: list[tuple[int, str, object]] = [
        (1, "单图矢量化（念奴娇 完整链路）", scenario_single),
        (2, "批量生成（3 条路由）", scenario_batch),
        (3, "异常输入（模拟桌面端用户行为）", scenario_invalid_inputs),
        (4, "SVG 打开校验", scenario_svg_open),
    ]

    for idx, title, fn in plan:
        if idx == 2 and args.skip_batch:
            ac.say("")
            ac.say(f" 场景 {idx}/{TOTAL_SCENARIOS}：{title} —— 已按 --skip-batch 跳过")
            skipped = ac.ScenarioResult(title, status=ac.SKIP)
            results.append(skipped)
            continue
        ac.say("")
        ac.say("=" * 60)
        ac.say(f" 场景 {idx}/{TOTAL_SCENARIOS}：{title}")
        ac.say("=" * 60)
        res = fn(ctx)  # type: ignore[operator]
        results.append(res)
        ac.say(f"  -> {res.status}  ({res.elapsed:.1f}s)")

    # ── 汇总 ──
    total_elapsed = time.monotonic() - started
    ac.say("")
    ac.hr()
    ac.say(" SUMMARY")
    ac.hr()
    for i, res in enumerate(results, 1):
        ac.say(f"  {i} {res.name[:34]:34s} : {res.status:4s}  ({res.elapsed:.1f}s)")
    ac.say(f"  artifacts: {ctx.report_dir}")
    ac.say(f"  累计耗时 {total_elapsed:.1f}s")

    _write_reports(ctx, results, total_elapsed)
    ac.say(f"  report:    {ctx.report_dir / 'report.txt'}")
    ac.say("")

    ctx.backends.cleanup()

    if any(res.status == ac.FAIL for res in results):
        ac.say("EXIT 1")
        return 1
    ac.say("EXIT 0")
    return 0


def _write_reports(ctx: "Context", results: list[ac.ScenarioResult], total: float) -> None:
    report = {
        "script": "run-scenarios.py",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(total, 1),
        "python": sys.executable,
        "txt2img_base": ctx.txt2img_base,
        "vectorizer_base": ctx.vectorizer_base,
        "comfyui_host": ctx.comfyui_host,
        "scenarios": [r.to_dict() for r in results],
    }
    ctx.report_dir.mkdir(parents=True, exist_ok=True)
    (ctx.report_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "四场景验收报告",
        f"生成时间: {report['generated_at']}",
        f"累计耗时: {total:.1f}s",
        f"Python:   {sys.executable}",
        "",
    ]
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r.name}  ->  {r.status}  ({r.elapsed:.1f}s)")
        for c in r.checks:
            detail = f"  ({c.detail})" if c.detail else ""
            lines.append(f"      [{c.status}] {c.label}{detail}")
        lines.append("")
    (ctx.report_dir / "report.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        ac.say("\n中断。")
        raise SystemExit(130)
