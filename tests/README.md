# 测试集与 CLI 验收

本目录提供面向评审验收的批量提示词集合与 CLI 自动化核验脚本。脚本会先把测试集规范化为 CLI 支持的 `文本 | 风格提示词 | 负面提示词 | seed | resolution` 文本格式，再调用 `gen2vec-cli batch`，最后核验输出产物是否满足赛题要求。

## 测试集

| 套件 | 文件 | 条数 | 用途 |
| --- | --- | ---: | --- |
| small | `tests/fixtures/4×8 小测试集.txt` | 32 | 快速冒烟验收，覆盖国风、节日、英文、促销等类型 |
| large | `tests/fixtures/art_text_prompts_150.txt` | 150 | 标准批量验收，满足赛题“≥100 条”要求 |
| stress | `tests/fixtures/大测试集.txt` | 300 | 压力测试，默认不随 `all` 一起运行 |

## 运行方式

确保桌面端已启动两个后端，或手动启动 `txt2img-api:9001` 和 `vectorizer-api:8000` 后执行：

```bash
node tests/cli-smoke-2.mjs
node tests/cli-acceptance.mjs --suite small
node tests/cli-acceptance.mjs --suite large
```

也可以一次运行小集与标准大集：

```bash
node tests/cli-acceptance.mjs --suite all
```

默认输出写入 `outputs/cli-acceptance/`，该目录已由根 `.gitignore` 忽略。

## 核验内容

脚本会检查：

- `batch_summary.csv` 行数、失败条数、状态字段与输入文本一致性。
- 每个任务目录是否包含 `original.png`、`transparent.png`、`result.svg`、`preview.png`、`metadata.json`、`run.log` 和 `workflows/*`。
- PNG 是否可读、默认尺寸是否为 `1280 x 720`，透明 PNG 是否具备 Alpha 通道。
- SVG 是否具备基础 XML 结构、`viewBox`、可编辑矢量元素，且不允许 `<image>` 或 base64 位图伪 SVG。
- `metadata.json` 是否为合法 JSON，`run.log` 是否包含状态与耗时字段。
- 单条端到端耗时默认不超过 90 秒，矢量化阶段默认不超过 10 秒。

常用调试参数：

```bash
# 只生成规范化输入并打印 CLI 命令，不实际调用后端
node tests/cli-acceptance.mjs --suite small --dry-run

# 核验已经跑完的一份 batch_summary.csv
node tests/cli-acceptance.mjs --suite small --verify-only outputs/cli-acceptance/.../batch_summary.csv

# 运行压力大集合
node tests/cli-acceptance.mjs --suite stress --timeout-minutes 540
```
