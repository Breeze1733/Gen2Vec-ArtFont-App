/**
 * 文件操作工具函数
 */

import { writeFile, readFile, mkdir } from 'node:fs/promises'
import { dirname, join, extname } from 'node:path'

/**
 * 保存 base64 数据到文件
 * @param {string} base64Data - base64 编码的数据（可能包含 data:... 前缀）
 * @param {string} outputPath - 输出文件路径
 */
export async function saveBase64ToFile(base64Data, outputPath) {
  // 移除 data URL 前缀（如果有）
  const base64 = base64Data.replace(/^data:[^;]+;base64,/, '')
  const buffer = Buffer.from(base64, 'base64')

  // 确保目录存在
  await mkdir(dirname(outputPath), { recursive: true })
  await writeFile(outputPath, buffer)
}

/**
 * 保存 SVG 文本到文件
 * @param {string} svgText - SVG 文本内容
 * @param {string} outputPath - 输出文件路径
 */
export async function saveSvgToFile(svgText, outputPath) {
  await mkdir(dirname(outputPath), { recursive: true })
  await writeFile(outputPath, svgText, 'utf-8')
}

/**
 * 读取文件为 base64
 * @param {string} filePath - 文件路径
 * @returns {Promise<string>} base64 编码的文件内容
 */
export async function readFileAsBase64(filePath) {
  const buffer = await readFile(filePath)
  return buffer.toString('base64')
}

/**
 * 从文件路径推断 MIME 类型
 * @param {string} filePath
 * @returns {string}
 */
export function getMimeType(filePath) {
  const ext = extname(filePath).toLowerCase()
  const mimeMap = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.svg': 'image/svg+xml',
  }
  return mimeMap[ext] || 'application/octet-stream'
}

/**
 * 生成输出文件路径
 * @param {string} baseName - 基础名称
 * @param {string} ext - 扩展名（如 .svg）
 * @param {string} [outputDir] - 输出目录，默认当前目录
 * @returns {string}
 */
export function getOutputPath(baseName, ext, outputDir = '.') {
  return join(outputDir, `${baseName}${ext}`)
}
