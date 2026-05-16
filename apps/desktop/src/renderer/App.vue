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
          @file-change="handleFileChange"
          @submit="startGeneration"
          @reset="resetForm"
        />

        <ResultPanel :result="result" @download="downloadOutput" @save-all="saveAllResults" />
      </div>

      <HistoryPanel :logs="logs" @export-history="exportHistory" @delete-history="deleteHistoryItem" />
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
  format: 'PNG + SVG',
  seed: 0,
  imageFile: null,
  vector: {
    smooth: 6,
    threshold: 42,
    colors: 8
  }
})

const result = reactive({
  image: '',
  svg: '',
  metadata: null
})

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

const handleFileChange = (event) => {
  const file = event.target.files?.[0]
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
    let imageBase64 = null
    let imageName = null
    if (mode.value === 'vectorize' && payload.imageFile) {
      imageBase64 = await fileToDataUrl(payload.imageFile)
      imageName = payload.imageFile.name
    }

    const payloadForApi = {
      mode: mode.value,
      source_type: mode.value === 'vectorize' ? 'upload' : undefined,
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

    const response = mode.value === 'vectorize' ? await vectorizeArtImage(payloadForApi) : await generateArtBitmap(payloadForApi)

    result.image = response.png
    result.svg = response.svg
    result.metadata = response.metadata

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
    if (window.artTextApp?.saveFile) {
      const saved = await saveWithElectron(result.image, defaultName, [{ name: 'PNG', extensions: ['png'] }])
      if (saved) return
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
    if (window.artTextApp?.saveFile) {
      const saved = await saveWithElectron(result.svg, defaultName, [{ name: 'SVG', extensions: ['svg'] }])
      if (saved) return
    }

    const blob = new Blob([result.svg], { type: 'image/svg+xml;charset=utf-8' })
    downloadFile(defaultName, blob)
    return
  }

  if (type === 'json' && result.metadata) {
    const defaultName = `${fileNameBase}.json`
    const jsonText = JSON.stringify(result.metadata, null, 2)
    if (window.artTextApp?.saveFile) {
      const saved = await saveWithElectron(jsonText, defaultName, [{ name: 'JSON', extensions: ['json'] }])
      if (saved) return
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
  payload.vector.smooth = 6
  payload.vector.threshold = 42
  payload.vector.colors = 8
  error.value = ''
  result.image = ''
  result.svg = ''
  result.metadata = null
}

const exportHistory = () => {
  const data = JSON.stringify(logs.value, null, 2)
  const blob = new Blob([data], { type: 'application/json;charset=utf-8' })
  downloadFile('art-text-history.json', blob)
}

const saveAllResults = async () => {
  const fileBase = getFileNameBase()

  try {
    if (window.artTextApp?.saveResults) {
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
