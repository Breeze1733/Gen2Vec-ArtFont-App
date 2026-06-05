/**
 * generate 命令 - 生成艺术字位图
 */

import { generateArtBitmap } from '../api.mjs'
import { saveBase64ToFile } from '../utils/file.mjs'
import { augmentMetadata, buildRunLog, createCliTask, prepareOutputTask, resolveStatus, writeTaskArtifacts } from '../utils/output.mjs'

/**
 * 生成艺术字位图
 * @param {Object} args
 * @param {string} args.text - 艺术字文本
 * @param {string} [args.prompt] - 风格提示词
 * @param {string} [args.negative] - 负面提示词
 * @param {string} [args.resolution] - 分辨率
 * @param {number} [args.seed] - 随机种子
 * @param {string} [args.output] - 输出文件路径
 * @returns {Promise<{pngPath: string, metadata: Object}>}
 */
export async function run(args) {
  const { text, prompt = '', negative = '', resolution = '1024 x 1024', seed = 0, output, outputDir = 'outputs' } = args

  console.log(`正在生成艺术字: "${text}"...`)

  const startedAt = new Date().toISOString()
  const task = createCliTask({ title: text || '艺术字位图', mode: 'generate', startedAt })
  const t1 = Date.now()
  const result = await generateArtBitmap({
    text,
    prompt,
    negative,
    resolution,
    seed,
    format: 'PNG',
  })
  const stage1Duration = Date.now() - t1

  if (output) {
    await saveBase64ToFile(result.png, output)
    console.log(`✓ PNG 已保存: ${output}`)
    return { pngPath: output, metadata: result.metadata }
  }

  const taskInfo = await prepareOutputTask({ mode: 'generate', index: 1, seed, startedAt, outputRoot: outputDir })
  const status = resolveStatus(result.metadata)
  const metadata = augmentMetadata(result.metadata, { task, taskInfo, modeName: 'generate', text, prompt, seed, usesTxt2Img: true })
  await writeTaskArtifacts({
    outputRoot: taskInfo.outputRoot,
    taskDir: taskInfo.taskDir,
    taskName: taskInfo.taskName,
    paths: taskInfo.paths,
    artifacts: { original: result.png },
    metadata,
    runLog: buildRunLog({
      task,
      taskInfo,
      modeName: 'generate',
      text,
      prompt,
      seed,
      stage1Duration,
      status,
      usesTxt2Img: true,
      engine: result.metadata?.engine || '',
    }),
    usesTxt2Img: true,
    workflowArtifacts: {
      workflowApi: result.workflow_api || null,
      modelDependencies: result.model_dependencies || null,
    },
  })

  console.log(`✓ 任务目录: ${taskInfo.taskDir}`)
  console.log(`  original: ${taskInfo.paths.original}`)
  console.log(`  metadata: ${taskInfo.paths.metadata}`)

  if (result.metadata) {
    console.log(`  生成耗时: ${stage1Duration}ms`)
  }

  return { pngPath: taskInfo.paths.original, taskDir: taskInfo.taskDir, metadata }
}
