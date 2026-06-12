/**
 * Desktop-compatible output helpers for CLI commands.
 *
 * The desktop app writes stable task artifacts:
 * original.png, transparent.png, result.svg, preview.png, metadata.json,
 * run.log, workflows/* and batch_summary.csv. Keeping the CLI layout aligned
 * makes large batch runs easy to inspect in either surface.
 */

import fsSync from 'node:fs'
import { appendFile, mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

export const VECTOR_PRESETS = {
  clean: {
    preset: 'clean',
    color_precision: 2,
    filter_speckle: 48,
    corner_threshold: 120,
    length_threshold: 30,
    layer_difference: 38,
    scale: 2,
  },
  balanced: {
    preset: 'balanced',
    color_precision: 6,
    filter_speckle: 18,
    corner_threshold: 70,
    length_threshold: 12,
    layer_difference: 20,
    scale: 2,
  },
  detailed: {
    preset: 'detailed',
    color_precision: 6,
    filter_speckle: 2,
    corner_threshold: 30,
    length_threshold: 3,
    layer_difference: 4,
    scale: 3,
  },
  ultra: {
    preset: 'ultra',
    color_precision: 8,
    filter_speckle: 1,
    corner_threshold: 20,
    length_threshold: 2,
    layer_difference: 2,
    scale: 3,
  },
}

export function resolveOutputRoot(outputRoot = '') {
  return path.resolve(outputRoot || process.env.ART_TEXT_OUTPUT_ROOT || 'outputs')
}

export function padTaskIndex(index) {
  const safeIndex = Number.isFinite(Number(index)) && Number(index) > 0 ? Number(index) : 1
  return String(Math.trunc(safeIndex)).padStart(3, '0')
}

function transliterateChinese(text) {
  const map = {
    爱: 'ai', 情: 'qing', 海: 'hai', 梨: 'li', 园: 'yuan', 醉: 'zui', 梦: 'meng', 七: 'qi', 里: 'li', 香: 'xiang',
    红: 'hong', 豆: 'dou', 抹: 'mo', 茶: 'cha', 青: 'qing', 山: 'shan', 集: 'ji', 夏: 'xia', 日: 'ri', 冰: 'bing', 饮: 'yin',
    花: 'hua', 朝: 'chao', 节: 'jie', 咖: 'ka', 啡: 'fei', 字: 'zi', 艺: 'yi', 术: 'shu', 文: 'wen', 本: 'ben', 图: 'tu'
  }
  return Array.from(String(text || '')).map((char) => {
    if (map[char]) return map[char]
    return /[\u3400-\u9fff]/u.test(char) ? `u${char.codePointAt(0).toString(16)}` : char
  }).join('-')
}

export function safeTaskSlug(text) {
  const transliterated = transliterateChinese(text || 'art-text')
  const slug = transliterated
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase()
  return (slug || 'art-text').slice(0, 48)
}

export function buildTaskDirectoryName({ startedAt = null, mode = 'single', index = 1, text = 'art-text', seed = 0 } = {}) {
  const taskId = mode === 'batch' ? `${formatTaskStartedAt(startedAt)}_${padTaskIndex(index)}` : formatTaskStartedAt(startedAt)
  return `task_${taskId}_${safeTaskSlug(text)}_seed-${seed || 0}`
}

export function formatTaskStartedAt(startedAt) {
  const date = startedAt ? new Date(startedAt) : new Date()
  const validDate = Number.isNaN(date.getTime()) ? new Date() : date
  const pad = (value, width = 2) => String(value).padStart(width, '0')
  return [
    validDate.getFullYear(),
    pad(validDate.getMonth() + 1),
    pad(validDate.getDate()),
    '_',
    pad(validDate.getHours()),
    pad(validDate.getMinutes()),
    pad(validDate.getSeconds()),
    '_',
    pad(validDate.getMilliseconds(), 3),
  ].join('')
}

export async function prepareOutputTask({
  outputRoot = '',
  mode = 'single',
  index = 1,
  text = 'art-text',
  seed = 0,
  startedAt = null,
  summaryDir = null,
} = {}) {
  const root = resolveOutputRoot(outputRoot)
  await mkdir(root, { recursive: true })

  const baseName = buildTaskDirectoryName({ startedAt, mode, index, text, seed })
  let taskName = baseName
  let taskDir = path.join(root, taskName)
  let counter = 2

  while (fsSync.existsSync(taskDir)) {
    taskName = `${baseName}_${counter}`
    taskDir = path.join(root, taskName)
    counter += 1
  }

  await mkdir(taskDir, { recursive: true })
  return buildTaskInfo({ outputRoot: root, taskDir, taskName, mode, index, seed, summaryDir })
}

export function buildTaskInfo({ outputRoot, taskDir, taskName, mode, index, seed, summaryDir }) {
  const summaryRoot = summaryDir || (mode === 'batch-batch' ? taskDir : outputRoot)
  const paths = {
    original: path.join(taskDir, 'original.png'),
    transparent: path.join(taskDir, 'transparent.png'),
    svg: path.join(taskDir, 'result.svg'),
    preview: path.join(taskDir, 'preview.png'),
    metadata: path.join(taskDir, 'metadata.json'),
    log: path.join(taskDir, 'run.log'),
    workflows: path.join(taskDir, 'workflows'),
    workflowApi: path.join(taskDir, 'workflows', 'workflow_api.json'),
    workflowNodes: path.join(taskDir, 'workflows', 'nodes.md'),
    modelDependencies: path.join(taskDir, 'workflows', 'model_dependencies.json'),
    summary: path.join(summaryRoot, 'batch_summary.csv'),
    summaryDir: summaryRoot,
  }
  return { outputRoot, taskDir, taskName, mode, index, seed, paths }
}

function parseDataUrl(dataUrl) {
  const match = /^data:(.+?)(;base64)?,(.*)$/s.exec(dataUrl)
  if (!match) return null
  const isBase64 = !!match[2]
  const data = match[3]
  return isBase64 ? Buffer.from(data, 'base64') : Buffer.from(decodeURIComponent(data), 'utf8')
}

function bufferForArtifact(data, key = '', isText = false) {
  if (data === undefined || data === null || data === '') return null
  if (Buffer.isBuffer(data)) return data
  if (typeof data === 'object') return Buffer.from(JSON.stringify(data, null, 2), 'utf8')

  const str = String(data)
  if (isText) return Buffer.from(str, 'utf8')

  const dataUrlBuffer = str.startsWith('data:') ? parseDataUrl(str) : null
  if (dataUrlBuffer) return dataUrlBuffer

  const imageKeys = ['original', 'transparent', 'preview', 'png']
  const lowerKey = String(key).toLowerCase()
  if (imageKeys.some((name) => lowerKey.includes(name))) {
    return Buffer.from(str.replace(/^data:[^;]+;base64,/, ''), 'base64')
  }

  return Buffer.from(str, 'utf8')
}

async function writeArtifactFile(filePath, data, key = '', isText = false) {
  const buffer = bufferForArtifact(data, key, isText)
  if (!buffer) return null
  await mkdir(path.dirname(filePath), { recursive: true })
  await writeFile(filePath, buffer)
  return filePath
}

function csvEscape(value) {
  const text = value === undefined || value === null ? '' : String(value)
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`
  return text
}

function extractQualityMetrics(metadata = {}) {
  const generationMs = metadata?.generation?.duration_ms
  const vectorMs = metadata?.stats?.elapsed_ms
  const normalizedGenerationMs = generationMs === undefined || generationMs === null ? '' : generationMs
  const normalizedVectorMs = vectorMs === undefined || vectorMs === null ? '' : vectorMs
  const pngTransparency = metadata?.preprocess?.png_transparency
  const svgFidelity = metadata?.quality?.svg_fidelity
  return {
    generation_ms: normalizedGenerationMs,
    vector_ms: normalizedVectorMs,
    png_transparency: pngTransparency === undefined || pngTransparency === null ? '' : pngTransparency,
    svg_fidelity: svgFidelity === undefined || svgFidelity === null ? '' : svgFidelity,
  }
}

function appendQualityMetricsToRunLog(runLog = '', metadata = {}) {
  if (!runLog) return runLog
  const metrics = extractQualityMetrics(metadata)
  const upsertMetric = (text, key, value) => {
    const line = `${key}=${value}`
    const pattern = new RegExp(`(^|\\n)${key}=.*(?=\\n|$)`)
    if (pattern.test(text)) {
      return text.replace(pattern, (match, prefix) => `${prefix}${line}`)
    }
    return `${text}\n${line}`
  }
  return [
    ['generation_ms', metrics.generation_ms],
    ['vector_ms', metrics.vector_ms],
    ['png_transparency', metrics.png_transparency],
    ['svg_fidelity', metrics.svg_fidelity],
  ].reduce((text, [key, value]) => upsertMetric(text, key, value), runLog)
}

export async function appendBatchSummaryCsv(summaryPath, row = {}) {
  const columns = [
    'task_id',
    'task_name',
    'mode',
    'status',
    'text',
    'prompt',
    'seed',
    'resolution',
    'task_dir',
    'run_log_path',
    'generation_ms',
    'vector_ms',
    'png_transparency',
    'svg_fidelity',
    'error',
  ]
  await mkdir(path.dirname(summaryPath), { recursive: true })
  const exists = fsSync.existsSync(summaryPath)
  const line = columns.map((key) => csvEscape(row[key])).join(',')
  const content = `${exists ? '' : `${columns.join(',')}\n`}${line}\n`
  await appendFile(summaryPath, content, 'utf8')
}

function buildWorkflowArtifacts({ metadata = {}, taskName = '', seed = 0, mode = 'single', workflowApi = null, modelDependencies = null }) {
  if (workflowApi || modelDependencies) {
    return {
      workflowApi: workflowApi || {
        task_name: taskName,
        mode,
        seed,
        workflow: metadata?.generation?.workflow || metadata?.workflow || metadata?.engine || 'local-runtime',
        prompt: metadata?.generation?.prompt || metadata?.prompt || '',
        text: metadata?.generation?.text || '',
        resolution: metadata?.generation?.resolution || '',
        captured_at: new Date().toISOString(),
      },
      workflowNodes: `# 工作流节点说明\n\n- 任务：${taskName}\n- 模式：${mode}\n- 文生图：生成位图 original.png\n- 矢量化：生成 transparent.png、result.svg、preview.png\n\n> 当前文件为 CLI 运行快照；后续可由 txt2img-api 返回完整 ComfyUI 节点清单。\n`,
      modelDependencies: modelDependencies || {
        engine: metadata?.engine || metadata?.generation?.engine || 'unknown',
        workflow: metadata?.workflow || metadata?.generation?.workflow || null,
        style: metadata?.style || metadata?.generation?.style || null,
        note: '运行时模型依赖快照；请结合交付文档中的模型清单核验。',
      },
    }
  }

  return {
    workflowApi: {
      task_name: taskName,
      mode,
      seed,
      workflow: metadata?.generation?.workflow || metadata?.workflow || metadata?.engine || 'local-runtime',
      prompt: metadata?.generation?.prompt || metadata?.prompt || '',
      text: metadata?.generation?.text || '',
      resolution: metadata?.generation?.resolution || '',
      captured_at: new Date().toISOString(),
    },
    workflowNodes: `# 工作流节点说明\n\n- 任务：${taskName}\n- 模式：${mode}\n- 文生图：生成位图 original.png\n- 矢量化：生成 transparent.png、result.svg、preview.png\n\n> 当前文件为 CLI 运行快照；后续可由 txt2img-api 返回完整 ComfyUI 节点清单。\n`,
    modelDependencies: {
      engine: metadata?.engine || metadata?.generation?.engine || 'unknown',
      workflow: metadata?.workflow || metadata?.generation?.workflow || null,
      style: metadata?.style || metadata?.generation?.style || null,
      note: '运行时模型依赖快照；请结合交付文档中的模型清单核验。',
    },
  }
}

export async function writeTaskArtifacts({
  outputRoot,
  taskDir,
  taskName,
  paths = {},
  artifacts = {},
  metadata = {},
  runLog = '',
  usesTxt2Img = false,
  workflowArtifacts = null,
  summaryRow = null,
} = {}) {
  if (!taskDir || typeof taskDir !== 'string') {
    throw new Error('taskDir is required')
  }

  const root = path.resolve(outputRoot || path.dirname(taskDir))
  const resolvedTaskDir = path.resolve(taskDir)
  await mkdir(resolvedTaskDir, { recursive: true })

  const targetPaths = {
    original: paths.original || path.join(resolvedTaskDir, 'original.png'),
    transparent: paths.transparent || path.join(resolvedTaskDir, 'transparent.png'),
    svg: paths.svg || path.join(resolvedTaskDir, 'result.svg'),
    preview: paths.preview || path.join(resolvedTaskDir, 'preview.png'),
    metadata: paths.metadata || path.join(resolvedTaskDir, 'metadata.json'),
    log: paths.log || path.join(resolvedTaskDir, 'run.log'),
    workflows: paths.workflows || path.join(resolvedTaskDir, 'workflows'),
    workflowApi: paths.workflowApi || path.join(resolvedTaskDir, 'workflows', 'workflow_api.json'),
    workflowNodes: paths.workflowNodes || path.join(resolvedTaskDir, 'workflows', 'nodes.md'),
    modelDependencies: paths.modelDependencies || path.join(resolvedTaskDir, 'workflows', 'model_dependencies.json'),
    summary: paths.summary || path.join(root, 'batch_summary.csv'),
    summaryDir: paths.summaryDir || root,
  }

  const savedFiles = []
  for (const [key, filePath] of [
    ['original', targetPaths.original],
    ['transparent', targetPaths.transparent],
    ['svg', targetPaths.svg],
    ['preview', targetPaths.preview],
  ]) {
    const saved = await writeArtifactFile(filePath, artifacts[key], key, key === 'svg')
    if (saved) savedFiles.push(saved)
  }

  const shouldWriteMetadata = metadata !== undefined && metadata !== null
  const metadataPayload = shouldWriteMetadata
    ? {
        ...(metadata || {}),
        schema_version: metadata?.schema_version || 1,
        task_name: metadata?.task_name || taskName || path.basename(resolvedTaskDir),
        output_dir: resolvedTaskDir,
        paths: {
          original: 'original.png',
          transparent: 'transparent.png',
          svg: 'result.svg',
          preview: 'preview.png',
          metadata: 'metadata.json',
          log: 'run.log',
        },
        workflow_paths: usesTxt2Img
          ? {
              workflow_api: 'workflows/workflow_api.json',
              nodes: 'workflows/nodes.md',
              model_dependencies: 'workflows/model_dependencies.json',
            }
          : null,
      }
    : null

  if (shouldWriteMetadata) {
    const saved = await writeArtifactFile(targetPaths.metadata, metadataPayload, 'metadata', true)
    if (saved) savedFiles.push(saved)
  }

  if (runLog) {
    const saved = await writeArtifactFile(targetPaths.log, appendQualityMetricsToRunLog(runLog, metadataPayload || {}), 'log', true)
    if (saved) savedFiles.push(saved)
  }

  if (usesTxt2Img) {
    const wfApi = workflowArtifacts?.workflowApi || workflowArtifacts?.workflow_api
    const wfDeps = workflowArtifacts?.modelDependencies || workflowArtifacts?.model_dependencies
    const hasRealData = wfApi && typeof wfApi === 'object' && Object.keys(wfApi).length > 2
    const fallbackWorkflow = buildWorkflowArtifacts({
      metadata: metadataPayload || {},
      taskName,
      seed: metadataPayload?.generation?.seed,
      mode: metadataPayload?.mode,
      workflowApi: wfApi,
      modelDependencies: wfDeps,
    })
    const workflow = hasRealData ? { ...fallbackWorkflow, ...workflowArtifacts } : fallbackWorkflow

    const workflowApiSaved = await writeArtifactFile(targetPaths.workflowApi, workflow.workflowApi || workflow.workflow_api || {}, 'workflowApi', true)
    const workflowNodesSaved = await writeArtifactFile(targetPaths.workflowNodes, workflow.workflowNodes || workflow.nodes || '', 'workflowNodes', true)
    const modelDepsSaved = await writeArtifactFile(targetPaths.modelDependencies, workflow.modelDependencies || workflow.model_dependencies || {}, 'modelDependencies', true)
    savedFiles.push(...[workflowApiSaved, workflowNodesSaved, modelDepsSaved].filter(Boolean))
  }

  if (summaryRow) {
    const summaryTarget = summaryRow.summary_path || targetPaths.summary
    if (summaryTarget) {
      await appendBatchSummaryCsv(summaryTarget, {
        ...extractQualityMetrics(metadataPayload || {}),
        ...summaryRow,
        task_name: summaryRow.task_name || taskName || path.basename(resolvedTaskDir),
        task_dir: summaryRow.task_dir || resolvedTaskDir,
        run_log_path: summaryRow.run_log_path || targetPaths.log,
      })
    }
  }

  return { outputRoot: root, taskDir: resolvedTaskDir, taskName: taskName || path.basename(resolvedTaskDir), paths: targetPaths, filePaths: savedFiles }
}

export function createCliTask({ title = '', mode = 'single', startedAt = new Date().toISOString() } = {}) {
  return {
    id: Date.now(),
    title,
    startedAt,
    time: new Date(startedAt).toLocaleTimeString('zh-CN', { hour12: false }),
    status: 'running',
    mode,
  }
}

export function resolveStatus(metadata) {
  if (!metadata) return 'success'
  if (metadata.engine === 'local-studio') return 'stub'
  if (metadata.fallback_tier > 0) return 'degraded'
  return 'success'
}

export function buildRunLog({
  task,
  taskInfo,
  modeName,
  text = '',
  prompt = '',
  seed = 0,
  stage1Duration = 0,
  stage2Duration = 0,
  status = 'success',
  error = '',
  usesTxt2Img = false,
  engine = '',
  metadata = {},
} = {}) {
  const paths = taskInfo?.paths || {}
  const metrics = extractQualityMetrics(metadata)
  return [
    `task_id=${task?.id || ''}`,
    `task_name=${taskInfo?.taskName || ''}`,
    `mode=${modeName}`,
    `text=${text}`,
    `prompt=${prompt}`,
    `seed=${seed}`,
    `generation_ms=${stage1Duration}`,
    `vector_ms=${stage2Duration}`,
    `uses_txt2img=${usesTxt2Img}`,
    `engine=${engine}`,
    `png_transparency=${metrics.png_transparency}`,
    `svg_fidelity=${metrics.svg_fidelity}`,
    `task_dir=${taskInfo?.taskDir || ''}`,
    `original_path=${paths.original || ''}`,
    `transparent_path=${paths.transparent || ''}`,
    `result_svg_path=${paths.svg || ''}`,
    `preview_path=${paths.preview || ''}`,
    `metadata_path=${paths.metadata || ''}`,
    `run_log_path=${paths.log || ''}`,
    `status=${status}`,
    error ? `error=${error}` : '',
  ].filter(Boolean).join('\n')
}

export function augmentMetadata(metadata, { task, taskInfo, modeName, text = '', prompt = '', seed = 0, usesTxt2Img = false } = {}) {
  return {
    ...(metadata || {}),
    schema_version: metadata?.schema_version || 1,
    task_id: String(task?.id || ''),
    task_name: taskInfo?.taskName || '',
    mode: modeName,
    output_dir: taskInfo?.taskDir || '',
    generation: {
      ...(metadata?.generation || {}),
      text: metadata?.generation?.text || text,
      prompt: metadata?.generation?.prompt || prompt,
      seed: metadata?.generation?.seed ?? seed,
    },
    paths: taskInfo?.paths
      ? {
          original: taskInfo.paths.original,
          transparent: taskInfo.paths.transparent,
          svg: taskInfo.paths.svg,
          preview: taskInfo.paths.preview,
          metadata: taskInfo.paths.metadata,
          log: taskInfo.paths.log,
        }
      : {
          original: 'original.png',
          transparent: 'transparent.png',
          svg: 'result.svg',
          preview: 'preview.png',
          metadata: 'metadata.json',
          log: 'run.log',
        },
    workflow_paths: usesTxt2Img
      ? {
          workflow_api: 'workflows/workflow_api.json',
          nodes: 'workflows/nodes.md',
          model_dependencies: 'workflows/model_dependencies.json',
        }
      : null,
  }
}

export function buildSummaryRow({
  task,
  taskInfo,
  modeName,
  status = 'success',
  text = '',
  prompt = '',
  seed = 0,
  resolution = '',
  error = '',
  metadata = {},
  generationMs = null,
  vectorMs = null,
} = {}) {
  const metrics = extractQualityMetrics({
    ...(metadata || {}),
    generation: {
      ...(metadata?.generation || {}),
      ...(generationMs !== null && generationMs !== undefined ? { duration_ms: generationMs } : {}),
    },
    stats: {
      ...(metadata?.stats || {}),
      ...(vectorMs !== null && vectorMs !== undefined ? { elapsed_ms: vectorMs } : {}),
    },
  })
  return {
    task_id: String(task?.id || ''),
    task_name: taskInfo?.taskName || '',
    mode: modeName,
    status,
    text,
    prompt,
    seed,
    resolution,
    task_dir: taskInfo?.taskDir || '',
    run_log_path: taskInfo?.paths?.log || '',
    generation_ms: metrics.generation_ms,
    vector_ms: metrics.vector_ms,
    png_transparency: metrics.png_transparency,
    svg_fidelity: metrics.svg_fidelity,
    error,
  }
}
