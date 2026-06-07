#!/usr/bin/env node

/**
 * Gen2Vec CLI — 矢量艺术字生成器命令行工具
 *
 * 定位：随桌面端安装包交付的自动化验收控制台。
 * 不管理后端生命周期，假设后端已由桌面端启动或用户自行启动。
 *
 * 用法:
 *   gen2vec-cli <command> [options]
 *
 * 命令:
 *   generate    生成艺术字位图 (txt2img-api)
 *   vectorize   将位图矢量化为 SVG (vectorizer-api)
 *   pipeline    完整流水线：文本 → 位图 → SVG
 *   batch       批量流水线（支持 TXT/CSV/JSON）
 *   env         显示当前环境与后端状态
 *   health      检查后端服务状态
 *   shutdown    关闭后端服务
 */

import { parseArgs } from 'node:util'
import { healthCheck, shutdownBackends } from '../src/api.mjs'
import { run as runGenerate } from '../src/commands/generate.mjs'
import { run as runVectorize } from '../src/commands/vectorize.mjs'
import { run as runPipeline } from '../src/commands/pipeline.mjs'
import { run as runBatch } from '../src/commands/batch.mjs'
import { run as runEnv } from '../src/commands/env.mjs'

const VERSION = '1.0.0'
const CLI_NAME = 'gen2vec-cli'

const HELP = `
${CLI_NAME} v${VERSION} — 矢量艺术字生成器 · 自动化验收控制台

用法:
  ${CLI_NAME} <command> [options]

命令:
  generate    生成艺术字位图
  vectorize   将位图矢量化为 SVG
  pipeline    完整流水线（文本 → 位图 → SVG）
  batch       批量流水线（文本 → 位图 → SVG，容错执行）
  env         显示当前环境与后端状态
  health      检查后端服务状态
  shutdown    关闭后端服务

选项:
  -h, --help                   显示帮助
  -t, --text <text>            艺术字文本
  -p, --prompt <prompt>        风格提示词
  -n, --negative <text>        负面提示词
  -r, --resolution <res>       分辨率 (默认: 1024 x 1024)
  -s, --seed <n>               随机种子
  -o, --output <path>          额外输出文件路径
  -i, --input <path>           输入图片路径
      --preset <name>          矢量化预设 (clean|balanced|detailed|ultra)
      --vector-preset <name>   矢量化预设 (pipeline / batch 命令)
      --output-dir <dir>       输出目录 (默认: ./outputs)
      --input-file <path>      批量输入文件（batch 命令）
      --no-vectorize           批量模式只生成 original.png，不做矢量化
      --seed-step <n>          批量模式每条 seed 递增步长（默认: 0）
      --preview                保存预览 PNG
      --color-precision <n>    颜色精度 1-16
      --filter-speckle <n>     斑点过滤 1-50
      --corner-threshold <n>   拐角阈值 1-100
      --length-threshold <n>   长度阈值 1-50
      --layer-difference <n>   图层差异 1-50
      --scale <n>              放大倍数 1-4
      --wait <n>               等待后端就绪的最大秒数（默认: 0，不等待）

环境变量:
  TXT2IMG_BACKEND_URL      txt2img 服务地址 (默认: http://127.0.0.1:9001/api/v1/txt2img)
  VECTORIZER_BACKEND_URL   矢量化服务地址 (默认: http://127.0.0.1:8000/api/v1/vectorize)
  TXT2IMG_WORKFLOW         ComfyUI 工作流名称
  ART_TEXT_OUTPUT_ROOT     默认输出根目录 (默认: ./outputs)

场景示例:
  评审验收 — 单条测试:
    ${CLI_NAME} pipeline --text "七里香" --prompt "清新国风、墨绿色金边"

  评审验收 — 批量 150 条:
    ${CLI_NAME} batch --input-file testdata/art_text_prompts_150.txt --output-dir ./outputs/cli-batch-150

  图片矢量化:
    ${CLI_NAME} vectorize --input artwork.png --preset detailed

  环境检查:
    ${CLI_NAME} env
`

/**
 * 检查后端是否就绪，如不可用则报错退出。
 * CLI 不启动后端，仅做前置校验。
 */
async function ensureBackendReady(waitSeconds = 0) {
  const deadline = Date.now() + waitSeconds * 1000
  let lastCheck = null

  while (Date.now() < deadline) {
    lastCheck = await healthCheck()
    if (lastCheck.txt2img && lastCheck.vectorizer) return true
    if (Date.now() < deadline) {
      await new Promise(r => setTimeout(r, 1000))
    }
  }

  // waitSeconds 为 0 时直接到这里（只检查一次）
  if (!lastCheck) lastCheck = await healthCheck()

  if (!lastCheck.txt2img && !lastCheck.vectorizer) {
    console.error(`\n错误: 后端服务未运行 (txt2img:9001, vectorizer:8000)`)
    console.error(`请先启动"矢量艺术字生成器"桌面应用，或手动启动后端服务。`)
    console.error(`提示: 可通过 Set-TXT2IMG_BACKEND_URL / VECTORIZER_BACKEND_URL 环境变量指定自定义地址。`)
    console.error(`      或运行 "${CLI_NAME} env" 查看详情。`)
    return false
  }
  if (!lastCheck.txt2img) {
    console.error(`\n错误: txt2img 服务不可用 (9001)，文生图功能不可用。`)
    return false
  }
  if (!lastCheck.vectorizer) {
    console.error(`\n错误: 矢量化服务不可用 (8000)，矢量化功能不可用。`)
    return false
  }
  return true
}

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
      'input-file': { type: 'string' },
      'no-vectorize': { type: 'boolean' },
      'seed-step': { type: 'string' },
      preview: { type: 'boolean' },
      'color-precision': { type: 'string' },
      'filter-speckle': { type: 'string' },
      'corner-threshold': { type: 'string' },
      'length-threshold': { type: 'string' },
      'layer-difference': { type: 'string' },
      scale: { type: 'string' },
      wait: { type: 'string' },
    },
    allowPositionals: true,
  })

  // 显示帮助
  if (values.help || positionals.length === 0) {
    console.log(HELP)
    process.exit(0)
  }

  const command = positionals[0]

  // 不需要后端的命令
  if (command === 'help') {
    console.log(HELP)
    process.exit(0)
  }

  if (command === 'env') {
    await runEnv()
    process.exit(0)
  }

  if (command === 'shutdown') {
    console.log('正在关闭后端服务...')
    await shutdownBackends()
    console.log('✓ 已发送关闭请求')
    process.exit(0)
  }

  // health 也不需要等待
  if (command === 'health') {
    const status = await healthCheck()
    const allOk = status.txt2img && status.vectorizer
    console.log(`txt2img 服务:    ${status.txt2img ? '✓ 正常' : '✗ 不可用'}`)
    console.log(`矢量化服务:     ${status.vectorizer ? '✓ 正常' : '✗ 不可用'}`)
    process.exit(allOk ? 0 : 1)
  }

  // ── 以下命令需要后端 ──
  const waitSeconds = values.wait ? Math.max(0, parseInt(values.wait, 10) || 0) : 0
  const backendReady = await ensureBackendReady(waitSeconds)
  if (!backendReady) {
    process.exit(1)
  }

  const parseNumber = (value, name) => {
    if (value === undefined || value === null || value === '') return undefined
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) {
      throw new Error(`${name} 必须是数字`)
    }
    return parsed
  }

  const buildVectorConfig = () => {
    const vector = {}
    const preset = values['vector-preset'] || values.preset
    if (preset) vector.preset = preset
    const mappings = [
      ['color-precision', 'colorPrecision'],
      ['filter-speckle', 'filterSpeckle'],
      ['corner-threshold', 'cornerThreshold'],
      ['length-threshold', 'lengthThreshold'],
      ['layer-difference', 'layerDifference'],
      ['scale', 'scale'],
    ]
    for (const [optionName, apiName] of mappings) {
      const parsed = parseNumber(values[optionName], `--${optionName}`)
      if (parsed !== undefined) vector[apiName] = parsed
    }
    return vector
  }

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
          seed: parseNumber(values.seed, '--seed'),
          output: values.output,
          outputDir: values['output-dir'] || 'outputs',
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
          outputDir: values['output-dir'] || 'outputs',
          vector: buildVectorConfig(),
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
          seed: parseNumber(values.seed, '--seed'),
          vectorPreset: values['vector-preset'] || values.preset,
          outputDir: values['output-dir'] || 'outputs',
          output: values.output,
          vector: buildVectorConfig(),
        })
        break
      }

      case 'batch': {
        if (!values.text && !values['input-file']) {
          console.error('错误: batch 命令需要 --text 或 --input-file')
          process.exit(1)
        }
        await runBatch({
          input: values.text,
          inputFile: values['input-file'],
          negative: values.negative,
          resolution: values.resolution,
          seed: parseNumber(values.seed, '--seed') ?? 0,
          seedStep: parseNumber(values['seed-step'], '--seed-step') ?? 0,
          vectorPreset: values['vector-preset'] || values.preset,
          vector: buildVectorConfig(),
          outputDir: values['output-dir'] || 'outputs',
          vectorize: !values['no-vectorize'],
        })
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

main()
