/**
 * pipeline 命令 - 完整流水线：文本 → 位图 → SVG
 */

import { pipeline } from '../api.mjs'
import { saveBase64ToFile, saveSvgToFile } from '../utils/file.mjs'

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
  const { text, prompt, negative, resolution, seed, vectorPreset, outputDir = '.' } = args

  console.log(`正在生成艺术字: "${text}"...`)
  console.log(`  矢量化预设: ${vectorPreset || 'balanced'}`)

  // 运行完整流水线
  const result = await pipeline({
    text,
    prompt,
    negative,
    resolution,
    seed,
    vectorPreset,
  })

  // 保存 PNG
  const pngPath = `${outputDir}/${text || 'output'}.png`
  await saveBase64ToFile(result.png, pngPath)
  console.log(`✓ PNG 已保存: ${pngPath}`)

  // 保存 SVG
  const svgPath = `${outputDir}/${text || 'output'}.svg`
  await saveSvgToFile(result.svg, svgPath)
  console.log(`✓ SVG 已保存: ${svgPath}`)

  // 输出元数据
  if (result.metadata?.generation) {
    console.log(`  生成耗时: ${result.metadata.generation.duration || 'N/A'}ms`)
  }
  if (result.metadata?.vectorization?.quality) {
    const q = result.metadata.vectorization.quality
    console.log(`  轮廓偏差: ${q.contour_deviation?.toFixed(4) || 'N/A'}`)
  }

  return { pngPath, svgPath, metadata: result.metadata }
}
