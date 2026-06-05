#!/usr/bin/env node

/**
 * Gen2Vec CLI 入口
 * 艺术字矢量化命令行工具
 */

import { parseArgs } from 'node:util'
import { run as runGenerate } from '../src/commands/generate.mjs'
import { run as runVectorize } from '../src/commands/vectorize.mjs'
import { run as runPipeline } from '../src/commands/pipeline.mjs'
import { healthCheck, shutdownBackends } from '../src/api.mjs'

const HELP = `
Gen2Vec CLI - 艺术字矢量化工具

用法:
  gen2vec <command> [options]

命令:
  generate    生成艺术字位图
  vectorize   将位图矢量化为 SVG
  pipeline    完整流水线（文本 → 位图 → SVG）
  health      检查后端服务状态
  shutdown    关闭后端服务（txt2img-api + vectorizer-api）

示例:
  gen2vec generate --text "你好" --prompt "霓虹风格"
  gen2vec vectorize --input artwork.png --preset detailed
  gen2vec pipeline --text "Hello" --vector-preset ultra
  gen2vec shutdown

环境变量:
  TXT2IMG_BACKEND_URL      txt2img 服务地址 (默认: http://127.0.0.1:9001)
  VECTORIZER_BACKEND_URL   矢量化服务地址 (默认: http://127.0.0.1:8000)
  TXT2IMG_WORKFLOW         ComfyUI 工作流名称 (默认: test_z_image_turbo)
`

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
      allowPositionals: true,
    },
  })

  // 显示帮助
  if (values.help || positionals.length === 0) {
    console.log(HELP)
    process.exit(0)
  }

  const command = positionals[0]

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
        console.log('检查后端服务状态...\n')
        const status = await healthCheck()
        console.log(`txt2img 服务:    ${status.txt2img ? '✓ 正常' : '✗ 不可用'}`)
        console.log(`矢量化服务:     ${status.vectorizer ? '✓ 正常' : '✗ 不可用'}`)
        if (!status.txt2img || !status.vectorizer) {
          console.log('\n提示: 请确保后端服务已启动')
          console.log('  cd services/txt2img-api && uv run txt2img-api')
          console.log('  cd services/vectorizer-api && uvicorn app.main:app --port 8000')
        }
        break
      }

      case 'shutdown': {
        console.log('正在关闭后端服务...')
        const result = await shutdownBackends()
        console.log(`txt2img 服务:    ${result.txt2img ? '✓ 已发送关闭请求' : '✗ 失败'}`)
        console.log(`矢量化服务:     ${result.vectorizer ? '✓ 已发送关闭请求' : '✗ 失败'}`)
        console.log('\n两个后端服务已关闭。')
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
