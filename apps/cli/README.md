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
```

| 参数 | 简写 | 说明 | 必填 |
|------|:----:|------|:----:|
| `--text` | `-t` | 艺术字文本 | ✓ |
| `--prompt` | `-p` | 风格提示词 | |
| `--negative` | `-n` | 负面提示词 | |
| `--resolution` | `-r` | 分辨率 (默认: 1024 x 1024) | |
| `--seed` | `-s` | 随机种子 | |
| `--output` | `-o` | 输出 PNG 路径 (默认: {text}.png) | |

### vectorize — 位图矢量化

```powershell
gen2vec vectorize --input artwork.png --preset detailed --preview
gen2vec vectorize -i artwork.png -o result.svg
```

| 参数 | 简写 | 说明 | 必填 |
|------|:----:|------|:----:|
| `--input` | `-i` | 输入图片路径 | ✓ |
| `--output` | `-o` | 输出 SVG 路径 (默认: 输入文件名.svg) | |
| `--preset` | | 矢量化预设: `clean` / `balanced` / `detailed` / `ultra` | |
| `--preview` | | 同时保存预览 PNG | |

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
| `--output-dir` | | 输出目录 (默认: 当前目录) | |

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
| `TXT2IMG_WORKFLOW` | `test_z_image_turbo` |
