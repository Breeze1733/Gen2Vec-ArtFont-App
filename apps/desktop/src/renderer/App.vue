<template>
  <div class="app-shell">
    <header class="hero">
      <div class="hero-content">
        <p class="eyebrow">Local-first studio</p>
        <h1>矢量艺术字生成器</h1>
        <p class="subtitle">
          管理单条提示词、批量提示词和已有图片矢量化流程，面向后续模型接入与桌面端打包。
        </p>
      </div>

      <div class="hero-panel" aria-label="运行概览">
        <div>
          <span>模型版本</span>
          <strong>v3.1.0</strong>
        </div>
        <div>
          <span>工作流版本</span>
          <strong>flow-2026.05</strong>
        </div>
        <div>
          <span>运行环境</span>
          <strong>本地 GPU</strong>
        </div>
      </div>
    </header>

    <ModeSwitcher v-model:modelValue="mode" :modes="modes" />

    <main class="workspace">
      <div>
        <GenerationForm
          :mode="mode"
          :payload="payload"
          :running="running"
          :error="error"
          :vector-presets="vectorPresets"
          @file-change="handleFileChange"
          @update:mode="(v) => (mode.value = v)"
          @batch-file="(info) => { payload.batch = info.content }"
          @submit="startGeneration"
          @reset="resetForm"
          @preset-change="applyVectorPreset"
        />

        <ResultPanel :result="result" @download="downloadOutput" @save-all="saveAllResults" @open-svg="handleOpenSvg" />
      </div>

      <HistoryPanel :logs="logs" :current-files="currentFiles" @export-history="exportHistory" @delete-history="deleteHistoryItem" />
    </main>

    <section class="panel command-panel">
      <div>
        <p class="section-kicker">CLI</p>
        <h2>命令行入口</h2>
        <p>适用于批处理和自动化脚本，参数与界面保持一致。</p>
      </div>
      <code>art-text-gen --mode batch --input prompts.txt --out ./output</code>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import ModeSwitcher from './components/ModeSwitcher.vue'
import GenerationForm from './components/GenerationForm.vue'
import ResultPanel from './components/ResultPanel.vue'
import HistoryPanel from './components/HistoryPanel.vue'
import { generateArtBitmap, saveFile, saveResults, vectorizeArtImage } from './api'

const modes = [
  { label: '单条提示词', value: 'single' },
  { label: '批量提示词', value: 'batch' },
  { label: '图片矢量化', value: 'vectorize' }
]

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

      result.transparent = respB.transparent_png || respB.png || ''
      result.preview = respB.png || ''
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

      result.transparent = respB.transparent_png || respB.png || ''
      result.preview = respB.png || ''
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
        result.preview = respB.png || ''
        result.svg = respB.svg || ''
        result.metadata = respB.metadata || null
      }
      const base = getFileNameBase()
      const files = []
      if (result.original) files.push({ key: 'original', name: `${base}_original.png`, data: result.original, isText: false })
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

  if (type === 'png' && result.image) {
    const defaultName = `${fileNameBase}.png`
    try {
      const saved = await saveWithElectron(result.image, defaultName, [{ name: 'PNG', extensions: ['png'] }])
      if (saved) return
    } catch (err) {
      console.warn('Electron 保存 PNG 失败：', err)
    }

    const a = document.createElement('a')
    a.href = result.image
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
  applyVectorPreset('balanced')
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
      const saveResult = await saveResults({ png: result.image, svg: result.svg, metadata: result.metadata }, fileBase)
      if (!saveResult?.canceled) {
        return
      }
    }
  } catch (err) {
    console.warn('保存结果失败：', err)
  }

  if (result.image) {
    const a = document.createElement('a')
    a.href = result.image
    a.download = `${fileBase}.png`
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  if (result.svg) {
    const blob = new Blob([result.svg], { type: 'image/svg+xml;charset=utf-8' })
    downloadFile(`${fileBase}.svg`, blob)
  }

  if (result.metadata) {
    const blob = new Blob([JSON.stringify(result.metadata, null, 2)], { type: 'application/json;charset=utf-8' })
    downloadFile(`${fileBase}.json`, blob)
  }
}

const deleteHistoryItem = (id) => {
  logs.value = logs.value.filter((item) => item.id !== id)
  saveHistory()
}
</script>
