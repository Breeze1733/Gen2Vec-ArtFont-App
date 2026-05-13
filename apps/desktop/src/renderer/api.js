function escapeXml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function parseResolution(resolution) {
  const parts = String(resolution).split('x').map((part) => Number(part.trim()))
  if (parts.length === 2 && parts[0] > 0 && parts[1] > 0) {
    return { width: parts[0], height: parts[1] }
  }
  return { width: 1024, height: 1024 }
}

function createSvgText(payload) {
  const { width, height } = parseResolution(payload.resolution)
  const title = escapeXml(payload.text || '艺术字')
  const prompt = escapeXml(payload.prompt || '艺术字风格')
  const bg = payload.format === 'SVG Only' ? '#ffffff' : 'linear-gradient(135deg, #f8fafc, #ecfdf5)'

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="gradient" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f766e" />
      <stop offset="100%" stop-color="#14b8a6" />
    </linearGradient>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="6" result="coloredBlur" />
      <feMerge>
        <feMergeNode in="coloredBlur" />
        <feMergeNode in="SourceGraphic" />
      </feMerge>
    </filter>
  </defs>
  <rect width="100%" height="100%" fill="${bg}" />
  <rect x="40" y="40" width="${width - 80}" height="${height - 80}" rx="36" ry="36" fill="rgba(255,255,255,0.7)" stroke="#0f766e" stroke-width="3" />
  <text x="50%" y="45%" text-anchor="middle" fill="url(#gradient)" font-family="PingFang SC, sans-serif" font-size="${Math.round(width / 8)}" font-weight="800" filter="url(#glow)">${title}</text>
  <text x="50%" y="62%" text-anchor="middle" fill="#475569" font-family="Inter, sans-serif" font-size="${Math.round(width / 24)}">${prompt}</text>
</svg>`
}

function renderSvgToPng(svg, width, height) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        reject(new Error('无法创建画布上下文'))
        return
      }
      ctx.clearRect(0, 0, width, height)
      ctx.drawImage(img, 0, 0, width, height)
      resolve(canvas.toDataURL('image/png'))
    }
    img.onerror = (event) => {
      reject(new Error('SVG 转 PNG 失败'))
    }
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  })
}

function createMetadata(payload, svg) {
  return {
    text: payload.text || '',
    prompt: payload.prompt || '',
    negative: payload.negative || '',
    format: payload.format,
    resolution: payload.resolution,
    seed: payload.seed,
    vector: payload.vector,
    createdAt: new Date().toISOString(),
    svgLength: svg.length
  }
}

async function generateMockResult(payload) {
  const svg = createSvgText(payload)
  const { width, height } = parseResolution(payload.resolution)
  const png = await renderSvgToPng(svg, width, height)
  const metadata = createMetadata(payload, svg)

  return {
    png,
    svg,
    metadata
  }
}

export async function generateArtText(payload) {
  if (window.artTextApp?.generate) {
    try {
      return await window.artTextApp.generate(payload)
    } catch (err) {
      console.warn('Electron backend generate failed:', err)
      return generateMockResult(payload)
    }
  }

  return generateMockResult(payload)
}

export async function saveFile(data, defaultName, filters = []) {
  if (window.artTextApp?.saveFile) {
    return window.artTextApp.saveFile({ data, defaultName, filters })
  }

  throw new Error('Electron 保存接口不可用')
}
