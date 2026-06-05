# 矢量艺术字生成应用

## 项目结构

```text
Development-Training/
├─ apps/
│  ├─ desktop/                  # Electron + Vue 桌面端
│  └─ cli/                      # Node.js CLI 工具
├─ services/
│  ├─ vectorizer-api/           # 智能矢量化后端
│  └─ txt2img-api/              # 文生图后端
├─ workflows/                   # 文生图工作流与模型流程配置
├─ packages/                    # 共享包
├─ docs/                        # 需求、接口、设计说明
├─ scripts/                     # 开发/构建/发布脚本
└─ README.md
```

## 快速启动联调

所有命令在**项目根目录**下执行。

### txt2img-api 文生图后端（端口 9001）

```powershell
cd services/txt2img-api
uv run txt2img-api
```

### 矢量化后端（端口 8000）

```powershell
cd services/vectorizer-api
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 桌面端

```powershell
cd apps/desktop
npm run electron:dev
```

桌面端默认连接 `http://127.0.0.1:8000/api/v1/vectorize`（矢量化），文生图请求默认转发到 `http://127.0.0.1:9001/api/v1/txt2img`。

可通过完整 endpoint 环境变量覆盖：

```powershell
$env:VECTORIZER_BACKEND_URL="http://127.0.0.1:8000/api/v1/vectorize"
$env:TXT2IMG_BACKEND_URL="http://127.0.0.1:9001/api/v1/txt2img"
npm run electron:dev
```

### CLI 命令行工具

无需 Electron 环境，直接调用后端接口的轻量 CLI。

```powershell
# 查看帮助
node apps/cli/bin/gen2vec.mjs --help

# 检查后端服务状态
node apps/cli/bin/gen2vec.mjs health
```

#### 生成艺术字位图

```powershell
node apps/cli/bin/gen2vec.mjs generate --text "你好" --prompt "霓虹风格" --output hello.png
```

| 参数 | 简写 | 说明 |
|------|------|------|
| `--text` | `-t` | 艺术字文本（必填） |
| `--prompt` | `-p` | 风格提示词 |
| `--negative` | `-n` | 负面提示词 |
| `--resolution` | `-r` | 分辨率，默认 `1024x1024` |
| `--seed` | `-s` | 随机种子 |
| `--output` | `-o` | 输出文件路径 |

#### 矢量化位图为 SVG

```powershell
node apps/cli/bin/gen2vec.mjs vectorize --input artwork.png --preset detailed --preview
```

| 参数 | 简写 | 说明 |
|------|------|------|
| `--input` | `-i` | 输入图片路径（必填） |
| `--output` | `-o` | 输出 SVG 路径 |
| `--preset` | | 矢量化预设：`clean` / `balanced` / `detailed` / `ultra` |
| `--preview` | | 同时保存预览 PNG |

#### 完整流水线（文本 → SVG）

```powershell
node apps/cli/bin/gen2vec.mjs pipeline --text "Hello" --prompt "赛博朋克" --vector-preset ultra --output-dir ./outputs
```

| 参数 | 简写 | 说明 |
|------|------|------|
| `--text` | `-t` | 艺术字文本（必填） |
| `--prompt` | `-p` | 风格提示词 |
| `--negative` | `-n` | 负面提示词 |
| `--resolution` | `-r` | 分辨率 |
| `--seed` | `-s` | 随机种子 |
| `--vector-preset` | | 矢量化预设 |
| `--output-dir` | | 输出目录，默认 `./outputs` |

#### 批量生成（文本 → SVG）

```powershell
node apps/cli/bin/gen2vec.mjs batch `
  --input-file testdata/art_text_prompts_150.txt `
  --output-dir ./outputs/cli-batch-150 `
  --resolution "1024 x 1024" `
  --seed 20260605 `
  --vector-preset balanced
```

批量输入支持 TXT / CSV / JSON。TXT 与桌面端批量输入框一致，每行：

```text
文本 | 风格提示词
```

CLI 默认写出与桌面端一致的任务目录：`original.png`、`transparent.png`、`result.svg`、`preview.png`、`metadata.json`、`run.log`、`workflows/*`；批量模式额外生成 `batch_summary.csv`。

#### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `TXT2IMG_BACKEND_URL` | 文生图服务地址 | `http://127.0.0.1:9001` |
| `VECTORIZER_BACKEND_URL` | 矢量化服务地址 | `http://127.0.0.1:8000` |
| `TXT2IMG_WORKFLOW` | ComfyUI 工作流名称 | 空字符串，使用后端降级链 |
| `ART_TEXT_OUTPUT_ROOT` | 默认输出根目录 | `./outputs` |
