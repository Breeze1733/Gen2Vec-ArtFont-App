/**
 * batch 命令 - 批量生成艺术字（逐条处理，容错执行）
 *
 * 输入格式：
 *   TXT:  每行一条：文本 | 风格提示词 | 负面提示词 | seed
 *   CSV:  text,prompt,negative,seed,resolution
 *   JSON: [{ "text": "...", "prompt": "..." }]
 */

import { generateArtBitmap, vectorizeImage } from '../api.mjs'
import {
  augmentMetadata,
  buildRunLog,
  buildSummaryRow,
  createCliTask,
  prepareOutputTask,
  resolveStatus,
  writeTaskArtifacts,
} from '../utils/output.mjs'
import { readFile } from 'node:fs/promises'

async function readStdin() {
  const chunks = []
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.from(chunk))
  }
  return Buffer.concat(chunks).toString('utf8')
}

function splitDelimitedLine(line, delimiter = ',') {
  const values = []
  let current = ''
  let quoted = false

  for (let i = 0; i < line.length; i++) {
    const char = line[i]
    const next = line[i + 1]
    if (char === '"' && quoted && next === '"') {
      current += '"'
      i += 1
    } else if (char === '"') {
      quoted = !quoted
    } else if (char === delimiter && !quoted) {
      values.push(current.trim())
      current = ''
    } else {
      current += char
    }
  }

  values.push(current.trim())
  return values
}

function normalizeBatchItem(item, index = 0) {
  if (typeof item === 'string') {
    return { text: item.trim(), prompt: '', negative: '', seed: undefined, resolution: undefined }
  }

  const raw = item || {}
  return {
    text: String(raw.text ?? raw.title ?? raw.word ?? raw.content ?? '').trim(),
    prompt: String(raw.prompt ?? raw.style ?? raw.description ?? '').trim(),
    negative: String(raw.negative ?? raw.negative_prompt ?? '').trim(),
    seed: raw.seed === undefined || raw.seed === '' ? undefined : Number(raw.seed),
    resolution: raw.resolution ? String(raw.resolution).trim() : undefined,
    index: raw.index ?? index + 1,
  }
}

function parseJsonInput(content) {
  const parsed = JSON.parse(content)
  const rows = Array.isArray(parsed) ? parsed : (Array.isArray(parsed.items) ? parsed.items : [])
  return rows.map(normalizeBatchItem).filter((item) => item.text || item.prompt)
}

function parseTextInput(content) {
  const lines = content.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  if (lines.length === 0) return []

  const first = lines[0].toLowerCase()
  const hasHeader = /\btext\b/.test(first) && /\bprompt\b/.test(first)
  const rows = hasHeader ? lines.slice(1) : lines
  const headerDelimiter = lines[0].includes('|') ? '|' : (lines[0].includes('\t') ? '\t' : ',')
  const headers = hasHeader ? splitDelimitedLine(lines[0], headerDelimiter).map((name) => name.trim().toLowerCase()) : []

  return rows.map((line, index) => {
    const delimiter = line.includes('|') ? '|' : (line.includes('\t') ? '\t' : ',')
    const parts = splitDelimitedLine(line, delimiter)

    if (headers.length > 0) {
      const record = {}
      headers.forEach((key, i) => {
        record[key] = parts[i] || ''
      })
      return normalizeBatchItem(record, index)
    }

    return normalizeBatchItem({
      text: parts[0] || '',
      prompt: parts[1] || '',
      negative: parts[2] || '',
      seed: parts[3] || undefined,
      resolution: parts[4] || undefined,
    }, index)
  }).filter((item) => item.text || item.prompt)
}

async function readBatchContent({ input = '', inputFile = '' } = {}) {
  if (inputFile) return readFile(inputFile, 'utf8')
  if (input === '-') return readStdin()
  if (input && input.startsWith('@')) return readFile(input.slice(1), 'utf8')
  return input || ''
}

async function parseBatchInput(options) {
  const content = (await readBatchContent(options)).trim()
  if (!content) return []
  if (content.startsWith('[') || content.startsWith('{')) return parseJsonInput(content)
  return parseTextInput(content)
}

async function vectorizeWithPathFallback(payload, fallbackImageBase64) {
  try {
    return await vectorizeImage(payload)
  } catch (pathErr) {
    if (!fallbackImageBase64) throw pathErr
    console.warn(`  路径读取失败，回退 base64: ${pathErr.message}`)
    return vectorizeImage({
      ...payload,
      imagePath: undefined,
      generatedImage: undefined,
      imageBase64: fallbackImageBase64,
    })
  }
}

/**
 * 运行批量生成
 * @param {Object} args
 * @param {string} [args.input] - 批量输入（每行一条）或 @file / -
 * @param {string} [args.inputFile] - 批量输入文件
 * @param {string} [args.negative] - 全局负面提示词
 * @param {string} [args.resolution] - 分辨率
 * @param {number} [args.seed] - 全局随机种子
 * @param {number} [args.seedStep] - 每条 seed 递增步长（默认 0，和 desktop 对齐）
 * @param {string} [args.vectorPreset] - 矢量化预设
 * @param {Object} [args.vector] - 矢量化参数
 * @param {boolean} [args.vectorize] - 是否同时矢量化（默认 true）
 * @param {string} [args.outputDir] - 输出目录
 * @returns {Promise<{count: number, succeeded: number, failed: number, results: Array}>}
 */
export async function run(args) {
  const {
    input,
    inputFile,
    negative = '',
    resolution = '1024 x 1024',
    seed: baseSeed = 0,
    seedStep = 0,
    vectorPreset,
    vector = {},
    vectorize: doVectorize = true,
    outputDir = 'outputs',
  } = args

  console.log('正在解析批量输入...\n')
  const items = await parseBatchInput({ input, inputFile })

  if (items.length === 0) {
    console.error('错误: 未找到有效的输入条目')
    process.exit(1)
  }

  const startedAt = new Date().toISOString()
  const task = createCliTask({ title: '批量任务', mode: 'batch', startedAt })
  const batchTaskInfo = await prepareOutputTask({ mode: 'batch-batch', index: 0, seed: baseSeed, startedAt, outputRoot: outputDir })
  const batchSummaryDir = batchTaskInfo.taskDir
  const summaryPath = batchTaskInfo.paths.summary

  console.log(`共 ${items.length} 条待处理`)
  console.log(`汇总目录: ${batchSummaryDir}`)
  console.log(`汇总 CSV: ${summaryPath}\n`)

  const results = []
  let succeeded = 0
  let failed = 0

  for (let i = 0; i < items.length; i++) {
    const item = items[i]
    const text = item.text || ''
    const prompt = item.prompt || ''
    const itemNegative = item.negative || negative
    const itemResolution = item.resolution || resolution
    const seed = item.seed ?? (Number(baseSeed) + i * Number(seedStep || 0))
    const itemTaskInfo = await prepareOutputTask({
      mode: 'batch',
      index: i + 1,
      seed,
      startedAt,
      outputRoot: outputDir,
      summaryDir: batchSummaryDir,
    })

    const result = {
      index: i + 1,
      text,
      prompt,
      seed,
      status: 'running',
      taskDir: itemTaskInfo.taskDir,
      pngPath: itemTaskInfo.paths.original,
      svgPath: doVectorize ? itemTaskInfo.paths.svg : '',
      metadata: null,
      error: '',
    }

    console.log(`[${i + 1}/${items.length}] 正在处理: "${text || prompt}"`)
    let stage1Duration = 0
    let stage2Duration = 0
    let genResult = null
    let workflowArtifacts = null

    try {
      console.log('  → 生成位图...')
      const t1 = Date.now()
      genResult = await generateArtBitmap({
        text,
        prompt,
        negative: itemNegative,
        resolution: itemResolution,
        seed,
        format: 'PNG',
      })
      stage1Duration = Date.now() - t1
      workflowArtifacts = {
        workflowApi: genResult.workflow_api || null,
        modelDependencies: genResult.model_dependencies || null,
      }

      await writeTaskArtifacts({
        outputRoot: itemTaskInfo.outputRoot,
        taskDir: itemTaskInfo.taskDir,
        taskName: itemTaskInfo.taskName,
        paths: itemTaskInfo.paths,
        artifacts: { original: genResult.png },
        metadata: null,
        runLog: buildRunLog({
          task,
          taskInfo: itemTaskInfo,
          modeName: 'batch',
          text,
          prompt,
          seed,
          stage1Duration,
          status: doVectorize ? 'vectorizing' : 'generated',
          usesTxt2Img: true,
          engine: genResult.metadata?.engine || '',
        }),
        usesTxt2Img: true,
        workflowArtifacts,
      })
      console.log(`  ✓ original: ${itemTaskInfo.paths.original}`)

      let metadata
      let batchStatus = resolveStatus(genResult.metadata)
      if (doVectorize) {
        console.log('  → 矢量化...')
        const vectorConfig = { preset: vectorPreset || vector.preset || 'balanced', ...vector }
        const t2 = Date.now()
        const vecResult = await vectorizeWithPathFallback({
          sourceType: 'generated',
          text,
          prompt,
          negative: itemNegative,
          resolution: itemResolution,
          format: 'PNG + SVG',
          seed,
          generatedImage: { file_path: itemTaskInfo.paths.original },
          imageName: genResult.image_name || `${text || `batch-${i + 1}`}-orig.png`,
          vector: vectorConfig,
          timeoutMs: 120000,
        }, genResult.png)
        stage2Duration = Date.now() - t2

        if (vecResult.metadata) {
          vecResult.metadata.generation = vecResult.metadata.generation || {}
          vecResult.metadata.generation.duration_ms = stage1Duration
        }

        metadata = augmentMetadata(vecResult.metadata, { task, taskInfo: itemTaskInfo, modeName: 'batch', text, prompt, seed, usesTxt2Img: true })
        await writeTaskArtifacts({
          outputRoot: itemTaskInfo.outputRoot,
          taskDir: itemTaskInfo.taskDir,
          taskName: itemTaskInfo.taskName,
          paths: itemTaskInfo.paths,
          artifacts: {
            original: genResult.png,
            transparent: vecResult.transparent_png,
            preview: vecResult.preview_png || vecResult.png,
            svg: vecResult.svg,
          },
          metadata,
          runLog: buildRunLog({
            task,
            taskInfo: itemTaskInfo,
            modeName: 'batch',
            text,
            prompt,
            seed,
            stage1Duration,
            stage2Duration,
            status: batchStatus,
            usesTxt2Img: true,
            engine: genResult.metadata?.engine || '',
          }),
          usesTxt2Img: true,
          summaryRow: {
            ...buildSummaryRow({ task, taskInfo: itemTaskInfo, modeName: 'batch', status: batchStatus, text, prompt, seed, resolution: itemResolution }),
            summary_path: summaryPath,
          },
          workflowArtifacts,
        })
        console.log(`  ✓ SVG: ${itemTaskInfo.paths.svg}`)
      } else {
        metadata = augmentMetadata(genResult.metadata, { task, taskInfo: itemTaskInfo, modeName: 'batch', text, prompt, seed, usesTxt2Img: true })
        batchStatus = batchStatus === 'success' ? 'generated' : batchStatus
        await writeTaskArtifacts({
          outputRoot: itemTaskInfo.outputRoot,
          taskDir: itemTaskInfo.taskDir,
          taskName: itemTaskInfo.taskName,
          paths: itemTaskInfo.paths,
          artifacts: { original: genResult.png },
          metadata,
          runLog: buildRunLog({
            task,
            taskInfo: itemTaskInfo,
            modeName: 'batch',
            text,
            prompt,
            seed,
            stage1Duration,
            status: batchStatus,
            usesTxt2Img: true,
            engine: genResult.metadata?.engine || '',
          }),
          usesTxt2Img: true,
          summaryRow: {
            ...buildSummaryRow({ task, taskInfo: itemTaskInfo, modeName: 'batch', status: batchStatus, text, prompt, seed, resolution: itemResolution }),
            summary_path: summaryPath,
          },
          workflowArtifacts,
        })
      }

      result.status = 'success'
      result.metadata = metadata
      succeeded++
    } catch (err) {
      result.status = 'failed'
      result.error = err.message
      failed++
      console.error(`  ✗ 失败: ${err.message}`)

      const metadata = augmentMetadata({ error: result.error, generation: genResult?.metadata || {} }, { task, taskInfo: itemTaskInfo, modeName: 'batch', text, prompt, seed, usesTxt2Img: true })
      await writeTaskArtifacts({
        outputRoot: itemTaskInfo.outputRoot,
        taskDir: itemTaskInfo.taskDir,
        taskName: itemTaskInfo.taskName,
        paths: itemTaskInfo.paths,
        artifacts: genResult?.png ? { original: genResult.png } : {},
        metadata,
        runLog: buildRunLog({
          task,
          taskInfo: itemTaskInfo,
          modeName: 'batch',
          text,
          prompt,
          seed,
          stage1Duration,
          stage2Duration,
          status: 'failed',
          error: result.error,
          usesTxt2Img: true,
          engine: genResult?.metadata?.engine || '',
        }),
        usesTxt2Img: true,
        summaryRow: {
          ...buildSummaryRow({ task, taskInfo: itemTaskInfo, modeName: 'batch', status: 'failed', text, prompt, seed, resolution: itemResolution, error: result.error }),
          summary_path: summaryPath,
        },
        workflowArtifacts,
      })
    }

    results.push(result)
    console.log('')
  }

  console.log('═'.repeat(40))
  console.log('批量处理完成:')
  console.log(`  总数:      ${items.length}`)
  console.log(`  成功:      ${succeeded}`)
  console.log(`  失败:      ${failed}`)
  console.log(`  汇总 CSV:  ${summaryPath}`)

  const failedItems = results.filter((result) => result.status === 'failed')
  if (failedItems.length > 0) {
    console.log('\n失败条目:')
    for (const failedItem of failedItems) {
      const label = failedItem.text || `第 ${failedItem.index} 条`
      console.log(`  [${failedItem.index}] ${label}: ${failedItem.error}`)
    }
  }

  return { count: items.length, succeeded, failed, results, summaryPath, outputRoot: batchTaskInfo.outputRoot }
}
