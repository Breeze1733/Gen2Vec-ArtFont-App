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
        <!-- Intel 集显：可用但提醒性能 -->
        <div v-if="gpuTier === 'integrated'" class="gpu-info">
          <p>集显可用，但文生图速度可能较慢</p>
        </div>
        <!-- 无 GPU：仅矢量化模式 -->
        <div v-if="gpuTier === 'none'" class="gpu-warning">
          <p>仅限图片矢量化模式</p>
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
            :has-usable-gpu="hasUsableGpu"
            :gpu-tier="gpuTier"
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
        <ResultPanel
          :result="result"
          :mode="mode"
          :batch-items="batchItems"
          :batch-progress="batchProgress"
          :selected-batch-index="selectedBatchIndex"
          :running="running"
          @download="downloadOutput"
          @save-all="saveAllResults"
          @open-svg="handleOpenSvg"
          @select-batch-item="selectBatchItem"
        />
      </main>
    </div>

    <!-- 历史任务 -->
    <div class="main-layout" v-if="activeTab === 'history'">
      <HistoryPanel
        :logs="logs"
        :current-files="currentFiles"
        @export-history="exportHistory"
        @delete-history="deleteHistoryItem"
        @restore-history="restoreHistoryItem"
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
import { saveResultToDB, loadResultFromDB, deleteResultFromDB, cleanupResults, makeThumbnail } from './utils/storage'

// GPU 检测
const gpuInfo = ref('检测中...')
const gpuRawRenderer = ref('')
const gpuDetectFailed = ref(false)
const hasUsableGpu = ref(false)
const gpuTier = ref('unknown') // 'discrete' | 'integrated' | 'unknown' | 'none'

const detectGPU = () => {
  try {
    // 维度 1：WebGL UNMASKED_RENDERER_WEBGL
    const canvas = document.createElement('canvas')
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl')
    if (!gl) {
      gpuInfo.value = '未检测到 GPU（WebGL 不可用）'
      gpuTier.value = 'none'
      gpuDetectFailed.value = true
      hasUsableGpu.value = false
      return
    }

    const debugInfo = gl.getExtension('WEBGL_debug_renderer_info')
    let webglRenderer = ''
    if (debugInfo) {
      webglRenderer = gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL) || ''
      gpuRawRenderer.value = webglRenderer
    }

    // 维度 2：WebGPU adapter（如果可用）—— 可能暴露不同于 WebGL 的 GPU 信息
    try {
      if (typeof navigator !== 'undefined' && navigator.gpu) {
        navigator.gpu.requestAdapter().then(adapter => {
          if (adapter) {
            const info = adapter.info || {}
            const gpuName = [info.vendor, info.architecture].filter(Boolean).join(' ').trim() || '未知 GPU'
            // WebGPU 可能在不同上下文中暴露独显——如果 WebGL 漏掉了，这里补上
            if ((gpuName.includes('NVIDIA') || gpuName.includes('AMD') || gpuName.includes('Radeon'))
              && gpuTier.value !== 'discrete') {
              gpuTier.value = 'discrete'
              gpuInfo.value = `GPU（${gpuName.substring(0, 30)}）`
              hasUsableGpu.value = true
            }
          }
        }).catch(() => {})
      }
    } catch (_) { /* WebGPU 不可用，忽略 */ }

    // 维度 3：综合判定
    const renderer = webglRenderer
    if (renderer.includes('NVIDIA') || renderer.includes('AMD') || renderer.includes('Radeon')) {
      gpuInfo.value = `独立显卡（${renderer.split(' ').slice(0, 2).join(' ')}）`
      gpuTier.value = 'discrete'
      hasUsableGpu.value = true
    } else if (renderer.includes('Intel')) {
      gpuInfo.value = '集成显卡（Intel）'
      gpuTier.value = 'integrated'
      hasUsableGpu.value = true
    } else if (renderer) {
      gpuInfo.value = `GPU（${renderer.substring(0, 30)}）`
      gpuTier.value = 'unknown'
      hasUsableGpu.value = true
    } else {
      gpuInfo.value = 'GPU（WebGL）'
      gpuTier.value = 'unknown'
      hasUsableGpu.value = true
    }
  } catch (e) {
    gpuInfo.value = 'GPU 检测失败'
    gpuTier.value = 'none'
    gpuDetectFailed.value = true
    hasUsableGpu.value = false
  }
}

onMounted(() => {
  detectGPU()
  // 仅在完全没有 GPU 时默认选择图片矢量化模式
  if (!hasUsableGpu.value) {
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

// 批量模式状态
const batchItems = ref([])
const batchProgress = reactive({ current: 0, total: 0, completed: 0, failed: 0 })
const selectedBatchIndex = ref(-1)

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
  const trimmed = logs.value.slice(0, 50)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(trimmed))
  // 清理 IndexedDB 中已不在历史列表的旧数据
  cleanupResults(trimmed.map(l => l.id)).catch(() => {})
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
  result.original = ''
  result.preview = ''
  result.transparent = ''
  batchItems.value = []
  batchProgress.current = 0
  batchProgress.total = 0
  batchProgress.completed = 0
  batchProgress.failed = 0
  selectedBatchIndex.value = -1

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

      // 将生成耗时写入 metadata
      if (result.metadata) {
        result.metadata.generation = result.metadata.generation || {}
        result.metadata.generation.duration_ms = stage1Duration
      }

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
      // 批量处理：逐条执行，支持进度展示和单条错误容错
      const lines = String(payload.batch || '').split(/\r?\n/).map(l => l.trim()).filter(Boolean)
      batchItems.value = []
      batchProgress.current = 0
      batchProgress.total = lines.length
      batchProgress.completed = 0
      batchProgress.failed = 0
      selectedBatchIndex.value = -1

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i]
        const parts = line.split('|').map(p => p.trim())
        const text = parts[0] || ''
        const prompt = parts[1] || ''

        // 初始化该条目
        batchItems.value.push({
          index: i,
          text,
          prompt,
          status: 'running',
          error: '',
          original: '',
          transparent: '',
          preview: '',
          svg: '',
          metadata: null,
          stage1Ms: 0,
          stage2Ms: 0
        })
        batchProgress.current = i + 1

        try {
          // Stage 1: 生成位图
          const payloadA = { text, prompt, negative: payload.negative || '', resolution: payload.resolution, format: payload.format, seed: payload.seed }
          const t1 = Date.now()
          const respA = await generateArtBitmap(payloadA)
          const s1Ms = Date.now() - t1

          // Stage 2: 矢量化
          const payloadB = {
            source_type: 'generated', text, prompt,
            negative: payload.negative || '',
            resolution: payload.resolution, format: payload.format, seed: payload.seed,
            vector: { ...payload.vector },
            image_base64: respA.png,
            image_name: respA.image_name || `${safeName(text || 'batch')}-orig.png`
          }
          const t2 = Date.now()
          const respB = await vectorizeArtImage(payloadB)
          const s2Ms = Date.now() - t2

          // 更新条目结果
          const item = batchItems.value[i]
          item.status = 'success'
          item.original = respA.png || ''
          item.transparent = respB.transparent_png || ''
          item.preview = respB.preview_png || respB.png || ''
          item.svg = respB.svg || ''
          item.metadata = respB.metadata || null
          item.stage1Ms = s1Ms
          item.stage2Ms = s2Ms
          if (item.metadata) {
            item.metadata.generation = item.metadata.generation || {}
            item.metadata.generation.duration_ms = s1Ms
          }

          batchProgress.completed++

          // 自动选中最新成功的条目并展示结果
          selectedBatchIndex.value = i
          result.original = item.original
          result.transparent = item.transparent
          result.preview = item.preview
          result.image = item.preview
          result.svg = item.svg
          result.metadata = item.metadata
        } catch (itemErr) {
          // 单条失败不中断整批
          const item = batchItems.value[i]
          item.status = 'failed'
          item.error = itemErr?.message || '生成失败'
          batchProgress.failed++
        }
      }

      // 构建文件列表（汇总所有成功条目）
      const base = getFileNameBase()
      const files = []
      const successItems = batchItems.value.filter(b => b.status === 'success')
      successItems.forEach((b, idx) => {
        const suffix = successItems.length > 1 ? `_item${idx + 1}` : ''
        if (b.original) files.push({ key: `original${suffix}`, name: `${base}${suffix}_original.png`, data: b.original, isText: false })
        if (b.transparent) files.push({ key: `transparent${suffix}`, name: `${base}${suffix}_transparent.png`, data: b.transparent, isText: false })
        if (b.preview) files.push({ key: `preview${suffix}`, name: `${base}${suffix}_preview.png`, data: b.preview, isText: false })
        if (b.svg) files.push({ key: `svg${suffix}`, name: `${base}${suffix}_vector.svg`, data: b.svg, isText: true })
        if (b.metadata) files.push({ key: `metadata${suffix}`, name: `${base}${suffix}_metadata.json`, data: JSON.stringify(b.metadata, null, 2), isText: true })
      })
      const logText = `task_id=${task.id}\nmode=batch\ntotal=${lines.length}\ncompleted=${batchProgress.completed}\nfailed=${batchProgress.failed}\nstatus=completed`
      files.push({ key: 'log', name: `${base}_log.log`, data: logText, isText: true })
      currentFiles.value = files

      // 设置最终任务状态
      if (batchProgress.failed === lines.length) {
        task.status = '失败'
        error.value = '所有批量任务均失败。'
      } else if (batchProgress.failed > 0) {
        task.status = `部分完成（${batchProgress.completed}/${lines.length}）`
      } else {
        task.status = '完成'
      }
    }

    if (mode.value !== 'batch') {
      task.status = '完成'
    }

    // 持久化结果到 IndexedDB + 生成缩略图
    try {
      if (mode.value === 'batch') {
        const successItems = batchItems.value.filter(b => b.status === 'success')
        if (successItems.length > 0) {
          const lastItem = successItems[successItems.length - 1]
          task.thumb = await makeThumbnail(lastItem.preview || lastItem.original)
          await saveResultToDB(task.id, {
            batchMode: true,
            items: batchItems.value.map(b => ({
              index: b.index, text: b.text, prompt: b.prompt,
              status: b.status, error: b.error,
              original: b.original, transparent: b.transparent,
              preview: b.preview, svg: b.svg, metadata: b.metadata,
              stage1Ms: b.stage1Ms, stage2Ms: b.stage2Ms
            }))
          })
        }
      } else {
        task.thumb = await makeThumbnail(result.preview || result.original)
        await saveResultToDB(task.id, {
          original: result.original,
          transparent: result.transparent,
          preview: result.preview,
          svg: result.svg,
          metadata: result.metadata
        })
      }
    } catch (storageErr) {
      console.warn('结果持久化失败（不影响正常使用）:', storageErr)
    }

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
  result.preview = ''
  result.transparent = ''
  batchItems.value = []
  batchProgress.current = 0
  batchProgress.total = 0
  batchProgress.completed = 0
  batchProgress.failed = 0
  selectedBatchIndex.value = -1
}

const selectBatchItem = (index) => {
  const item = batchItems.value[index]
  if (!item || item.status !== 'success') return
  selectedBatchIndex.value = index
  result.original = item.original || ''
  result.transparent = item.transparent || ''
  result.preview = item.preview || ''
  result.image = item.preview || ''
  result.svg = item.svg || ''
  result.metadata = item.metadata || null
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

const deleteHistoryItem = async (id) => {
  logs.value = logs.value.filter((item) => item.id !== id)
  await deleteResultFromDB(id)
  saveHistory()
}

const restoreHistoryItem = async (id) => {
  const item = logs.value.find(l => l.id === id)
  if (!item || item.status === '运行中') return

  const saved = await loadResultFromDB(id)
  if (!saved) {
    error.value = '该记录的结果数据已丢失，无法恢复。'
    return
  }

  // 恢复批量模式
  if (saved.batchMode && saved.items) {
    mode.value = 'batch'
    batchItems.value = saved.items.map(b => ({ ...b }))
    batchProgress.total = saved.items.length
    batchProgress.completed = saved.items.filter(b => b.status === 'success').length
    batchProgress.failed = saved.items.filter(b => b.status === 'failed').length
    batchProgress.current = saved.items.length

    const lastSuccess = [...saved.items].reverse().find(b => b.status === 'success')
    if (lastSuccess) {
      selectedBatchIndex.value = lastSuccess.index
      result.original = lastSuccess.original || ''
      result.transparent = lastSuccess.transparent || ''
      result.preview = lastSuccess.preview || ''
      result.image = lastSuccess.preview || ''
      result.svg = lastSuccess.svg || ''
      result.metadata = lastSuccess.metadata || null
    }
  } else {
    // 恢复单条/矢量化模式
    mode.value = item.mode === '矢量化' ? 'vectorize' : 'single'
    result.original = saved.original || ''
    result.transparent = saved.transparent || ''
    result.preview = saved.preview || ''
    result.image = saved.preview || ''
    result.svg = saved.svg || ''
    result.metadata = saved.metadata || null
    batchItems.value = []
    selectedBatchIndex.value = -1
  }

  activeTab.value = 'output'
}
</script>
