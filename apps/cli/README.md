# Gen2Vec CLI

艺术字矢量化命令行工具，与 desktop 共用相同的后端接口。

## 目录结构

```
apps/cli/
├── bin/
│   └── gen2vec.mjs          # CLI 入口
├── src/
│   ├── api.mjs              # 后端 API 调用层
│   ├── commands/
│   │   ├── generate.mjs     # txt2img 命令
│   │   ├── vectorize.mjs    # 矢量化命令
│   │   └── pipeline.mjs     # 完整流水线
│   └── utils/
│       └── file.mjs         # 文件操作工具
└── README.md
```

## 前置依赖

需要启动后端服务：

```powershell
# 终端 1: txt2img 服务 (端口 9001)
cd services/txt2img-api
uv run txt2img-api

# 终端 2: 矢量化服务 (端口 8000)
cd services/vectorizer-api
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## 使用方法

### 直接运行（无需安装）

```powershell
node apps/cli/bin/gen2vec.mjs <command> [options]
```

### 全局安装（待配置 package.json）

```powershell
cd apps/cli
npm link
gen2vec <command> [options]
```

## 命令

### generate - 生成艺术字位图

```powershell
gen2vec generate --text "你好" --prompt "霓虹风格" --output hello.png
```

**参数:**
| 参数 | 简写 | 说明 | 必填 |
|------|------|------|------|
| `--text` | `-t` | 艺术字文本 | ✓ |
| `--prompt` | `-p` | 风格提示词 | |
| `--negative` | `-n` | 负面提示词 | |
| `--resolution` | `-r` | 分辨率 (默认: 1024x1024) | |
| `--seed` | `-s` | 随机种子 | |
| `--output` | `-o` | 输出文件路径 | |

### vectorize - 将位图矢量化为 SVG

```powershell
gen2vec vectorize --input artwork.png --preset detailed --preview
```

**参数:**
| 参数 | 简写 | 说明 | 必填 |
|------|------|------|------|
| `--input` | `-i` | 输入图片路径 | ✓ |
| `--output` | `-o` | 输出 SVG 路径 | |
| `--preset` | | 矢量化预设 (clean/balanced/detailed/ultra) | |
| `--preview` | | 保存预览 PNG | |

### pipeline - 完整流水线

```powershell
gen2vec pipeline --text "Hello" --prompt "赛博朋克" --vector-preset ultra
```

**参数:**
| 参数 | 简写 | 说明 | 必填 |
|------|------|------|------|
| `--text` | `-t` | 艺术字文本 | ✓ |
| `--prompt` | `-p` | 风格提示词 | |
| `--negative` | `-n` | 负面提示词 | |
| `--resolution` | `-r` | 分辨率 | |
| `--seed` | `-s` | 随机种子 | |
| `--vector-preset` | | 矢量化预设 | |
| `--output-dir` | | 输出目录 | |

### health - 检查后端服务状态

```powershell
gen2vec health
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `TXT2IMG_BACKEND_URL` | txt2img 服务地址 | `http://127.0.0.1:9001` |
| `VECTORIZER_BACKEND_URL` | 矢量化服务地址 | `http://127.0.0.1:8000` |
| `TXT2IMG_WORKFLOW` | ComfyUI 工作流名称 | `test_z_image_turbo` |

## package.json 配置（待定）

```json
{
  "name": "gen2vec-cli",
  "version": "0.1.0",
  "type": "module",
  "bin": {
    "gen2vec": "./bin/gen2vec.mjs"
  },
  "engines": {
    "node": ">=18.0.0"
  }
}
```
