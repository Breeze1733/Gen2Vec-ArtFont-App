/**
 * vectorize 命令 - 将位图矢量化为 SVG
 */

import { vectorizeImage } from '../api.mjs'
import { readFileAsBase64, saveSvgToFile, saveBase64ToFile } from '../utils/file.mjs'
import { augmentMetadata, buildRunLog, createCliTask, prepareOutputTask, writeTaskArtifacts } from '../utils/output.mjs'
import path from 'node:path'

/**
 * 矢量化位图
 * @param {Object} args
 * @param {string} args.input - 输入图片路径
 * @param {string} [args.output] - 输出 SVG 路径
 * @param {string} [args.preset] - 矢量化预设
 * @param {boolean} [args.preview] - 是否保存预览 PNG
 * @returns {Promise<{svgPath: string, metadata: Object}>}
 */
export async function run(args) {
  const { input, output, preset = 'balanced', preview = false, outputDir = 'outputs', vector = {} } = args

  console.log(`正在矢量化: ${input}...`)

  const startedAt = new Date().toISOString()
  const task = createCliTask({ title: path.basename(input), mode: 'vectorize', startedAt })
  const taskInfo = await prepareOutputTask({ mode: 'vectorize', index: 1, text: path.basename(input, path.extname(input)) || 'uploaded-image', seed: 0, startedAt, outputRoot: outputDir })

  // 读取输入文件
  const imageBase64 = await readFileAsBase64(input)

  let result
  const t2 = Date.now()
  try {
    result = await vectorizeImage({
      imagePath: input,
      imageName: path.basename(input),
      sourceType: 'upload',
      vector: { preset, ...vector },
      timeoutMs: 120000,
    })
  } catch (pathErr) {
    console.warn(`  路径读取失败，回退 base64: ${pathErr.message}`)
    result = await vectorizeImage({
      imageBase64,
      imageName: path.basename(input),
      sourceType: 'upload',
      vector: { preset, ...vector },
      timeoutMs: 120000,
    })
  }
  const stage2Duration = Date.now() - t2

  const metadata = augmentMetadata(result.metadata, { task, taskInfo, modeName: 'vectorize', seed: 0, usesTxt2Img: false })
  await writeTaskArtifacts({
    outputRoot: taskInfo.outputRoot,
    taskDir: taskInfo.taskDir,
    taskName: taskInfo.taskName,
    paths: taskInfo.paths,
    artifacts: {
      original: imageBase64,
      transparent: result.transparent_png,
      preview: result.preview_png || result.png,
      svg: result.svg,
    },
    metadata,
    runLog: buildRunLog({ task, taskInfo, modeName: 'vectorize', stage2Duration, status: 'success', usesTxt2Img: false }),
    usesTxt2Img: false,
  })

  console.log(`✓ 任务目录: ${taskInfo.taskDir}`)
  console.log(`  SVG: ${taskInfo.paths.svg}`)
  console.log(`  preview: ${taskInfo.paths.preview}`)

  if (output) {
    await saveSvgToFile(result.svg, output)
    console.log(`✓ 额外 SVG 已保存: ${output}`)
  }

  // 可选：保存预览 PNG
  if (preview && result.preview_png) {
    const previewPath = output
      ? (/\.svg$/i.test(output) ? output.replace(/\.svg$/i, '-preview.png') : `${output}-preview.png`)
      : taskInfo.paths.preview
    await saveBase64ToFile(result.preview_png, previewPath)
    console.log(`✓ 预览已保存: ${previewPath}`)
  }

  // 输出质量信息
  if (result.metadata?.quality) {
    const q = result.metadata.quality
    console.log(`  轮廓偏差: ${q.contour_deviation?.toFixed(4) || 'N/A'}`)
    console.log(`  颜色数量: ${q.color_count || 'N/A'}`)
  }

  return { svgPath: taskInfo.paths.svg, taskDir: taskInfo.taskDir, metadata }
}
