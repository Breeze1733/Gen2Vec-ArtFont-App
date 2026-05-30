/**
 * generate 命令 - 生成艺术字位图
 */

import { generateArtBitmap } from '../api.mjs'
import { saveBase64ToFile } from '../utils/file.mjs'

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
  const { text, prompt, negative, resolution, seed, output } = args

  console.log(`正在生成艺术字: "${text}"...`)

  const result = await generateArtBitmap({
    text,
    prompt,
    negative,
    resolution,
    seed,
  })

  // 保存 PNG
  const pngPath = output || `${text || 'output'}.png`
  await saveBase64ToFile(result.png, pngPath)

  console.log(`✓ PNG 已保存: ${pngPath}`)

  if (result.metadata) {
    console.log(`  生成耗时: ${result.metadata.duration || 'N/A'}ms`)
  }

  return { pngPath, metadata: result.metadata }
}
