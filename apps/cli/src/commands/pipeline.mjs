/**
 * pipeline 命令 - 完整流水线：文本 → 位图 → SVG
 */

import { generateArtBitmap, vectorizeImage } from '../api.mjs'
import { saveBase64ToFile, saveSvgToFile } from '../utils/file.mjs'
import { augmentMetadata, appendTaskIndex, buildRunLog, createCliTask, prepareOutputTask, resolveStatus, writeTaskArtifacts } from '../utils/output.mjs'

/**
 * 运行完整流水线
 * @param {Object} args
 * @param {string} args.text - 艺术字文本
 * @param {string} [args.prompt] - 风格提示词
 * @param {string} [args.negative] - 负面提示词
 * @param {string} [args.resolution] - 分辨率
 * @param {number} [args.seed] - 随机种子
 * @param {string} [args.vectorPreset] - 矢量化预设
 * @param {string} [args.outputDir] - 输出目录
 * @returns {Promise<{pngPath: string, svgPath: string, metadata: Object}>}
 */
export async function run(args) {
  const { text, prompt = '', negative = '', resolution = '1024 x 1024', seed = 0, vectorPreset, outputDir = 'outputs', output, vector = {} } = args

  console.log(`正在生成艺术字: "${text}"...`)
  console.log(`  矢量化预设: ${vectorPreset || 'balanced'}`)

  const startedAt = new Date().toISOString()
  const task = createCliTask({ title: text || '艺术字流水线', mode: 'single', startedAt })
  const taskInfo = await prepareOutputTask({ mode: 'single', index: 1, text, seed, startedAt, outputRoot: outputDir })

  const t1 = Date.now()
  const genResult = await generateArtBitmap({
    text,
    prompt,
    negative,
    resolution,
    seed,
    format: 'PNG',
  })
  const stage1Duration = Date.now() - t1
  const stage1Status = resolveStatus(genResult.metadata)
  const workflowArtifacts = {
    workflowApi: genResult.workflow_api || null,
    modelDependencies: genResult.model_dependencies || null,
  }

  await writeTaskArtifacts({
    outputRoot: taskInfo.outputRoot,
    taskDir: taskInfo.taskDir,
    taskName: taskInfo.taskName,
    paths: taskInfo.paths,
    artifacts: { original: genResult.png },
    metadata: null,
    runLog: buildRunLog({
      task,
      taskInfo,
      modeName: 'single',
      text,
      prompt,
      seed,
      stage1Duration,
      status: 'vectorizing',
      usesTxt2Img: true,
      engine: genResult.metadata?.engine || '',
    }),
    usesTxt2Img: true,
    workflowArtifacts,
  })

  const vectorConfig = { preset: vectorPreset || vector.preset || 'balanced', ...vector }
  let vecResult
  const t2 = Date.now()
  try {
    vecResult = await vectorizeImage({
      sourceType: 'generated',
      text,
      prompt,
      negative,
      resolution,
      format: 'PNG + SVG',
      seed,
      generatedImage: { file_path: taskInfo.paths.original },
      imageName: genResult.image_name || `${text || 'art'}-orig.png`,
      vector: vectorConfig,
      timeoutMs: 120000,
    })
  } catch (pathErr) {
    console.warn(`  路径读取失败，回退 base64: ${pathErr.message}`)
    vecResult = await vectorizeImage({
      sourceType: 'generated',
      text,
      prompt,
      negative,
      resolution,
      format: 'PNG + SVG',
      seed,
      imageBase64: genResult.png,
      imageName: genResult.image_name || `${text || 'art'}-orig.png`,
      vector: vectorConfig,
      timeoutMs: 120000,
    })
  }
  const stage2Duration = Date.now() - t2

  if (vecResult.metadata) {
    vecResult.metadata.generation = vecResult.metadata.generation || {}
    vecResult.metadata.generation.duration_ms = stage1Duration
  }

  const metadata = augmentMetadata(vecResult.metadata, { task, taskInfo, modeName: 'single', text, prompt, seed, usesTxt2Img: true })
  await writeTaskArtifacts({
    outputRoot: taskInfo.outputRoot,
    taskDir: taskInfo.taskDir,
    taskName: taskInfo.taskName,
    paths: taskInfo.paths,
    artifacts: {
      original: genResult.png,
      transparent: vecResult.transparent_png,
      preview: vecResult.preview_png || vecResult.png,
      svg: vecResult.svg,
    },
    metadata,
    runLog: buildRunLog({
      task,
      taskInfo,
      modeName: 'single',
      text,
      prompt,
      seed,
      stage1Duration,
      stage2Duration,
      status: stage1Status,
      usesTxt2Img: true,
      engine: genResult.metadata?.engine || '',
    }),
    usesTxt2Img: true,
    workflowArtifacts,
  })

  console.log(`✓ 任务目录: ${taskInfo.taskDir}`)
  console.log(`  original: ${taskInfo.paths.original}`)
  console.log(`  SVG: ${taskInfo.paths.svg}`)
  console.log(`  preview: ${taskInfo.paths.preview}`)

  if (output) {
    await saveSvgToFile(vecResult.svg, output)
    const pngOutput = /\.svg$/i.test(output) ? output.replace(/\.svg$/i, '.png') : `${output}.png`
    await saveBase64ToFile(genResult.png, pngOutput)
    console.log(`✓ 额外输出: ${output}`)
  }

  // 输出元数据
  if (metadata?.generation) {
    console.log(`  生成耗时: ${stage1Duration}ms`)
  }
  if (metadata?.quality) {
    const q = metadata.quality
    console.log(`  轮廓偏差: ${q.contour_deviation?.toFixed(4) || 'N/A'}`)
  }

  // ── 写入 tasks-index.json ──
  try {
    await appendTaskIndex(outputDir, {
      id: task.id,
      mode: 'single',
      title: text || '艺术字流水线',
      time: startedAt,
      status: '完成',
      taskDir: taskInfo.taskDir,
      paths: taskInfo.paths,
      inputParams: { mode: 'single', text, prompt, negative, resolution, seed, vector: vectorConfig },
    })
  } catch (indexErr) {
    console.warn(`  ⚠ 写入任务索引失败: ${indexErr.message}`)
  }

  return { pngPath: taskInfo.paths.original, svgPath: taskInfo.paths.svg, taskDir: taskInfo.taskDir, metadata }
}
