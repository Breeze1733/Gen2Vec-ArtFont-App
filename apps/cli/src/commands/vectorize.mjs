/**
 * vectorize 命令 - 将位图矢量化为 SVG
 */

import { vectorizeImage } from '../api.mjs'
import { readFileAsBase64, saveSvgToFile, saveBase64ToFile } from '../utils/file.mjs'

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
  const { input, output, preset = 'balanced', preview = false } = args

  console.log(`正在矢量化: ${input}...`)

  // 读取输入文件
  const imageBase64 = await readFileAsBase64(input)

  // 调用矢量化 API
  const result = await vectorizeImage({
    imageBase64,
    imageName: input.split(/[\\/]/).pop(),
    vector: { preset },
  })

  // 保存 SVG
  const svgPath = output || input.replace(/\.[^.]+$/, '.svg')
  await saveSvgToFile(result.svg, svgPath)
  console.log(`✓ SVG 已保存: ${svgPath}`)

  // 可选：保存预览 PNG
  if (preview && result.preview_png) {
    const previewPath = svgPath.replace(/\.svg$/, '-preview.png')
    await saveBase64ToFile(result.preview_png, previewPath)
    console.log(`✓ 预览已保存: ${previewPath}`)
  }

  // 输出质量信息
  if (result.metadata?.quality) {
    const q = result.metadata.quality
    console.log(`  轮廓偏差: ${q.contour_deviation?.toFixed(4) || 'N/A'}`)
    console.log(`  颜色数量: ${q.color_count || 'N/A'}`)
  }

  return { svgPath, metadata: result.metadata }
}
