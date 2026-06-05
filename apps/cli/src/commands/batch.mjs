/**
 * batch 命令 - 批量生成艺术字（逐条处理，容错执行）
 *
 * 每行格式：文本 | 风格提示词
 * 支持 CSV/TXT 文件输入
 */

import { generateArtBitmap } from '../api.mjs'
import { vectorizeImage } from '../api.mjs'
import { saveBase64ToFile, saveSvgToFile } from '../utils/file.mjs'
import { createReadStream } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { createInterface } from 'node:readline'

/**
 * 解析输入：支持直接字符串、@file 引用或 - (stdin)
 * @param {string} input
 * @returns {Promise<Array<{text:string, prompt:string}>>}
 */
async function parseInputLines(input) {
  let content = input || ''

  // 从文件读取
  if (input && input.startsWith('@')) {
    const filePath = input.slice(1)
    content = await readFile(filePath, 'utf-8')
  }

  const lines = content.split(/\r?\n/).map(l => l.trim()).filter(Boolean)
  return lines.map(line => {
    // 支持 | 和 , 作为分隔符
    const sep = line.includes('|') ? '|' : (line.includes('\t') ? '\t' : ',')
    const parts = line.split(sep).map(p => p.trim())
    return {
      text: parts[0] || '',
      prompt: parts[1] || '',
      negative: parts[2] || '',
    }
  })
}

/**
 * 运行批量生成
 * @param {Object} args
 * @param {string} args.input - 批量输入（每行一条）或 @file 引用
 * @param {string} [args.negative] - 全局负面提示词
 * @param {string} [args.resolution] - 分辨率
 * @param {number} [args.seed] - 随机种子（每条递增）
 * @param {string} [args.vectorPreset] - 矢量化预设
 * @param {boolean} [args.vectorize] - 是否同时矢量化（默认 true）
 * @param {string} [args.outputDir] - 输出目录
 * @param {boolean} [args.preview] - 是否保存预览 PNG
 * @returns {Promise<{count: number, succeeded: number, failed: number, results: Array}>}
 */
export async function run(args) {
  const {
    input,
    negative = '',
    resolution,
    seed: baseSeed,
    vectorPreset,
    vectorize: doVectorize = true,
    outputDir = '.',
    preview = false,
  } = args

  console.log('正在解析批量输入...\n')

  const items = await parseInputLines(input)

  if (items.length === 0) {
    console.error('错误: 未找到有效的输入条目')
    process.exit(1)
  }

  console.log(`共 ${items.length} 条待处理\n`)

  const results = []
  let succeeded = 0
  let failed = 0

  for (let i = 0; i < items.length; i++) {
    const { text, prompt, negative: lineNegative } = items[i]
    const itemNegative = lineNegative || negative
    const seed = baseSeed != null ? Number(baseSeed) + i : undefined

    console.log(`[${i + 1}/${items.length}] 正在处理: "${text}"`)

    const result = {
      index: i + 1,
      text,
      prompt,
      status: 'running',
      pngPath: null,
      svgPath: null,
      metadata: null,
    }

    try {
      // Step 1: 生成位图
      console.log(`  → 生成位图...`)
      const genResult = await generateArtBitmap({
        text,
        prompt,
        negative: itemNegative,
        resolution,
        seed,
      })

      // 保存 PNG
      const safeName = text.replace(/[<>:"/\\|?*]+/g, '-').trim() || `item-${i + 1}`
      const pngPath = `${outputDir}/${safeName}.png`
      await saveBase64ToFile(genResult.png, pngPath)
      console.log(`  ✓ PNG: ${pngPath}`)

      result.pngPath = pngPath

      if (doVectorize) {
        // Step 2: 矢量化
        console.log(`  → 矢量化...`)
        const vecResult = await vectorizeImage({
          imageBase64: genResult.png,
          imageName: `${safeName}.png`,
          vector: {
            preset: vectorPreset || 'balanced',
            evaluateQuality: true,
            removeEdgeWhite: true,
          },
        })

        // 保存 SVG
        const svgPath = `${outputDir}/${safeName}.svg`
        await saveSvgToFile(vecResult.svg, svgPath)
        console.log(`  ✓ SVG: ${svgPath}`)
        result.svgPath = svgPath

        // 保存预览 PNG
        if (preview && vecResult.preview_png) {
          const previewPath = `${outputDir}/${safeName}-preview.png`
          await saveBase64ToFile(vecResult.preview_png, previewPath)
          console.log(`  ✓ 预览: ${previewPath}`)
        }

        // 保存透明图
        if (vecResult.transparent_png) {
          const transparentPath = `${outputDir}/${safeName}-transparent.png`
          await saveBase64ToFile(vecResult.transparent_png, transparentPath)
        }

        result.metadata = {
          generation: genResult.metadata,
          vectorization: vecResult.metadata,
        }
      } else {
        result.metadata = { generation: genResult.metadata }
      }

      result.status = 'success'
      succeeded++
    } catch (err) {
      result.status = 'failed'
      result.error = err.message
      failed++
      console.error(`  ✗ 失败: ${err.message}`)
    }

    results.push(result)
    console.log('')
  }

  // 输出汇总
  console.log('═'.repeat(40))
  console.log(`批量处理完成:`)
  console.log(`  总数:      ${items.length}`)
  console.log(`  成功:      ${succeeded}`)
  console.log(`  失败:      ${failed}`)

  // 输出失败的条目
  const failedItems = results.filter(r => r.status === 'failed')
  if (failedItems.length > 0) {
    console.log(`\n失败条目:`)
    for (const item of failedItems) {
      const label = item.text || `第 ${item.index} 条`
      console.log(`  [${item.index}] ${label}: ${item.error}`)
    }
  }

  return { count: items.length, succeeded, failed, results }
}
