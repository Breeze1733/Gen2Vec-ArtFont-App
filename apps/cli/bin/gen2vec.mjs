#!/usr/bin/env node

/**
 * Gen2Vec CLI 入口
 * 艺术字矢量化命令行工具
 *
 * 启动流程：
 *   1. 检查同级 backend/ 目录 → 解压引擎 → 下载模型 → 启动后端
 *   2. 执行用户命令 (generate / vectorize / pipeline / health / shutdown)
 *   3. 退出时清理后端进程
 */

import { parseArgs } from 'node:util'
import { run as runGenerate } from '../src/commands/generate.mjs'
import { run as runVectorize } from '../src/commands/vectorize.mjs'
import { run as runPipeline } from '../src/commands/pipeline.mjs'
import { run as runBatch } from '../src/commands/batch.mjs'
import { healthCheck, shutdownBackends } from '../src/api.mjs'
import { runStartupSequence, shutdownBackendsProcesses, resolveBackendDir } from '../src/startup.mjs'

const VERSION = '0.1.0'

const HELP = `
Gen2Vec CLI v${VERSION} — 矢量艺术字生成器

用法:
  gen2vec <command> [options]

命令:
  generate    生成艺术字位图
  vectorize   将位图矢量化为 SVG
  pipeline    完整流水线（文本 → 位图 → SVG）
  batch       批量生成（文本 → 位图 → SVG，容错执行）
  health      检查后端服务状态
  shutdown    关闭后端服务

选项:
  -h, --help                   显示帮助
  -t, --text <text>            艺术字文本
  -p, --prompt <prompt>        风格提示词
  -n, --negative <text>        负面提示词
  -r, --resolution <res>       分辨率 (默认: 1024 x 1024)
  -s, --seed <n>               随机种子（批量模式时每条递增）
  -o, --output <path>          输出文件路径
  -i, --input <path>           输入图片路径
      --preset <name>          矢量化预设 (clean|balanced|detailed|ultra)
      --vector-preset <name>   矢量化预设 (pipeline / batch 命令)
      --output-dir <dir>       输出目录
      --input-file <path>      批量输入文件（batch 命令）
      --vectorize              是否矢量化（batch 命令，默认开启）
      --preview                保存预览 PNG
      --color-precision <n>    颜色精度 1-16
      --filter-speckle <n>     斑点过滤 1-50
      --corner-threshold <n>   拐角阈值 1-100
      --length-threshold <n>   长度阈值 1-50
      --layer-difference <n>   图层差异 1-50
      --scale <n>              放大倍数 1-4

示例:
  gen2vec generate --text "你好" --prompt "霓虹风格"
  gen2vec vectorize --input artwork.png --preset detailed
  gen2vec pipeline --text "Hello" --vector-preset ultra
  gen2vec batch --text "你好|霓虹风格" --vector-preset detailed
  gen2vec batch --input-file batch.txt --output-dir ./output
  gen2vec health
  gen2vec shutdown

环境变量:
  TXT2IMG_BACKEND_URL     txt2img 服务地址 (默认: http://127.0.0.1:9001)
  VECTORIZER_BACKEND_URL  矢量化服务地址 (默认: http://127.0.0.1:8000)
  TXT2IMG_WORKFLOW        ComfyUI 工作流名称 (默认: test_z_image_turbo)
`

// 记录后端是否由我们启动的（退出时需要关闭）
let startedByUs = false

async function main() {
  const { values, positionals } = parseArgs({
    args: process.argv.slice(2),
    options: {
      help: { type: 'boolean', short: 'h' },
      text: { type: 'string', short: 't' },
      prompt: { type: 'string', short: 'p' },
      negative: { type: 'string', short: 'n' },
      resolution: { type: 'string', short: 'r' },
      seed: { type: 'string', short: 's' },
      output: { type: 'string', short: 'o' },
      'output-dir': { type: 'string' },
      input: { type: 'string', short: 'i' },
      preset: { type: 'string' },
      'vector-preset': { type: 'string' },
      preview: { type: 'boolean' },
    },
    allowPositionals: true,
  })

  // 显示帮助
  if (values.help || positionals.length === 0) {
    console.log(HELP)
    process.exit(0)
  }

  const command = positionals[0]

  // shutdown 命令不需要启动后端
  if (command === 'shutdown') {
    console.log('正在关闭后端服务...\n')
    await shutdownBackends()
    await shutdownBackendsProcesses()
    console.log('✓ 已关闭')
    process.exit(0)
  }

  // 其他命令需要后端在线 → 走启动序列
  const backendDir = resolveBackendDir()
  if (backendDir) {
    console.log(`\n  ⏳ 矢量艺术字生成器 v${VERSION}`)
    const result = await runStartupSequence()
    if (!result.success) {
      console.error('\n错误: 后端服务未就绪，无法执行命令')
      process.exit(1)
    }
    startedByUs = true
  } else {
    // 没有 backend/ 目录，假设后端已手动启动
    // 开发模式下用
  }

  // 执行命令
  try {
    switch (command) {
      case 'generate': {
        if (!values.text) {
          console.error('错误: --text 参数必填')
          process.exit(1)
        }
        await runGenerate({
          text: values.text,
          prompt: values.prompt,
          negative: values.negative,
          resolution: values.resolution,
          seed: values.seed ? parseInt(values.seed, 10) : undefined,
          output: values.output,
        })
        break
      }

      case 'vectorize': {
        if (!values.input) {
          console.error('错误: --input 参数必填')
          process.exit(1)
        }
        await runVectorize({
          input: values.input,
          output: values.output,
          preset: values.preset,
          preview: values.preview,
        })
        break
      }

      case 'pipeline': {
        if (!values.text) {
          console.error('错误: --text 参数必填')
          process.exit(1)
        }
        await runPipeline({
          text: values.text,
          prompt: values.prompt,
          negative: values.negative,
          resolution: values.resolution,
          seed: values.seed ? parseInt(values.seed, 10) : undefined,
          vectorPreset: values['vector-preset'] || values.preset,
          outputDir: values['output-dir'] || '.',
        })
        break
      }

      case 'health': {
        const status = await healthCheck()
        const allOk = status.txt2img && status.vectorizer
        console.log(`txt2img 服务:    ${status.txt2img ? '✓ 正常' : '✗ 不可用'}`)
        console.log(`矢量化服务:     ${status.vectorizer ? '✓ 正常' : '✗ 不可用'}`)
        if (!allOk) {
          process.exit(1)
        }
        break
      }

      default:
        console.error(`未知命令: ${command}`)
        console.log(HELP)
        process.exit(1)
    }
  } catch (err) {
    console.error(`\n错误: ${err.message}`)
    process.exit(1)
  }
}

// 退出清理
process.on('exit', () => {
  if (startedByUs) {
    shutdownBackendsProcesses().catch(() => {})
  }
})

// 响应 Ctrl+C
process.on('SIGINT', async () => {
  console.log('\n正在关闭后端...')
  if (startedByUs) {
    await shutdownBackends()
    await shutdownBackendsProcesses()
  }
  process.exit(0)
})

process.on('SIGTERM', async () => {
  if (startedByUs) {
    await shutdownBackendsProcesses()
  }
  process.exit(0)
})

main()
