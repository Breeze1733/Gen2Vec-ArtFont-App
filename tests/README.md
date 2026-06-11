# 测试集与 CLI 验收

本目录提供面向评审验收的标准测试集与 Windows 原生验收脚本。脚本会先把测试集规范化为 CLI 支持的 `文本 | 风格提示词 | 负面提示词 | seed | resolution` 文本格式，再调用安装包交付的 `gen2vec_cli.exe batch`，最后核验输出产物是否满足赛题要求。

## 测试集

| 套件 | 文件 | 条数 | 用途 |
| --- | --- | ---: | --- |
| acceptance | `tests/fixtures/acceptance.txt` | 300 | 标准批量验收，满足赛题”≥100 条”要求 |

安装包中的 `tests\` 目录会进一步精简，只包含：

```text
tests/
├─ acceptance.txt
├─ run-acceptance.ps1
└─ run-acceptance.bat
```

## 运行方式

确保桌面端已启动两个后端，或手动启动 `txt2img-api:9001` 和 `vectorizer-api:8000` 后执行。评审可直接双击 `.bat`，也可以在 PowerShell 中运行 `.ps1`：

```powershell
.\tests\run-acceptance.ps1
```

对应的双击入口：

```bat
tests\run-acceptance.bat
```

脚本会自动在安装目录、仓库根目录和 `apps\cli\dist\` 中查找 `gen2vec_cli.exe`。如果评审把脚本放在其他位置，可显式指定：

```powershell
.\tests\run-acceptance.ps1 -CliPath "C:\Program Files\矢量艺术字生成器\gen2vec_cli.exe"
```

默认输出写入 `outputs\cli-acceptance\`，该目录已由根 `.gitignore` 忽略。

## 核验内容

脚本会检查：

- `batch_summary.csv` 行数、失败条数、状态字段与输入文本一致性。
- 每个任务目录是否包含 `original.png`、`transparent.png`、`result.svg`、`preview.png`、`metadata.json`、`run.log` 和 `workflows/*`。
- PNG 是否可读、默认尺寸是否为 `1280 x 720`，透明 PNG 是否具备 Alpha 通道。
- SVG 是否具备基础 XML 结构、`viewBox`、可编辑矢量元素，且不允许 `<image>` 或 base64 位图伪 SVG。
- `metadata.json` 是否为合法 JSON，`run.log` 是否包含状态与耗时字段。
- 单条端到端耗时默认不超过 90 秒，矢量化阶段默认不超过 10 秒。

常用调试参数：

```powershell
# 只生成规范化输入并打印 CLI 命令，不实际调用后端
.\tests\run-acceptance.ps1 -DryRun

# 核验已经跑完的一份 batch_summary.csv
.\tests\run-acceptance.ps1 -VerifyOnly outputs\cli-acceptance\...\batch_summary.csv

# 不做矢量化，只验 original.png、metadata、日志和汇总表
.\tests\run-acceptance.ps1 -NoVectorize
```
