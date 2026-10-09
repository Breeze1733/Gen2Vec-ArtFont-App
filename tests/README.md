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

默认输出写入桌面端同一个 `outputs\` 根目录。CLI 会创建一个批量任务目录 `outputs\task_..._batch-run_...`，历史索引只写入根目录的 `outputs\tasks-index.json`。

## 核验内容

脚本会检查：

- `batch_summary.csv` 行数、失败条数、状态字段与输入文本一致性。
- 每个任务目录是否包含 `original.png`、`transparent.png`、`result.svg`、`preview.png`、`metadata.json`、`run.log` 和核心 `workflows/*` 文件。
- PNG 是否可读、默认尺寸是否为 `1664 x 928`；如果 Qwen 工作流映射到官方 16:9 尺寸 `1664 x 928`，记录为警告但不判失败。
- SVG 是否具备基础 XML 结构和可编辑矢量元素，且不允许 `<image>` 或 base64 位图伪 SVG；缺少 `viewBox` 或 `<g>` 分组记录为警告。
- `metadata.json` 是否为合法 JSON，`run.log` 是否包含状态与耗时字段。
- 单条端到端耗时与矢量化耗时默认只记录，不设硬阈值；需要性能门槛时可显式传入 `-MaxE2eMs` 或 `-MaxVectorMs`。
- 批量汇总 CSV 会包含 `generation_ms`、`vector_ms`、`png_transparency`、`svg_fidelity`，并保留 `run_log_path` 便于追溯每条任务日志。

常用调试参数：

```powershell
# 只生成规范化输入并打印 CLI 命令，不实际调用后端
.\tests\run-acceptance.ps1 -DryRun

# 核验已经跑完的一份 batch_summary.csv
.\tests\run-acceptance.ps1 -VerifyOnly outputs\task_...\batch_summary.csv

# 不做矢量化，只验 original.png、metadata、日志和汇总表
.\tests\run-acceptance.ps1 -NoVectorize
```

---

## 四场景验收脚本（run-scenarios）

`run-acceptance.ps1` 只覆盖批量生成。`run-scenarios` 覆盖四个场景，与前者并存：

| # | 场景 | 内容 |
| --- | --- | --- |
| 1 | 单图矢量化 | 输入「念奴娇」，走完整链路：提示词 → 文生图 → 矢量化 |
| 2 | 批量生成 | 3 条输入，分别命中 Qwen / Flux / Z-Image 三条路由链 |
| 3 | 异常输入 | 超长文本、非法自定义分辨率、损坏或改后缀的图片、源文件被移走 |
| 4 | SVG 打开校验 | 把产出的 SVG 真正渲染成 PNG，校验图形非空，而不只是 XML 能解析 |

### 运行

双击 `tests\run-scenarios.bat`。

**不需要预先打开桌面端或 CLI** —— 后端没在运行的话脚本会自己拉起（连同 ComfyUI）；已在运行的则直接复用，退出时不动它。预计 7-20 分钟，全程打印进度与已等待时间。

### 结果

报告写入 `outputs/acceptance_<时间戳>/`，含 `report.txt`、`report.json`、各场景产物与运行日志。

| 退出码 | 含义 |
| ---: | --- |
| 0 | 四个场景全部通过 |
| 1 | 有场景失败 |
| 2 | 环境不可用（后端连不上也拉不起） |
| 3 | 参数错误 |

### 说明

ComfyUI 不可用时，后端会静默回落到占位图。脚本对生成类场景设有 ComfyUI 门禁，并逐条核对响应不是占位图产物，避免出现「全部通过但什么都没生成」。
