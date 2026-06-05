# 批量生成样例

`art_text_prompts_150.txt` 包含 150 条 CLI / desktop 通用的批量输入，每行格式：

```text
文本 | 风格提示词
```

从项目根目录运行：

```powershell
node apps/cli/bin/gen2vec.mjs batch `
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
