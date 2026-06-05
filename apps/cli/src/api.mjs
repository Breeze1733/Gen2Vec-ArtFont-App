/**
 * 后端 API 调用层
 * 与 desktop 共用相同的后端接口，直接 HTTP 调用（无 Electron IPC）
 */

const TXT2IMG_URL = process.env.TXT2IMG_BACKEND_URL || 'http://127.0.0.1:9001/api/v1/txt2img'
const VECTORIZER_URL = process.env.VECTORIZER_BACKEND_URL || 'http://127.0.0.1:8000/api/v1/vectorize'
const TXT2IMG_WORKFLOW = process.env.TXT2IMG_WORKFLOW || ''

/**
 * 生成艺术字位图
 * @param {Object} options
 * @param {string} options.text - 艺术字文本
 * @param {string} [options.prompt] - 风格提示词
 * @param {string} [options.negative] - 负面提示词
 * @param {string} [options.resolution] - 分辨率，如 "1024x1024"
 * @param {number} [options.seed] - 随机种子
 * @param {string} [options.style] - 风格
 * @returns {Promise<{png: string, metadata: Object}>}
 */
export async function generateArtBitmap(options) {
  const { text = '', prompt = '', negative = '', resolution = '1024 x 1024', seed = 0, style = 'default', format = 'PNG' } = options

  const body = {
    text,
    prompt,
    negative_prompt: negative,
    resolution: resolution.replace(/\s/g, ''),
    seed,
    style,
    format: format === 'SVG Only' ? 'PNG' : 'PNG',
    workflow: TXT2IMG_WORKFLOW,
  }

  const response = await fetch(TXT2IMG_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const errBody = await response.json().catch(() => ({}))
    throw new Error(errBody.detail || `txt2img 返回 ${response.status}`)
  }

  const data = await response.json()
  return {
    png: data.image_base64 || '',
    image_name: data.image_name || '',
    metadata: data.metadata || null,
    workflow_api: data.workflow_api || null,
    model_dependencies: data.model_dependencies || null,
  }
}

/**
 * 矢量化位图
 * @param {Object} options
 * @param {string} options.imageBase64 - 位图 base64
 * @param {string} [options.imageName] - 图片名称
 * @param {Object} [options.vector] - 矢量化配置
 * @param {string} [options.vector.preset] - 预设: clean | balanced | detailed | ultra
 * @param {boolean} [options.vector.evaluateQuality] - 是否评估质量
 * @returns {Promise<{svg: string, transparent_png: string, preview_png: string, metadata: Object}>}
 */
export async function vectorizeImage(options) {
  const {
    imageBase64,
    imagePath,
    imageName,
    sourceType = 'upload',
    text = '',
    prompt = '',
    negative = '',
    resolution = '1024 x 1024',
    format = 'PNG + SVG',
    seed = 0,
    generatedImage,
    timeoutMs,
    vector = {},
  } = options
  const pickVector = (camelName, snakeName) => vector[camelName] ?? vector[snakeName]

  const body = {
    source_type: sourceType,
    text,
    prompt,
    negative,
    resolution,
    format,
    seed,
    image_base64: imageBase64,
    image_path: imagePath,
    image_name: imageName || 'cli-input',
    generated_image: generatedImage,
    ...(timeoutMs != null && { __timeoutMs: timeoutMs }),
    vector: {
      preset: vector.preset || 'balanced',
      evaluate_quality: pickVector('evaluateQuality', 'evaluate_quality') !== false,
      remove_edge_white_background: pickVector('removeEdgeWhite', 'remove_edge_white_background') !== false,
      ...(pickVector('colorPrecision', 'color_precision') != null && { color_precision: pickVector('colorPrecision', 'color_precision') }),
      ...(pickVector('filterSpeckle', 'filter_speckle') != null && { filter_speckle: pickVector('filterSpeckle', 'filter_speckle') }),
      ...(pickVector('cornerThreshold', 'corner_threshold') != null && { corner_threshold: pickVector('cornerThreshold', 'corner_threshold') }),
      ...(pickVector('lengthThreshold', 'length_threshold') != null && { length_threshold: pickVector('lengthThreshold', 'length_threshold') }),
      ...(pickVector('layerDifference', 'layer_difference') != null && { layer_difference: pickVector('layerDifference', 'layer_difference') }),
      ...(vector.scale != null && { scale: vector.scale }),
    },
  }

  const response = await fetch(VECTORIZER_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })

  if (!response.ok) {
    const errBody = await response.json().catch(() => ({}))
    throw new Error(errBody.detail || `vectorizer 返回 ${response.status}`)
  }

  return response.json()
}

/**
 * 完整流水线：文本 → 位图 → SVG
 * @param {Object} options
 * @param {string} options.text - 艺术字文本
 * @param {string} [options.prompt] - 风格提示词
 * @param {string} [options.negative] - 负面提示词
 * @param {string} [options.resolution] - 分辨率
 * @param {number} [options.seed] - 随机种子
 * @param {string} [options.vectorPreset] - 矢量化预设
 * @returns {Promise<{png: string, svg: string, metadata: Object}>}
 */
export async function pipeline(options) {
  // 第一步：生成位图
  const genResult = await generateArtBitmap(options)

  // 第二步：矢量化
  const vecResult = await vectorizeImage({
    sourceType: 'generated',
    imageBase64: genResult.png,
    imageName: genResult.image_name || options.text || 'art',
    text: options.text || '',
    prompt: options.prompt || '',
    negative: options.negative || '',
    resolution: options.resolution || '1024 x 1024',
    format: 'PNG + SVG',
    seed: options.seed || 0,
    vector: {
      preset: options.vectorPreset || 'balanced',
    },
  })

  return {
    png: genResult.png,
    transparent_png: vecResult.transparent_png,
    preview_png: vecResult.preview_png,
    svg: vecResult.svg,
    metadata: {
      generation: genResult.metadata,
      vectorization: vecResult.metadata,
    },
    workflow_api: genResult.workflow_api || null,
    model_dependencies: genResult.model_dependencies || null,
  }
}

/**
 * 健康检查
 * @returns {Promise<{txt2img: boolean, vectorizer: boolean}>}
 */
export async function healthCheck() {
  const check = async (url) => {
    try {
      const resp = await fetch(url.replace(/\/api\/v1\/.*/, '/healthz'))
      return resp.ok
    } catch {
      return false
    }
  }

  return {
    txt2img: await check(TXT2IMG_URL),
    vectorizer: await check(VECTORIZER_URL),
  }
}

/**
 * 关闭两个后端服务。
 * 发送 POST /shutdown 到两个后端，不等待响应（后端收到后即退出）。
 * @returns {Promise<{txt2img: boolean, vectorizer: boolean}>}
 */
export async function shutdownBackends() {
  const TXT2IMG_SHUTDOWN = TXT2IMG_URL.replace(/\/api\/v1\/.*/, '/shutdown')
  const VECTORIZER_SHUTDOWN = VECTORIZER_URL.replace(/\/api\/v1\/.*/, '/shutdown')

  const call = async (url) => {
    try {
      await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      return true
    } catch {
      // 后端可能本来就已关闭，或收到请求后立即退出导致连接断开
      return true
    }
  }

  return {
    txt2img: await call(TXT2IMG_SHUTDOWN),
    vectorizer: await call(VECTORIZER_SHUTDOWN),
  }
}
