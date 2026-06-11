#!/usr/bin/env node

/**
 * CLI acceptance runner for Gen2Vec.
 *
 * It executes the delivery CLI in batch mode, then verifies the generated
 * artifact contract required by the competition brief:
 * original PNG, transparent PNG, SVG, preview PNG, metadata, run log, workflow
 * snapshot, and batch summary CSV.
 */

import { spawn } from 'node:child_process'
import { access, mkdir, readdir, readFile, stat, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const TESTS_DIR = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(TESTS_DIR, '..')
const CLI_ENTRY = path.join(REPO_ROOT, 'apps', 'cli', 'bin', 'gen2vec.mjs')

const DEFAULT_NEGATIVE = [
  'low quality',
  'blurry',
  'wrong text',
  'missing character',
  'extra character',
  'garbled letters',
  'busy background',
  'human figure',
  'watermark',
].join(', ')

const SUITES = {
  small: {
    label: '小测试集',
    fixture: path.join(REPO_ROOT, 'tests', 'fixtures', '4×8 小测试集.txt'),
    minRows: 32,
    exactRows: 32,
    seed: 2026061101,
    timeoutMinutes: 90,
  },
  large: {
    label: '大测试集',
    fixture: path.join(REPO_ROOT, 'tests', 'fixtures', 'art_text_prompts_150.txt'),
    minRows: 100,
    exactRows: 150,
    seed: 2026061201,
    timeoutMinutes: 270,
  },
  stress: {
    label: '压力大测试集',
    fixture: path.join(REPO_ROOT, 'tests', 'fixtures', '大测试集.txt'),
    minRows: 100,
    exactRows: 300,
    seed: 2026061301,
    timeoutMinutes: 540,
  },
}

function printUsage() {
  console.log(`
Gen2Vec CLI 自动化验收脚本

用法:
  node tests/cli-acceptance.mjs --suite small
  node tests/cli-acceptance.mjs --suite large
  node tests/cli-acceptance.mjs --suite all

常用选项:
  --suite <small|large|stress|all>  选择测试集，默认 small
  --fixture <path>                  自定义输入测试集（覆盖 suite fixture）
  --min-rows <number>               自定义 fixture 最少条数，默认 1
  --cli <path>                      CLI 入口，默认 apps/cli/bin/gen2vec.mjs
  --output-root <dir>               输出根目录，默认 outputs/cli-acceptance
  --wait <seconds>                  等待后端健康检查，默认 30
  --resolution <value>              CLI 分辨率，默认 "1280 x 720"
  --vector-preset <name>            矢量化预设，默认 balanced
  --seed <number>                   起始 seed，默认按 suite 固定
  --seed-step <number>              每条 seed 递增步长，默认 1
  --negative <text>                 全局负面提示词
  --allow-status <csv>              允许的非失败状态，默认 success,degraded
  --max-failures <number>           允许失败条数，默认 0
  --max-e2e-ms <number>             单条端到端阈值，默认 90000，0 表示不检查
  --max-vector-ms <number>          单条矢量化阈值，默认 10000，0 表示不检查
  --no-vectorize                    只验收 original/metadata/log，不验 SVG 链路
  --strict-svg-groups               缺少 <g> 分组时判失败（默认只警告）
  --allow-resolution-mismatch       PNG 尺寸不等于 resolution 时只警告
  --skip-health                     不单独执行 health 等待，直接运行 batch
  --dry-run                         只规范化测试集并打印 CLI 命令
  --verify-only <batch_summary.csv> 只核验已有 batch_summary.csv
`)
}

function parseArgs(argv) {
  const args = {}
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i]
    if (!token.startsWith('--')) {
      throw new Error(`未知参数: ${token}`)
    }
    const eq = token.indexOf('=')
    if (eq > -1) {
      args[token.slice(2, eq)] = token.slice(eq + 1)
      continue
    }
    const key = token.slice(2)
    const next = argv[i + 1]
    if (!next || next.startsWith('--')) {
      args[key] = true
    } else {
      args[key] = next
      i += 1
    }
  }
  return args
}

function resolvePath(value) {
  if (!value) return value
  return path.isAbsolute(value) ? value : path.resolve(REPO_ROOT, value)
}

function formatTimestamp(date = new Date()) {
  const pad = (value, width = 2) => String(value).padStart(width, '0')
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
    '-',
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds()),
  ].join('')
}

function sanitizeCliToken(value) {
  return String(value).replace(/\u3000/g, ' ').trim()
}

function splitPromptLine(rawLine) {
  const line = sanitizeCliToken(rawLine)
    .replace(/\uFEFF/g, '')
    .replace(/｜/g, '|')
    .replace(/\t+\|/g, '|')
    .replace(/\|\t+/g, '|')
    .trim()

  if (!line || line.startsWith('#')) return null

  const delimiter = line.includes('|') ? '|' : (line.includes('\t') ? '\t' : '')
  if (!delimiter) {
    return { text: line, prompt: '', negative: '', seed: '', resolution: '' }
  }

  const parts = line.split(delimiter).map((part) => sanitizeCliToken(part))
  const [text = '', prompt = '', negative = '', seed = '', resolution = ''] = parts
  if (!text && !prompt) return null
  return { text, prompt, negative, seed, resolution }
}

async function prepareFixture({ fixturePath, preparedPath, suite }) {
  const content = await readFile(fixturePath, 'utf8')
  const rows = content.split(/\r?\n/).map(splitPromptLine).filter(Boolean)

  if (suite.exactRows && rows.length !== suite.exactRows) {
    throw new Error(`${suite.label}应为 ${suite.exactRows} 条，当前为 ${rows.length} 条: ${fixturePath}`)
  }
  if (rows.length < suite.minRows) {
    throw new Error(`${suite.label}至少需要 ${suite.minRows} 条，当前为 ${rows.length} 条: ${fixturePath}`)
  }

  const normalized = rows.map((row) => {
    const parts = [row.text, row.prompt, row.negative, row.seed, row.resolution]
    while (parts.length > 2 && !parts[parts.length - 1]) parts.pop()
    return parts.join(' | ')
  }).join('\n') + '\n'

  await mkdir(path.dirname(preparedPath), { recursive: true })
  await writeFile(preparedPath, normalized, 'utf8')
  return rows
}

function buildCliInvocation(cliPath) {
  const resolved = resolvePath(cliPath)
  if (/\.m?js$/i.test(resolved)) {
    return { command: process.execPath, baseArgs: [resolved] }
  }
  return { command: resolved, baseArgs: [] }
}

function runCommand(command, args, { timeoutMs = 0, live = true, cwd = REPO_ROOT } = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd,
      env: process.env,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    })

    let stdout = ''
    let stderr = ''
    let timedOut = false
    const timer = timeoutMs > 0 ? setTimeout(() => {
      timedOut = true
      child.kill('SIGTERM')
    }, timeoutMs) : null

    child.stdout.on('data', (chunk) => {
      const text = chunk.toString()
      stdout += text
      if (live) process.stdout.write(text)
    })
    child.stderr.on('data', (chunk) => {
      const text = chunk.toString()
      stderr += text
      if (live) process.stderr.write(text)
    })
    child.on('error', (error) => {
      if (timer) clearTimeout(timer)
      resolve({ code: 1, stdout, stderr: `${stderr}${error.message}`, timedOut })
    })
    child.on('close', (code) => {
      if (timer) clearTimeout(timer)
      resolve({ code: code ?? 1, stdout, stderr, timedOut })
    })
  })
}

async function waitForHealth(invocation, waitSeconds) {
  const deadline = Date.now() + waitSeconds * 1000
  let last = null

  do {
    last = await runCommand(invocation.command, [...invocation.baseArgs, 'health'], { live: false, timeoutMs: 10000 })
    if (last.code === 0) {
      console.log('后端健康检查通过。')
      return
    }
    if (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 1000))
    }
  } while (Date.now() < deadline)

  const output = `${last?.stdout || ''}${last?.stderr || ''}`.trim()
  throw new Error(`后端健康检查失败，请先启动桌面端或两个后端服务。\n${output}`)
}

async function findFilesByName(rootDir, fileName) {
  const found = []
  async function walk(current) {
    let entries = []
    try {
      entries = await readdir(current, { withFileTypes: true })
    } catch {
      return
    }
    for (const entry of entries) {
      const next = path.join(current, entry.name)
      if (entry.isDirectory()) {
        await walk(next)
      } else if (entry.isFile() && entry.name === fileName) {
        found.push(next)
      }
    }
  }
  await walk(rootDir)
  return found
}

function parseCsv(text) {
  const rows = []
  let row = []
  let cell = ''
  let quoted = false

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i]
    const next = text[i + 1]
    if (char === '"' && quoted && next === '"') {
      cell += '"'
      i += 1
    } else if (char === '"') {
      quoted = !quoted
    } else if (char === ',' && !quoted) {
      row.push(cell)
      cell = ''
    } else if ((char === '\n' || char === '\r') && !quoted) {
      if (char === '\r' && next === '\n') i += 1
      row.push(cell)
      if (row.some((value) => value !== '')) rows.push(row)
      row = []
      cell = ''
    } else {
      cell += char
    }
  }
  if (cell || row.length > 0) {
    row.push(cell)
    if (row.some((value) => value !== '')) rows.push(row)
  }
  return rows
}

function csvObjects(text) {
  const rows = parseCsv(text)
  const header = rows.shift() || []
  return rows.map((row) => Object.fromEntries(header.map((key, index) => [key, row[index] || ''])))
}

async function fileSize(filePath) {
  const info = await stat(filePath)
  return info.size
}

async function exists(filePath) {
  try {
    await access(filePath)
    return true
  } catch {
    return false
  }
}

function resolveArtifactPath(value, summaryPath) {
  if (!value) return ''
  return path.isAbsolute(value) ? value : path.resolve(path.dirname(summaryPath), value)
}

function readPngInfo(buffer) {
  const signature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]
  if (buffer.length < 33 || !signature.every((byte, index) => buffer[index] === byte)) {
    throw new Error('不是有效 PNG 文件')
  }
  let hasTrns = false
  let offset = 8
  while (offset + 12 <= buffer.length) {
    const length = buffer.readUInt32BE(offset)
    const type = buffer.toString('ascii', offset + 4, offset + 8)
    if (type === 'tRNS') hasTrns = true
    offset += 12 + length
  }
  const width = buffer.readUInt32BE(16)
  const height = buffer.readUInt32BE(20)
  const bitDepth = buffer[24]
  const colorType = buffer[25]
  return {
    width,
    height,
    bitDepth,
    colorType,
    hasAlpha: colorType === 4 || colorType === 6 || hasTrns,
  }
}

function parseResolution(value) {
  const match = String(value || '').match(/(\d+)\D+(\d+)/)
  if (!match) return null
  return { width: Number(match[1]), height: Number(match[2]) }
}

function parseKeyValueLog(text) {
  const out = {}
  for (const line of text.split(/\r?\n/)) {
    const index = line.indexOf('=')
    if (index <= 0) continue
    out[line.slice(0, index)] = line.slice(index + 1)
  }
  return out
}

function basicXmlCheck(svgText) {
  const failures = []
  if (!/<svg[\s>]/i.test(svgText)) failures.push('缺少 <svg> 根元素')
  if (!/<\/svg>/i.test(svgText)) failures.push('缺少 </svg> 结束标签')
  if (/&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)/.test(svgText)) {
    failures.push('存在未转义的 & 字符')
  }

  const stack = []
  const tagPattern = /<[^>]+>/g
  let match
  while ((match = tagPattern.exec(svgText)) !== null) {
    const tag = match[0]
    if (/^<\?/.test(tag) || /^<!/.test(tag)) continue
    const closing = /^<\//.test(tag)
    const selfClosing = /\/>$/.test(tag)
    const nameMatch = tag.match(/^<\/?\s*([A-Za-z_][\w:.-]*)/)
    if (!nameMatch) continue
    const name = nameMatch[1]
    if (closing) {
      const previous = stack.pop()
      if (previous !== name) {
        failures.push(`标签闭合顺序异常: 期望 </${previous || 'none'}>，实际 </${name}>`)
        break
      }
    } else if (!selfClosing) {
      stack.push(name)
    }
  }
  if (stack.length > 0) failures.push(`存在未闭合标签: ${stack.slice(-3).join(', ')}`)
  return failures
}

function toNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

async function verifyArtifacts({
  summaryPath,
  expectedRows,
  options,
  suite,
}) {
  const failures = []
  const warnings = []
  const summaryText = await readFile(summaryPath, 'utf8')
  const rows = csvObjects(summaryText)
  const allowedStatuses = new Set(String(options['allow-status'] || 'success,degraded').split(',').map((item) => item.trim()).filter(Boolean))
  const maxFailures = Number(options['max-failures'] ?? 0)
  const maxE2eMs = Number(options['max-e2e-ms'] ?? 90000)
  const maxVectorMs = Number(options['max-vector-ms'] ?? 10000)
  const resolution = parseResolution(options.resolution || '1280 x 720')
  const noVectorize = Boolean(options['no-vectorize'])
  const strictSvgGroups = Boolean(options['strict-svg-groups'])
  const allowResolutionMismatch = Boolean(options['allow-resolution-mismatch'])

  const fail = (message) => failures.push(message)
  const warn = (message) => warnings.push(message)

  if (rows.length !== expectedRows.length) {
    fail(`汇总 CSV 行数应为 ${expectedRows.length}，实际为 ${rows.length}: ${summaryPath}`)
  }

  const failedRows = rows.filter((row) => row.status === 'failed' || row.error)
  if (failedRows.length > maxFailures) {
    fail(`失败条数 ${failedRows.length} 超过阈值 ${maxFailures}`)
  }

  rows.forEach((row, index) => {
    if (!allowedStatuses.has(row.status) && row.status !== 'failed') {
      fail(`[${index + 1}] 状态 ${row.status || '(空)'} 不在允许列表: ${Array.from(allowedStatuses).join(',')}`)
    }
    const expected = expectedRows[index]
    if (expected && row.text !== expected.text) {
      fail(`[${index + 1}] summary text 不匹配: "${row.text}" != "${expected.text}"`)
    }
  })

  for (let index = 0; index < rows.length; index += 1) {
    const row = rows[index]
    const label = `[${index + 1}] ${row.text || row.task_name || 'unknown'}`
    const taskDir = resolveArtifactPath(row.task_dir, summaryPath)
    const paths = {
      original: resolveArtifactPath(row.original_path, summaryPath),
      transparent: resolveArtifactPath(row.transparent_path, summaryPath),
      svg: resolveArtifactPath(row.result_svg_path, summaryPath),
      preview: resolveArtifactPath(row.preview_path, summaryPath),
      metadata: resolveArtifactPath(row.metadata_path, summaryPath),
      log: resolveArtifactPath(row.run_log_path, summaryPath),
      workflowApi: path.join(taskDir, 'workflows', 'workflow_api.json'),
      workflowNodes: path.join(taskDir, 'workflows', 'nodes.md'),
      modelDependencies: path.join(taskDir, 'workflows', 'model_dependencies.json'),
    }

    const required = noVectorize
      ? ['original', 'metadata', 'log', 'workflowApi', 'workflowNodes', 'modelDependencies']
      : ['original', 'transparent', 'svg', 'preview', 'metadata', 'log', 'workflowApi', 'workflowNodes', 'modelDependencies']

    for (const key of required) {
      if (!paths[key] || !(await exists(paths[key]))) {
        fail(`${label} 缺少产物: ${key} (${paths[key] || 'empty path'})`)
        continue
      }
      const size = await fileSize(paths[key])
      if (size <= 0) fail(`${label} 空文件: ${key} (${paths[key]})`)
    }

    if (await exists(paths.original)) {
      try {
        const png = readPngInfo(await readFile(paths.original))
        if (resolution && (png.width !== resolution.width || png.height !== resolution.height)) {
          const message = `${label} original.png 尺寸 ${png.width}x${png.height} 不等于 ${resolution.width}x${resolution.height}`
          allowResolutionMismatch ? warn(message) : fail(message)
        }
      } catch (error) {
        fail(`${label} original.png 校验失败: ${error.message}`)
      }
    }

    if (!noVectorize && await exists(paths.transparent)) {
      try {
        const png = readPngInfo(await readFile(paths.transparent))
        if (!png.hasAlpha) fail(`${label} transparent.png 缺少 Alpha 通道`)
        if (resolution && (png.width !== resolution.width || png.height !== resolution.height)) {
          const message = `${label} transparent.png 尺寸 ${png.width}x${png.height} 不等于 ${resolution.width}x${resolution.height}`
          allowResolutionMismatch ? warn(message) : fail(message)
        }
      } catch (error) {
        fail(`${label} transparent.png 校验失败: ${error.message}`)
      }
    }

    if (!noVectorize && await exists(paths.preview)) {
      try {
        readPngInfo(await readFile(paths.preview))
      } catch (error) {
        fail(`${label} preview.png 校验失败: ${error.message}`)
      }
    }

    if (!noVectorize && await exists(paths.svg)) {
      const svgText = await readFile(paths.svg, 'utf8')
      const xmlFailures = basicXmlCheck(svgText)
      for (const error of xmlFailures) fail(`${label} SVG XML 校验失败: ${error}`)
      if (!/viewBox=/i.test(svgText)) fail(`${label} result.svg 缺少 viewBox`)
      if (/<image[\s>]/i.test(svgText) || /data:image\/[^;]+;base64/i.test(svgText)) {
        fail(`${label} result.svg 含有位图 <image> 或 base64，不符合真矢量要求`)
      }
      if (!/<(path|polygon|polyline|rect|circle|ellipse)\b/i.test(svgText)) {
        fail(`${label} result.svg 缺少可编辑矢量图形元素`)
      }
      if (!/<g[\s>]/i.test(svgText)) {
        const message = `${label} result.svg 未发现 <g> 分组`
        strictSvgGroups ? fail(message) : warn(message)
      }
    }

    let metadata = null
    if (await exists(paths.metadata)) {
      try {
        metadata = JSON.parse(await readFile(paths.metadata, 'utf8'))
        if (!metadata.schema_version) fail(`${label} metadata.json 缺少 schema_version`)
        if (row.text && metadata.generation?.text && metadata.generation.text !== row.text) {
          fail(`${label} metadata.generation.text 不匹配`)
        }
      } catch (error) {
        fail(`${label} metadata.json 不是合法 JSON: ${error.message}`)
      }
    }

    if (await exists(paths.log)) {
      const runLog = parseKeyValueLog(await readFile(paths.log, 'utf8'))
      if (!runLog.status) fail(`${label} run.log 缺少 status`)
      const stage1 = toNumber(runLog.stage1_ms)
      const stage2 = toNumber(runLog.stage2_ms)
      if (maxE2eMs > 0 && stage1 !== null && stage2 !== null && stage1 + stage2 > maxE2eMs) {
        fail(`${label} 端到端耗时 ${stage1 + stage2}ms 超过 ${maxE2eMs}ms`)
      }
      if (!noVectorize && maxVectorMs > 0 && stage2 !== null && stage2 > maxVectorMs) {
        fail(`${label} 矢量化耗时 ${stage2}ms 超过 ${maxVectorMs}ms`)
      }
    }

    const vectorElapsed = toNumber(metadata?.stats?.elapsed_ms)
    if (!noVectorize && maxVectorMs > 0 && vectorElapsed !== null && vectorElapsed > maxVectorMs) {
      fail(`${label} metadata.stats.elapsed_ms ${vectorElapsed}ms 超过 ${maxVectorMs}ms`)
    }
  }

  return {
    suite: suite.label,
    summaryPath,
    total: rows.length,
    failedRows: failedRows.length,
    failures,
    warnings,
  }
}

async function runSuite(name, options) {
  const baseSuite = SUITES[name] || {
    label: '自定义测试集',
    minRows: 1,
    seed: 2026061101,
    timeoutMinutes: 90,
  }
  const suite = {
    ...baseSuite,
    ...(options.fixture
      ? {
          fixture: resolvePath(options.fixture),
          exactRows: undefined,
          minRows: Number(options['min-rows'] ?? 1),
        }
      : {}),
  }
  if (!suite.fixture) throw new Error(`未知测试集: ${name}`)

  const outputRoot = resolvePath(options['output-root'] || path.join('outputs', 'cli-acceptance'))
  const runDir = resolvePath(options['verify-only'])
    ? path.dirname(resolvePath(options['verify-only']))
    : path.join(outputRoot, `${name}-${formatTimestamp()}`)
  const preparedFixture = path.join(runDir, '_prepared', `${name}.txt`)
  const rows = await prepareFixture({ fixturePath: suite.fixture, preparedPath: preparedFixture, suite })

  console.log(`\n=== ${suite.label} (${name}) ===`)
  console.log(`测试集: ${suite.fixture}`)
  console.log(`规范化输入: ${preparedFixture}`)
  console.log(`条目数: ${rows.length}`)

  if (options['verify-only']) {
    return verifyArtifacts({
      summaryPath: resolvePath(options['verify-only']),
      expectedRows: rows,
      options,
      suite,
    })
  }

  const invocation = buildCliInvocation(options.cli || CLI_ENTRY)
  const seed = Number(options.seed ?? suite.seed)
  const seedStep = Number(options['seed-step'] ?? 1)
  const resolution = options.resolution || '1280 x 720'
  const vectorPreset = options['vector-preset'] || 'balanced'
  const waitSeconds = Number(options.wait ?? 30)
  const timeoutMinutes = Number(options['timeout-minutes'] ?? suite.timeoutMinutes)
  const negative = options.negative || DEFAULT_NEGATIVE

  const cliArgs = [
    ...invocation.baseArgs,
    'batch',
    '--input-file', preparedFixture,
    '--output-dir', runDir,
    '--seed', String(seed),
    '--seed-step', String(seedStep),
    '--resolution', resolution,
    '--vector-preset', vectorPreset,
    '--negative', negative,
    '--wait', String(waitSeconds),
  ]
  if (options['no-vectorize']) cliArgs.push('--no-vectorize')

  console.log(`输出目录: ${runDir}`)
  console.log(`CLI: ${invocation.command} ${cliArgs.map((arg) => JSON.stringify(arg)).join(' ')}`)

  if (options['dry-run']) {
    return {
      suite: suite.label,
      summaryPath: '',
      total: rows.length,
      failedRows: 0,
      failures: [],
      warnings: ['dry-run: 未运行 CLI，也未核验产物。'],
    }
  }

  if (!options['skip-health']) {
    await waitForHealth(invocation, waitSeconds)
  }

  const batch = await runCommand(invocation.command, cliArgs, {
    timeoutMs: timeoutMinutes * 60 * 1000,
  })
  if (batch.timedOut) {
    throw new Error(`${suite.label}运行超时，阈值 ${timeoutMinutes} 分钟`)
  }
  if (batch.code !== 0) {
    throw new Error(`${suite.label} CLI batch 退出码 ${batch.code}`)
  }

  const summaries = await findFilesByName(runDir, 'batch_summary.csv')
  if (summaries.length === 0) {
    throw new Error(`未找到 batch_summary.csv: ${runDir}`)
  }
  const summaryStats = await Promise.all(summaries.map(async (file) => ({ file, info: await stat(file) })))
  summaryStats.sort((a, b) => b.info.mtimeMs - a.info.mtimeMs)

  return verifyArtifacts({
    summaryPath: summaryStats[0].file,
    expectedRows: rows,
    options,
    suite,
  })
}

function suiteNames(value) {
  if (!value || value === 'small') return ['small']
  if (value === 'all') return ['small', 'large']
  return String(value).split(',').map((name) => name.trim()).filter(Boolean)
}

async function main() {
  const options = parseArgs(process.argv.slice(2))
  if (options.help || options.h) {
    printUsage()
    return
  }

  const reports = []
  for (const name of suiteNames(options.suite)) {
    if (!SUITES[name] && !options.fixture) throw new Error(`未知 suite: ${name}`)
    reports.push(await runSuite(name, options))
  }

  let failureCount = 0
  let warningCount = 0
  console.log('\n=== 验收结果 ===')
  for (const report of reports) {
    failureCount += report.failures.length
    warningCount += report.warnings.length
    console.log(`${report.failures.length === 0 ? 'PASS' : 'FAIL'} ${report.suite}: ${report.total} 条，失败行 ${report.failedRows}，硬失败 ${report.failures.length}，警告 ${report.warnings.length}`)
    if (report.summaryPath) console.log(`  summary: ${report.summaryPath}`)
    for (const warning of report.warnings.slice(0, 20)) console.log(`  WARN ${warning}`)
    for (const failure of report.failures.slice(0, 50)) console.log(`  FAIL ${failure}`)
    if (report.warnings.length > 20) console.log(`  ... 还有 ${report.warnings.length - 20} 条警告`)
    if (report.failures.length > 50) console.log(`  ... 还有 ${report.failures.length - 50} 条失败`)
  }

  if (failureCount > 0) {
    throw new Error(`验收未通过: ${failureCount} 个硬失败，${warningCount} 个警告`)
  }
}

main().catch((error) => {
  console.error(`\n错误: ${error.message}`)
  process.exit(1)
})
