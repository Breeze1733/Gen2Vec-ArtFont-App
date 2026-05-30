<template>
  <div class="app-shell">
    <header class="hero">
      <div class="hero-content">
        <h1>矢量艺术字生成器</h1>
        <div class="hero-tabs">
          <button
            :class="['tab-button', { active: activeTab === 'input' }]"
            type="button"
            @click="activeTab = 'input'"
          >
            输入面板
          </button>
          <button
            :class="['tab-button', { active: activeTab === 'output' }]"
            type="button"
            @click="activeTab = 'output'"
          >
            输出面板
          </button>
          <button
            :class="['tab-button', { active: activeTab === 'history' }]"
            type="button"
            @click="activeTab = 'history'"
          >
            历史任务
          </button>
        </div>
      </div>

      <div class="hero-panel" aria-label="运行概览">
        <div>
          <span>运行环境</span>
          <strong>{{ gpuInfo }}</strong>
        </div>
        <div v-if="!hasDiscreteGpu" class="gpu-warning">
          只能使用图片矢量化模式
        </div>
      </div>
    </header>

    <!-- 输入面板 -->
    <div class="main-layout" v-if="activeTab === 'input'">
      <main class="workspace">
        <div class="params-row">
          <GenerationForm
            v-model:mode="mode"
            :payload="payload"
            :running="running"
            :error="error"
            :has-discrete-gpu="hasDiscreteGpu"
            @file-change="handleFileChange"
            @batch-file="(info) => { payload.batch = info.content }"
            @reset="resetForm"
          />

          <VectorParams
            :vector="payload.vector"
            :vector-presets="vectorPresets"
            :running="running"
            @update:vector="(v) => Object.assign(payload.vector, v)"
            @preset-change="applyVectorPreset"
            @submit="startGeneration"
          />
        </div>
      </main>
    </div>

    <!-- 输出面板 -->
    <div class="main-layout" v-if="activeTab === 'output'">
      <main class="workspace">
        <ResultPanel :result="result" @download="downloadOutput" @save-all="saveAllResults" @open-svg="handleOpenSvg" />
      </main>
    </div>

    <!-- 历史任务 -->
    <div class="main-layout" v-if="activeTab === 'history'">
      <HistoryPanel
        :logs="logs"
        :current-files="currentFiles"
        @export-history="exportHistory"
        @delete-history="deleteHistoryItem"
      />
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, onMounted } from 'vue'
import GenerationForm from './components/GenerationForm.vue'
import ResultPanel from './components/ResultPanel.vue'
import HistoryPanel from './components/HistoryPanel.vue'
import VectorParams from './components/VectorParams.vue'
import { generateArtBitmap, saveFile, saveResults, vectorizeArtImage } from './api'

// GPU 检测
const gpuInfo = ref('检测中...')
const hasDiscreteGpu = ref(false)

const detectGPU = () => {
  try {
    const canvas = document.createElement('canvas')
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl')
    if (!gl) {
      gpuInfo.value = 'CPU（无 WebGL）'
      hasDiscreteGpu.value = false
      return
    }

    const debugInfo = gl.getExtension('WEBGL_debug_renderer_info')
    if (debugInfo) {
      const renderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL)
      // 简化显示
      if (renderer.includes('NVIDIA') || renderer.includes('AMD') || renderer.includes('Radeon')) {
        gpuInfo.value = `GPU（${renderer.split(' ').slice(0, 2).join(' ')}）`
        hasDiscreteGpu.value = true
      } else if (renderer.includes('Intel')) {
        gpuInfo.value = `集成显卡（Intel）`
        hasDiscreteGpu.value = false
      } else {
        gpuInfo.value = `GPU（${renderer.substring(0, 30)}）`
        hasDiscreteGpu.value = true
      }
    } else {
      gpuInfo.value = 'GPU（WebGL）'
      hasDiscreteGpu.value = true
    }
  } catch (e) {
    gpuInfo.value = 'CPU（检测失败）'
    hasDiscreteGpu.value = false
  }
}

onMounted(() => {
  detectGPU()
  // 无独立显卡时默认选择图片矢量化模式
  if (!hasDiscreteGpu.value) {
    mode.value = 'vectorize'
  }
})

const activeTab = ref('input')

const vectorPresets = {
  clean: {
    preset: 'clean',
    color_precision: 3,
    filter_speckle: 15,
    corner_threshold: 60,
    length_threshold: 12,
    layer_difference: 20,
    scale: 2
  },
  balanced: {
    preset: 'balanced',
    color_precision: 5,
    filter_speckle: 6,
    corner_threshold: 45,
    length_threshold: 5,
    layer_difference: 10,
    scale: 2
  },
  detailed: {
    preset: 'detailed',
    color_precision: 6,
    filter_speckle: 2,
    corner_threshold: 30,
    length_threshold: 3,
    layer_difference: 4,
    scale: 3
  },
  ultra: {
    preset: 'ultra',
    color_precision: 8,
    filter_speckle: 1,
    corner_threshold: 20,
    length_threshold: 2,
    layer_difference: 2,
    scale: 3
  }
}

const HISTORY_KEY = 'art-text-generator-history'

const mode = ref('single')
const running = ref(false)
const error = ref('')

const payload = reactive({
  text: '',
  prompt: '',
  negative: '',
  batch: '',
  resolution: '1024 x 1024',
  format: 'PNG',
  seed: 0,
  imageFile: null,
  vector: { ...vectorPresets.balanced }
})

const applyVectorPreset = (presetName) => {
  const preset = vectorPresets[presetName] || vectorPresets.balanced
  Object.assign(payload.vector, preset)
}

const result = reactive({
  image: '',
  svg: '',
  metadata: null,
  original: '',
  preview: '',
  transparent: ''
})

const currentFiles = ref([])

const logs = ref(loadHistory())

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
  } catch {
    return []
  }
}

function saveHistory() {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(logs.value.slice(0, 50)))
}

const validateForm = () => {
  error.value = ''

  if (mode.value === 'single') {
    if (!payload.text.trim()) {
      error.value = '请输入艺术字文字内容。'
      return false
    }
    if (!payload.prompt.trim()) {
      error.value = '请输入风格提示词。'
      return false
    }
  }

  if (mode.value === 'vectorize') {
    if (!payload.imageFile) {
      error.value = '请选择要矢量化的图片文件。'
      return false
    }
  }

  return true
}

const handleFileChange = (file) => {
  payload.imageFile = file || null
}

const startGeneration = async () => {
  if (!validateForm()) {
    return
  }

  activeTab.value = 'output'
  error.value = ''
  running.value = true
  result.image = ''
  result.svg = ''
  result.metadata = null

  const taskTitle = mode.value === 'single' ? payload.text.trim() : mode.value === 'batch' ? '批量任务' : '图片矢量化'
  const task = {
    id: Date.now(),
    title: taskTitle,
    time: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
    status: '运行中',
    mode: mode.value === 'single' ? '单条' : mode.value === 'batch' ? '批量' : '矢量化'
  }

  logs.value.unshift(task)
  saveHistory()

  try {
    error.value = ''
    let imageBase64 = null
    let imageName = null
    let stage1Duration = 0
    let stage2Duration = 0

    // 准备上传图片（仅在 vectorize 模式）
    if (mode.value === 'vectorize' && payload.imageFile) {
      imageBase64 = await fileToDataUrl(payload.imageFile)
      imageName = payload.imageFile.name
      result.original = imageBase64
    }

    if (mode.value === 'single') {
      // Stage 1: 生成位图（后端 A）
      const payloadA = {
        text: payload.text.trim(),
        prompt: payload.prompt.trim(),
        negative: payload.negative.trim(),
        resolution: payload.resolution,
        format: payload.format,
        seed: payload.seed
      }
      const t1 = Date.now()
      const respA = await generateArtBitmap(payloadA)
      stage1Duration = Date.now() - t1

      imageBase64 = respA.png || ''
      imageName = respA.image_name || `${safeName(payload.text || 'art')}-orig.png`
      result.original = imageBase64

      // Stage 2: 矢量化（后端 B）
      const payloadB = {
        source_type: 'generated',
        text: payload.text.trim(),
        prompt: payload.prompt.trim(),
        negative: payload.negative.trim(),
        resolution: payload.resolution,
        format: payload.format,
        seed: payload.seed,
        vector: { ...payload.vector },
        image_base64: imageBase64,
        image_name: imageName
      }
      const t2 = Date.now()
      const respB = await vectorizeArtImage(payloadB)
      stage2Duration = Date.now() - t2

      result.transparent = respB.transparent_png || ''
      result.preview = respB.preview_png || respB.png || ''
      result.image = result.preview
      result.svg = respB.svg || ''
      result.metadata = respB.metadata || null

      // 构建文件列表
      const base = getFileNameBase()
      const files = []
      if (imageBase64) files.push({ key: 'original', name: `${base}_original.png`, data: imageBase64, isText: false })
      if (result.transparent) files.push({ key: 'transparent', name: `${base}_transparent.png`, data: result.transparent, isText: false })
      if (result.preview) files.push({ key: 'preview', name: `${base}_preview.png`, data: result.preview, isText: false })
      if (result.svg) files.push({ key: 'svg', name: `${base}_vector.svg`, data: result.svg, isText: true })
      if (result.metadata) files.push({ key: 'metadata', name: `${base}_metadata.json`, data: JSON.stringify(result.metadata, null, 2), isText: true })
      const logText = `task_id=${task.id}\nmode=single\ntext=${payload.text}\nseed=${payload.seed}\nstage1_ms=${stage1Duration}\nstage2_ms=${stage2Duration}\nstatus=success`
      files.push({ key: 'log', name: `${base}_log.log`, data: logText, isText: true })
      currentFiles.value = files

    } else if (mode.value === 'vectorize') {
      // 直接调用后端 B
      const payloadB = {
        source_type: 'upload',
        resolution: payload.resolution,
        format: payload.format,
        seed: payload.seed,
        vector: { ...payload.vector },
        image_base64: imageBase64,
        image_name: imageName
      }
      const t2 = Date.now()
      const respB = await vectorizeArtImage(payloadB)
      stage2Duration = Date.now() - t2

      result.transparent = respB.transparent_png || ''
      result.preview = respB.preview_png || respB.png || ''
      result.image = result.preview
      result.svg = respB.svg || ''
      result.metadata = respB.metadata || null

      const base = getFileNameBase()
      const files = []
      if (result.original) files.push({ key: 'original', name: `${base}_original.png`, data: result.original, isText: false })
      if (result.transparent) files.push({ key: 'transparent', name: `${base}_transparent.png`, data: result.transparent, isText: false })
      if (result.preview) files.push({ key: 'preview', name: `${base}_preview.png`, data: result.preview, isText: false })
      if (result.svg) files.push({ key: 'svg', name: `${base}_vector.svg`, data: result.svg, isText: true })
      if (result.metadata) files.push({ key: 'metadata', name: `${base}_metadata.json`, data: JSON.stringify(result.metadata, null, 2), isText: true })
      const logText = `task_id=${task.id}\nmode=vectorize\nseed=${payload.seed}\nstage2_ms=${stage2Duration}\nstatus=success`
      files.push({ key: 'log', name: `${base}_log.log`, data: logText, isText: true })
      currentFiles.value = files

    } else if (mode.value === 'batch') {
      // 简单批处理：每行一个任务，顺序执行
      const lines = String(payload.batch || '').split(/\r?\n/).map(l => l.trim()).filter(Boolean)
      for (const line of lines) {
        const parts = line.split('|').map(p => p.trim())
        const text = parts[0] || ''
        const prompt = parts[1] || ''
        const payloadA = { text, prompt, negative: payload.negative || '', resolution: payload.resolution, format: payload.format, seed: payload.seed }
        const respA = await generateArtBitmap(payloadA)
        const payloadB = { source_type: 'generated', text, prompt, negative: payload.negative || '', resolution: payload.resolution, format: payload.format, seed: payload.seed, vector: { ...payload.vector }, image_base64: respA.png, image_name: respA.image_name || `${safeName(text || 'batch')}-orig.png` }
        const respB = await vectorizeArtImage(payloadB)
        result.original = respA.png
        result.transparent = respB.transparent_png || ''
        result.preview = respB.preview_png || respB.png || ''
        result.image = result.preview
        result.svg = respB.svg || ''
        result.metadata = respB.metadata || null
      }
      const base = getFileNameBase()
      const files = []
      if (result.original) files.push({ key: 'original', name: `${base}_original.png`, data: result.original, isText: false })
      if (result.transparent) files.push({ key: 'transparent', name: `${base}_transparent.png`, data: result.transparent, isText: false })
      if (result.preview) files.push({ key: 'preview', name: `${base}_preview.png`, data: result.preview, isText: false })
      if (result.svg) files.push({ key: 'svg', name: `${base}_vector.svg`, data: result.svg, isText: true })
      if (result.metadata) files.push({ key: 'metadata', name: `${base}_metadata.json`, data: JSON.stringify(result.metadata, null, 2), isText: true })
      const logText = `task_id=${task.id}\nmode=batch\nitems=${lines.length}\nstatus=completed`
      files.push({ key: 'log', name: `${base}_log.log`, data: logText, isText: true })
      currentFiles.value = files
    }

    task.status = '完成'
    saveHistory()
  } catch (err) {
    error.value = err?.message || '生成失败，请稍后重试。'
    task.status = '失败'
    saveHistory()
  } finally {
    running.value = false
  }
}

const fileToDataUrl = (file) =>
  new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('图片读取失败，请重试'))
    reader.readAsDataURL(file)
  })

const downloadFile = (filename, blob) => {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

const handleOpenSvg = (type) => {
  if (!result.svg) return
  const svgText = result.svg
  const blob = new Blob([svgText], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  window.open(url, '_blank')
  // 不立即 revoke，以便用户查看；浏览器在标签页关闭后释放
}

const saveWithElectron = async (data, filename, filters) => {
  try {
    const result = await saveFile(data, filename, filters)
    if (result?.canceled) {
      return false
    }

    return !!result?.filePath
  } catch (err) {
    console.warn('Electron save failed:', err)
    return false
  }
}

const getFileNameBase = () => {
  if (mode.value === 'vectorize' && payload.imageFile?.name) {
    return `${stripExtension(payload.imageFile.name)}-vectorized`
  }
  return safeName(payload.text || 'art-text')
}

const stripExtension = (name) => {
  return name.replace(/\.[^.]+$/, '')
}

const downloadOutput = async (type) => {
  const fileNameBase = getFileNameBase()

  if (['original', 'transparent', 'preview'].includes(type)) {
    const imageMap = {
      original: {
        data: result.original,
        suffix: 'original',
        label: '原始图像'
      },
      transparent: {
        data: result.transparent,
        suffix: 'transparent',
        label: '透明化图像'
      },
      preview: {
        data: result.preview || result.image,
        suffix: 'preview',
        label: '矢量化预览'
      }
    }
    const target = imageMap[type]
    if (!target.data) return

    const defaultName = `${fileNameBase}_${target.suffix}.png`
    try {
      const saved = await saveWithElectron(target.data, defaultName, [{ name: 'PNG', extensions: ['png'] }])
      if (saved) return
    } catch (err) {
      console.warn(`Electron 保存 ${target.label} 失败：`, err)
    }

    const a = document.createElement('a')
    a.href = target.data
    a.download = defaultName
    document.body.appendChild(a)
    a.click()
    a.remove()
    return
  }

  if (type === 'svg' && result.svg) {
    const defaultName = `${fileNameBase}.svg`
    try {
      const saved = await saveWithElectron(result.svg, defaultName, [{ name: 'SVG', extensions: ['svg'] }])
      if (saved) return
    } catch (err) {
      console.warn('Electron 保存 SVG 失败：', err)
    }

    const blob = new Blob([result.svg], { type: 'image/svg+xml;charset=utf-8' })
    downloadFile(defaultName, blob)
    return
  }

  if (type === 'json' && result.metadata) {
    const defaultName = `${fileNameBase}.json`
    const jsonText = JSON.stringify(result.metadata, null, 2)
    try {
      const saved = await saveWithElectron(jsonText, defaultName, [{ name: 'JSON', extensions: ['json'] }])
      if (saved) return
    } catch (err) {
      console.warn('Electron 保存 JSON 失败：', err)
    }

    const blob = new Blob([jsonText], { type: 'application/json;charset=utf-8' })
    downloadFile(defaultName, blob)
    return
  }
}

const safeName = (name) => name.replace(/[<>:"/\\|?*]+/g, '-').trim() || 'art-text'

const resetForm = () => {
  payload.text = ''
  payload.prompt = ''
  payload.negative = ''
  payload.batch = ''
  payload.resolution = '1024 x 1024'
  payload.format = 'PNG + SVG'
  payload.seed = 0
  payload.imageFile = null
  error.value = ''
  result.image = ''
  result.svg = ''
  result.metadata = null
  result.original = ''
}

const exportHistory = () => {
  const data = JSON.stringify(logs.value, null, 2)
  const blob = new Blob([data], { type: 'application/json;charset=utf-8' })
  downloadFile('art-text-history.json', blob)
}

const saveAllResults = async () => {
  const fileBase = getFileNameBase()

  try {
    // 如果 currentFiles 有内容，优先按文件列表保存
    if (currentFiles.value && currentFiles.value.length) {
      const payload = {}
      currentFiles.value.forEach(f => { payload[f.key] = f.data })
      const saveResult = await saveResults(payload, fileBase)
      if (!saveResult?.canceled) {
        return
      }
    } else {
      const saveResult = await saveResults({
        original: result.original,
        transparent: result.transparent,
        preview: result.preview || result.image,
        svg: result.svg,
        metadata: result.metadata
      }, fileBase)
      if (!saveResult?.canceled) {
        return
      }
    }
  } catch (err) {
    console.warn('保存结果失败：', err)
  }

  const fallbackImages = [
    ['original', result.original],
    ['transparent', result.transparent],
    ['preview', result.preview || result.image]
  ]
  fallbackImages.forEach(([suffix, data]) => {
    if (!data) return
    const a = document.createElement('a')
    a.href = data
    a.download = `${fileBase}_${suffix}.png`
    document.body.appendChild(a)
    a.click()
    a.remove()
  })

  if (result.metadata) {
    const blob = new Blob([JSON.stringify(result.metadata, null, 2)], { type: 'application/json;charset=utf-8' })
    downloadFile(`${fileBase}_metadata.json`, blob)
  }
}

const deleteHistoryItem = (id) => {
  logs.value = logs.value.filter((item) => item.id !== id)
  saveHistory()
}
</script>
