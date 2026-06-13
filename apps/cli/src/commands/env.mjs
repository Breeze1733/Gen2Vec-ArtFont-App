/**
 * env 命令 — 显示当前环境与后端状态
 *
 * 用于排障：确认 CLI 连接的 backend URL、health 状态、ComfyUI 工作流配置等。
 * 不依赖后端进程管理，纯只读信息展示。
 */

import { healthCheck } from '../api.mjs'
import { resolveOutputRoot } from '../utils/output.mjs'

const VERSION = '1.0.1'
const CLI_NAME = process.platform === 'win32' ? '.\\gen2vec_cli.exe' : './gen2vec_cli'

const TXT2IMG_URL = process.env.TXT2IMG_BACKEND_URL || 'http://127.0.0.1:9001/api/v1/txt2img'
const VECTORIZER_URL = process.env.VECTORIZER_BACKEND_URL || 'http://127.0.0.1:8000/api/v1/vectorize'
const TXT2IMG_WORKFLOW = process.env.TXT2IMG_WORKFLOW || '(自动选择)'

function fmtBool(value) {
  return value ? '✓ 是' : '✗ 否'
}

export async function run() {
  console.log(`${CLI_NAME} v${VERSION}`)
  console.log('═'.repeat(40))
  console.log('')

  // ── 基本配置 ──
  console.log('【环境配置】')
  console.log(`  TXT2IMG_BACKEND_URL    = ${TXT2IMG_URL}`)
  console.log(`  VECTORIZER_BACKEND_URL  = ${VECTORIZER_URL}`)
  console.log(`  TXT2IMG_WORKFLOW       = ${TXT2IMG_WORKFLOW}`)
  console.log(`  ART_TEXT_OUTPUT_ROOT    = ${process.env.ART_TEXT_OUTPUT_ROOT || '(默认: ./outputs)'}`)
  console.log(`  输出根目录（解析后）    = ${resolveOutputRoot()}`)
  console.log('')

  // ── Node.js 环境 ──
  console.log('【运行环境】')
  console.log(`  Node.js  = ${process.version}`)
  console.log(`  平台     = ${process.platform} ${process.arch}`)
  console.log(`  exe 路径 = ${process.execPath}`)
  console.log(`  工作目录 = ${process.cwd()}`)
  console.log('')

  // ── 后端状态 ──
  console.log('【后端服务状态】')
  const status = await healthCheck()
  console.log(`  txt2img 服务  : ${status.txt2img ? '✓ 正常' : '✗ 不可用'}  (${TXT2IMG_URL.replace('/api/v1/txt2img', '/healthz')})`)
  console.log(`  矢量化服务   : ${status.vectorizer ? '✓ 正常' : '✗ 不可用'}  (${VECTORIZER_URL.replace('/api/v1/vectorize', '/healthz')})`)
  console.log('')

  // ── 使用提示 ──
  if (!status.txt2img || !status.vectorizer) {
    console.log('【操作提示】')
    if (!status.txt2img && !status.vectorizer) {
      console.log('  两个后端均未运行。请先启动"矢量艺术字生成器"桌面应用。')
    } else if (!status.txt2img) {
      console.log('  txt2img 服务未运行。文生图 generate / pipeline / batch 不可用。')
    } else if (!status.vectorizer) {
      console.log('  矢量化服务未运行。vectorize 命令不可用。')
    }
    console.log('')
  }

  console.log('═'.repeat(40))
}
