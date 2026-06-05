/**
 * 后端 API 调用层
 * 与 desktop 共用相同的后端接口，直接 HTTP 调用（无 Electron IPC）
 */

const TXT2IMG_URL = process.env.TXT2IMG_BACKEND_URL || 'http://127.0.0.1:9001/api/v1/txt2img'
const VECTORIZER_URL = process.env.VECTORIZER_BACKEND_URL || 'http://127.0.0.1:8000/api/v1/vectorize'
const TXT2IMG_WORKFLOW = process.env.TXT2IMG_WORKFLOW || 'test_z_image_turbo'

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
  const { text, prompt = '', negative = '', resolution = '1024x1024', seed = 0, style = 'default' } = options

  const combinedPrompt = text
    ? `艺术字文本：${text}，风格：${prompt}`
    : prompt

  const body = {
    prompt: combinedPrompt,
    negative_prompt: negative,
    resolution: resolution.replace(/\s/g, ''),
    seed,
    style,
    format: 'PNG',
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
  const { imageBase64, imageName, vector = {} } = options

  const body = {
    source_type: 'upload',
    image_base64: imageBase64,
    image_name: imageName || 'cli-input',
    vector: {
      preset: vector.preset || 'balanced',
      evaluate_quality: vector.evaluateQuality !== false,
      remove_edge_white_background: vector.removeEdgeWhite !== false,
      ...(vector.colorPrecision != null && { color_precision: vector.colorPrecision }),
      ...(vector.filterSpeckle != null && { filter_speckle: vector.filterSpeckle }),
      ...(vector.cornerThreshold != null && { corner_threshold: vector.cornerThreshold }),
      ...(vector.lengthThreshold != null && { length_threshold: vector.lengthThreshold }),
      ...(vector.layerDifference != null && { layer_difference: vector.layerDifference }),
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
    imageBase64: genResult.png,
    imageName: options.text || 'art',
    vector: {
      preset: options.vectorPreset || 'balanced',
    },
  })

  return {
    png: genResult.png,
    svg: vecResult.svg,
    metadata: {
      generation: genResult.metadata,
      vectorization: vecResult.metadata,
    },
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
