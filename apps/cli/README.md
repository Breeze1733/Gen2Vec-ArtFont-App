# Gen2Vec CLI

矢量艺术字生成器命令行工具。

## 运行方式

```powershell
# 安装桌面端后，在安装目录下:
gen2vec_cli <command> [options]

# 或者源码直接运行（需要 Node.js 18+）:
node apps/cli/bin/gen2vec.mjs <command> [options]
```

## 命令

### generate — 生成艺术字位图

```powershell
gen2vec generate --text "你好" --prompt "霓虹风格" --output hello.png
gen2vec generate -t "你好" -p "霓虹风格" -o hello.png
gen2vec generate --text "你好" --prompt "霓虹风格" --output-dir ./outputs
```

| 参数 | 简写 | 说明 | 必填 |
|------|:----:|------|:----:|
| `--text` | `-t` | 艺术字文本 | ✓ |
| `--prompt` | `-p` | 风格提示词 | |
| `--negative` | `-n` | 负面提示词 | |
| `--resolution` | `-r` | 分辨率 (默认: 1024 x 1024) | |
| `--seed` | `-s` | 随机种子 | |
| `--output` | `-o` | 兼容模式：额外输出单个 PNG 路径 | |
| `--output-dir` | | desktop-compatible 任务输出根目录 (默认: `./outputs`) | |

### vectorize — 位图矢量化

```powershell
gen2vec vectorize --input artwork.png --preset detailed --preview
gen2vec vectorize -i artwork.png -o result.svg
gen2vec vectorize --input artwork.png --preset balanced --output-dir ./outputs
```

| 参数 | 简写 | 说明 | 必填 |
|------|:----:|------|:----:|
| `--input` | `-i` | 输入图片路径 | ✓ |
| `--output` | `-o` | 兼容模式：额外输出 SVG 路径 | |
| `--preset` | | 矢量化预设: `clean` / `balanced` / `detailed` / `ultra` | |
| `--preview` | | 同时保存预览 PNG | |
| `--output-dir` | | desktop-compatible 任务输出根目录 (默认: `./outputs`) | |

### pipeline — 全流程（文本 → 位图 → SVG）

```powershell
gen2vec pipeline --text "Hello" --prompt "赛博朋克" --vector-preset ultra --output-dir ./outputs
```

| 参数 | 简写 | 说明 | 必填 |
|------|:----:|------|:----:|
| `--text` | `-t` | 艺术字文本 | ✓ |
| `--prompt` | `-p` | 风格提示词 | |
| `--negative` | `-n` | 负面提示词 | |
| `--resolution` | `-r` | 分辨率 | |
| `--seed` | `-s` | 随机种子 | |
| `--vector-preset` | | 矢量化预设 | |
| `--output-dir` | | 输出目录 (默认: `./outputs`) | |
| `--output` | `-o` | 兼容模式：额外输出 SVG，并在同目录输出同名 PNG | |

### batch — 批量全流程（文本 → 位图 → SVG）

批量输入支持 TXT / CSV / JSON；TXT 与桌面端输入框一致，每行一条：

```text
文本 | 风格提示词 | 负面提示词 | seed | resolution
```

常用命令：

```powershell
gen2vec batch --input-file batch.txt --output-dir ./outputs/batch-demo --vector-preset balanced
gen2vec batch --text "你好|霓虹风格`n世界|金属浮雕" --seed 20260605 --seed-step 1
gen2vec batch --input-file batch.txt --no-vectorize
```

150 条生成指令样例：

```powershell
gen2vec batch `
  --input-file testdata/art_text_prompts_150.txt `
  --output-dir ./outputs/cli-batch-150 `
  --resolution "1024 x 1024" `
  --seed 20260605 `
  --vector-preset balanced `
  --color-precision 4 `
  --filter-speckle 18 `
  --corner-threshold 70 `
  --length-threshold 12 `
  --layer-difference 20 `
  --scale 2
```

| 参数 | 简写 | 说明 | 必填 |
|------|:----:|------|:----:|
| `--text` | `-t` | 直接传入一行或多行批量输入；与 `--input-file` 二选一 | |
| `--input-file` | | 批量输入文件 TXT / CSV / JSON；与 `--text` 二选一 | |
| `--negative` | `-n` | 全局负面提示词，行内第 3 列可覆盖 | |
| `--resolution` | `-r` | 全局分辨率，行内第 5 列可覆盖 | |
| `--seed` | `-s` | 全局随机种子；默认和桌面端一样每条使用同一个 seed | |
| `--seed-step` | | 每条 seed 递增步长；需要每条不同 seed 时设为 `1` | |
| `--vector-preset` | | 矢量化预设 | |
| `--no-vectorize` | | 只生成 `original.png`，不执行矢量化 | |
| `--output-dir` | | 输出目录 (默认: `./outputs`) | |

## 输出结构

默认输出与桌面端对齐，每个任务目录固定包含：

```text
task_YYYYMMDD_HHMMSS_mmm[_001]/
├─ original.png
├─ transparent.png
├─ result.svg
├─ preview.png
├─ metadata.json
├─ run.log
└─ workflows/
   ├─ workflow_api.json
   ├─ nodes.md
   └─ model_dependencies.json
```

批量模式会额外在汇总目录写入 `batch_summary.csv`，每条成功或失败都会落一行，便于验收和重跑。

### health — 检查后端状态

```powershell
gen2vec health
# txt2img 服务:    ✓ 正常
# 矢量化服务:     ✓ 正常
```

### shutdown — 关闭后端

```powershell
gen2vec shutdown
```

## 矢量化预设

| 预设 | 颜色精度 | 去噪强度 | 角点阈值 | 长度阈值 | 图层差异 | 缩放 |
|------|:--------:|:--------:|:--------:|:--------:|:--------:|:----:|
| `clean` | 2 | 48 | 120 | 30 | 38 | 2 |
| `balanced` | 4 | 18 | 70 | 12 | 20 | 2 |
| `detailed` | 6 | 2 | 30 | 3 | 4 | 3 |
| `ultra` | 8 | 1 | 20 | 2 | 2 | 3 |

## 环境变量

| 变量 | 默认值 |
|------|--------|
| `TXT2IMG_BACKEND_URL` | `http://127.0.0.1:9001/api/v1/txt2img` |
| `VECTORIZER_BACKEND_URL` | `http://127.0.0.1:8000/api/v1/vectorize` |
| `TXT2IMG_WORKFLOW` | 空字符串，使用后端降级链 |
| `ART_TEXT_OUTPUT_ROOT` | `./outputs` |
