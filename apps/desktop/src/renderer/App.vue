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
        <!-- 模型未下载提示 -->
        <div v-if="modelsSkipped || downloadingModels" class="gpu-warning" style="background: #fffbeb; color: #92400e; border: 1px solid #fcd34d;">
          <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
            <span>⚠️ AI 模型未下载，文生图使用本地降级引擎</span>
            <button
              v-if="!downloadingModels"
              type="button"
              @click="startModelDownload"
              style="padding:4px 12px;border-radius:6px;border:1px solid #f59e0b;background:#fef3c7;color:#92400e;cursor:pointer;font-size:12px;font-weight:600"
            >下载模型</button>
            <span v-else style="font-size:12px;color:#92400e;font-weight:600">
              下载中 {{ modelDownloadProgress.current || 0 }}/{{ modelDownloadProgress.total || '?' }}
            </span>
          </div>
          <div v-if="downloadingModels || modelDownloadProgress.message" style="margin-top:10px;display:grid;gap:6px">
            <div style="height:6px;background:#fde68a;border-radius:999px;overflow:hidden">
              <div :style="{ width: modelDownloadOverallPercent + '%', height: '100%', background: '#f59e0b', borderRadius: '999px', transition: 'width 0.25s ease' }"></div>
            </div>
            <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:12px;color:#92400e">
              <span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                {{ modelDownloadProgress.fileName || modelDownloadProgress.message || '准备下载模型...' }}
              </span>
              <span style="flex:none">{{ modelDownloadOverallPercent }}%</span>
            </div>
            <div v-if="modelDownloadProgress.filePercent >= 0" style="display:grid;gap:4px">
              <div style="height:4px;background:#fed7aa;border-radius:999px;overflow:hidden">
                <div :style="{ width: modelDownloadFilePercent + '%', height: '100%', background: '#ea580c', borderRadius: '999px', transition: 'width 0.25s ease' }"></div>
              </div>
              <div style="font-size:11px;color:#a16207">当前文件 {{ modelDownloadFilePercent }}%</div>
            </div>
            <div style="display:flex;gap:12px;flex-wrap:wrap;font-size:11px;color:#a16207">
              <span v-if="modelDownloadProgress.fileSize">大小 {{ modelDownloadProgress.fileSize }}</span>
              <span v-if="modelDownloadProgress.speed">速度 {{ modelDownloadProgress.speed }}</span>
              <span v-if="modelDownloadProgress.eta">剩余 {{ modelDownloadProgress.eta }}</span>
              <span v-if="modelDownloadProgress.result">{{ modelDownloadResultText }}</span>
            </div>
          </div>
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
          :stage-progress="stageProgress"
          @open-output-dir="openOutputDirectory"
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
        @delete-history="deleteHistoryItem"
        @restore-history="restoreHistoryItem"
      />
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, onMounted } from 'vue'
import GenerationForm from './components/GenerationForm.vue'
import ResultPanel from './components/ResultPanel.vue'
import HistoryPanel from './components/HistoryPanel.vue'
import VectorParams from './components/VectorParams.vue'
import { generateArtBitmap, openPath, prepareOutputTask, readOutputFile, deleteOutputDir, saveFile, saveResults, vectorizeArtImage, writeTaskArtifacts, getStartupStatus, downloadModels, onSplashProgress, removeSplashProgressListener } from './api'
import { makeThumbnail } from './utils/storage'

// 渲染进程中无法使用 Node.js path 模块，用纯字符串操作替代
const joinPath = (dir, file) => {
  if (!dir) return file
  // 处理 Windows (\\) 和 Unix (/) 两种分隔符
  const sep = dir.includes('\\') ? '\\' : '/'
  return dir.endsWith(sep) ? `${dir}${file}` : `${dir}${sep}${file}`
}
const basename = (p) => {
  if (!p) return ''
  // 同时兼容 Windows 和 Unix 路径分隔符
  const parts = p.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || ''
}

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

onMounted(async () => {
  detectGPU()
  // 仅在完全没有 GPU 时默认选择图片矢量化模式
  if (!hasUsableGpu.value) {
    mode.value = 'vectorize'
  }

  // 检查启动状态（生产打包模式）
  try {
    const status = await getStartupStatus()
    modelsSkipped.value = status.modelsSkipped || false
    modelsReady.value = status.modelsReady !== false // 默认 true（开发模式）
  } catch {
    // 开发模式或无此 API，静默忽略
  }
})

const activeTab = ref('input')

const vectorPresets = {
  clean: {
    preset: 'clean',
    color_precision: 2,
    filter_speckle: 48,
    corner_threshold: 120,
    length_threshold: 30,
    layer_difference: 38,
    scale: 2
  },
  balanced: {
    preset: 'balanced',
    color_precision: 4,
    filter_speckle: 18,
    corner_threshold: 70,
    length_threshold: 12,
    layer_difference: 20,
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
const HISTORY_DIR_KEY = 'art-text-generator-history-dirs'

const mode = ref('single')
const running = ref(false)
const error = ref('')
const modelsSkipped = ref(false)
const modelsReady = ref(true)
const downloadingModels = ref(false)
const modelDownloadProgress = reactive({
  current: 0,
  total: 0,
  fileName: '',
  fileSize: '',
  subdir: '',
  percent: 0,
  filePercent: -1,
  speed: '',
  eta: '',
  message: '',
  phase: '',
  result: null
})
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

const clampPercent = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n) || n < 0) return -1
  return Math.min(100, Math.max(0, Math.round(n)))
}

const resetModelDownloadProgress = () => {
  modelDownloadProgress.current = 0
  modelDownloadProgress.total = 0
  modelDownloadProgress.fileName = ''
  modelDownloadProgress.fileSize = ''
  modelDownloadProgress.subdir = ''
  modelDownloadProgress.percent = 0
  modelDownloadProgress.filePercent = -1
  modelDownloadProgress.speed = ''
  modelDownloadProgress.eta = ''
  modelDownloadProgress.message = ''
  modelDownloadProgress.phase = ''
  modelDownloadProgress.result = null
}

const modelDownloadOverallPercent = computed(() => {
  const direct = clampPercent(modelDownloadProgress.percent)
  if (direct >= 0) return direct
  if (modelDownloadProgress.total > 0) {
    return clampPercent((modelDownloadProgress.current / modelDownloadProgress.total) * 100)
  }
  return 0
})

const modelDownloadFilePercent = computed(() => {
  const direct = clampPercent(modelDownloadProgress.filePercent)
  return direct >= 0 ? direct : 0
})

const modelDownloadResultText = computed(() => {
  const result = modelDownloadProgress.result
  if (!result) return ''
  return `${result.ok || 0} 成功，${result.skip || 0} 跳过，${result.fail || 0} 失败`
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

// 阶段进度（单条/矢量化模式的生成过程）
const stageProgress = reactive({
  stage1: { active: false, percent: 0 },
  stage2: { active: false, percent: 0 }
})
let progressTimer = null

const currentFiles = ref([])
const currentTaskDir = ref('')
const currentOutputRoot = ref('')
const currentTaskPaths = ref(null)

const logs = ref(loadHistory())

const historyDirs = ref(loadHistoryDirs())

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
  } catch {
    return []
  }
}

function loadHistoryDirs() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_DIR_KEY) || '{}')
  } catch {
    return {}
  }
}

function saveHistory() {
  const trimmed = logs.value.slice(0, 50)
  localStorage.setItem(HISTORY_KEY, JSON.stringify(trimmed))
  localStorage.setItem(HISTORY_DIR_KEY, JSON.stringify(historyDirs.value || {}))
}

function setHistoryDir(id, payload) {
  historyDirs.value = { ...historyDirs.value, [String(id)]: payload }
  localStorage.setItem(HISTORY_DIR_KEY, JSON.stringify(historyDirs.value))
}

function getHistoryDir(id) {
  return historyDirs.value?.[String(id)] || null
}

function deleteHistoryDir(id) {
  const next = { ...historyDirs.value }
  delete next[String(id)]
  historyDirs.value = next
  localStorage.setItem(HISTORY_DIR_KEY, JSON.stringify(next))
}

// 仅写入 localStorage：历史记录列表 + 任务目录映射
function persistHistory() {
  saveHistory()
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

// ── 阶段进度管理（时间估算，每 100ms 刷新） ──

function resetStageProgress() {
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null }
  stageProgress.stage1.active = false; stageProgress.stage1.percent = 0
  stageProgress.stage2.active = false; stageProgress.stage2.percent = 0
}

function startStageProgress(stage) {
  const sp = stageProgress[stage]
  sp.active = true
  sp.percent = 0
  const startTime = Date.now()
  // 对数曲线：前期较快，后期越来越慢，自然趋近 99% 但不会到
  // 约 15s → 62%，约 25s → 85%，约 40s → 96%
  progressTimer = setInterval(() => {
    const elapsed = Date.now() - startTime
    const t = elapsed / 1000 // 秒
    sp.percent = Math.min(99, Math.round(99 * Math.log(1 + t / 10) / Math.log(5)))
  }, 100)
}

function finishStageProgress(stage) {
  if (progressTimer) { clearInterval(progressTimer); progressTimer = null }
  const sp = stageProgress[stage]
  sp.percent = 100
  // 短暂显示 100% 后关闭
  setTimeout(() => { sp.active = false }, 600)
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
  currentTaskDir.value = ''
  currentOutputRoot.value = ''
  currentTaskPaths.value = null
  resetStageProgress()
  batchItems.value = []
  batchProgress.current = 0
  batchProgress.total = 0
  batchProgress.completed = 0
  batchProgress.failed = 0
  selectedBatchIndex.value = -1

  const taskTitle = mode.value === 'single' ? payload.text.trim() : mode.value === 'batch' ? '批量任务' : '图片矢量化'
  const taskStartedAt = new Date().toISOString()
  const task = {
    id: Date.now(),
    title: taskTitle,
    startedAt: taskStartedAt,
    time: new Date(taskStartedAt).toLocaleTimeString('zh-CN', { hour12: false }),
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
    let taskInfo = null

    // 准备上传图片（仅在 vectorize 模式）
    if (mode.value === 'vectorize' && payload.imageFile) {
      imageBase64 = await fileToDataUrl(payload.imageFile)
      imageName = payload.imageFile.name
      result.original = imageBase64
      taskInfo = await prepareOutputTask({ mode: 'vectorize', index: 1, text: stripExtension(imageName) || 'uploaded-image', seed: payload.seed, startedAt: taskStartedAt, usesTxt2Img: false })
      await writeTaskArtifacts({
        outputRoot: taskInfo.outputRoot,
        taskDir: taskInfo.taskDir,
        taskName: taskInfo.taskName,
        paths: taskInfo.paths,
        artifacts: { original: imageBase64 },
        metadata: null,
        runLog: buildRunLog({ task, taskInfo, modeName: 'vectorize', seed: payload.seed, status: 'vectorizing', usesTxt2Img: false }),
        usesTxt2Img: false
      })
      currentTaskDir.value = taskInfo.taskDir
      currentOutputRoot.value = taskInfo.outputRoot
      currentTaskPaths.value = taskInfo.paths
    }

    if (mode.value === 'single') {
      // Stage 1: 生成位图（后端 A）
      startStageProgress('stage1')
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
      finishStageProgress('stage1')

      const workflowArtifactsData = {
        workflowApi: respA.workflow_api || null,
        modelDependencies: respA.model_dependencies || null,
      }

      taskInfo = await prepareOutputTask({ mode: 'single', index: 1, text: payload.text.trim(), seed: payload.seed, startedAt: taskStartedAt, usesTxt2Img: true })
      const stage1Engine = respA.metadata?.engine || ''
      await writeTaskArtifacts({
        outputRoot: taskInfo.outputRoot,
        taskDir: taskInfo.taskDir,
        taskName: taskInfo.taskName,
        paths: taskInfo.paths,
        artifacts: { original: imageBase64 },
        metadata: null,
        runLog: buildRunLog({ task, taskInfo, modeName: 'single', text: payload.text.trim(), prompt: payload.prompt.trim(), seed: payload.seed, stage1Duration, status: 'vectorizing', usesTxt2Img: true, engine: stage1Engine }),
        usesTxt2Img: true,
        workflowArtifacts: workflowArtifactsData
      })
      currentTaskDir.value = taskInfo.taskDir
      currentOutputRoot.value = taskInfo.outputRoot
      currentTaskPaths.value = taskInfo.paths

      // Stage 2: 矢量化（后端 B）
      startStageProgress('stage2')
      const payloadB = {
        source_type: 'generated',
        text: payload.text.trim(),
        prompt: payload.prompt.trim(),
        negative: payload.negative.trim(),
        resolution: payload.resolution,
        format: payload.format,
        seed: payload.seed,
        vector: { ...payload.vector },
        __timeoutMs: 120000,
        generated_image: { file_path: taskInfo.paths.original },
        image_base64: taskInfo?.paths?.original ? undefined : imageBase64,
        image_name: imageName
      }
      const t2 = Date.now()
      const vectorized = await vectorizeWithPathFallback(payloadB, imageBase64)
      const respB = vectorized.response
      stage2Duration = Date.now() - t2

      result.transparent = respB.transparent_png || ''
      result.preview = respB.preview_png || respB.png || ''
      result.image = result.preview
      result.svg = respB.svg || ''
      result.metadata = respB.metadata || null
      finishStageProgress('stage2')

      // 将生成耗时写入 metadata
      if (result.metadata) {
        result.metadata.generation = result.metadata.generation || {}
        result.metadata.generation.duration_ms = stage1Duration
      }

      // 构建文件列表
      const finalMetadata = augmentMetadata(result.metadata, { task, taskInfo, modeName: 'single', text: payload.text.trim(), prompt: payload.prompt.trim(), seed: payload.seed, usesTxt2Img: true })
      result.metadata = finalMetadata
      const stage1Status = resolveStatus(respA.metadata)
      const runLog = buildRunLog({ task, taskInfo, modeName: 'single', text: payload.text.trim(), prompt: payload.prompt.trim(), seed: payload.seed, stage1Duration, stage2Duration, status: stage1Status, usesTxt2Img: true, engine: stage1Engine })
      const writeResult = await writeCurrentTask({
        task,
        taskInfo,
        artifacts: { original: imageBase64, transparent: result.transparent, preview: result.preview, svg: result.svg },
        metadata: finalMetadata,
        runLog,
        usesTxt2Img: true,
        workflowArtifacts: workflowArtifactsData
      })
      currentFiles.value = Object.entries(writeResult.paths || {}).map(([key, value]) => ({ key, name: value, data: value, isPath: true }))

    } else if (mode.value === 'vectorize') {
      // 直接调用后端 B
      startStageProgress('stage2')
      const payloadB = {
        source_type: 'upload',
        resolution: payload.resolution,
        format: payload.format,
        seed: payload.seed,
        vector: { ...payload.vector },
        __timeoutMs: 120000,
        image_path: taskInfo?.paths?.original,
        image_base64: taskInfo?.paths?.original ? undefined : imageBase64,
        image_name: imageName
      }
      const t2 = Date.now()
      const vectorized = await vectorizeWithPathFallback(payloadB, imageBase64)
      const respB = vectorized.response
      stage2Duration = Date.now() - t2

      result.transparent = respB.transparent_png || ''
      result.preview = respB.preview_png || respB.png || ''
      result.image = result.preview
      result.svg = respB.svg || ''
      result.metadata = respB.metadata || null
      finishStageProgress('stage2')

      const finalMetadata = augmentMetadata(result.metadata, { task, taskInfo, modeName: 'vectorize', seed: payload.seed, usesTxt2Img: false })
      result.metadata = finalMetadata
      const runLog = buildRunLog({ task, taskInfo, modeName: 'vectorize', seed: payload.seed, stage2Duration, status: 'success', usesTxt2Img: false, engine: '' })
      const writeResult = await writeCurrentTask({
        task,
        taskInfo,
        artifacts: { original: result.original, transparent: result.transparent, preview: result.preview, svg: result.svg },
        metadata: finalMetadata,
        runLog,
        usesTxt2Img: false
      })
      currentFiles.value = Object.entries(writeResult.paths || {}).map(([key, value]) => ({ key, name: value, data: value, isPath: true }))

    } else if (mode.value === 'batch') {
      // 批量处理：逐条执行，支持进度展示和单条错误容错
      const lines = String(payload.batch || '').split(/\r?\n/).map(l => l.trim()).filter(Boolean)
      batchItems.value = []
      batchProgress.current = 0
      batchProgress.total = lines.length
      batchProgress.completed = 0
      batchProgress.failed = 0
      selectedBatchIndex.value = -1

      const batchTaskInfo = await prepareOutputTask({ mode: 'batch-batch', index: 0, text: 'batch-run', seed: payload.seed, startedAt: taskStartedAt, usesTxt2Img: false })
      const batchSummaryDir = batchTaskInfo.taskDir
      currentTaskDir.value = batchTaskInfo.taskDir
      currentOutputRoot.value = batchTaskInfo.outputRoot
      currentTaskPaths.value = { ...batchTaskInfo.paths, summary: joinPath(batchSummaryDir, 'batch_summary.csv') }
      const batchSummaryPath = joinPath(batchSummaryDir, 'batch_summary.csv')

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
          const batchWorkflowArtifacts = {
            workflowApi: respA.workflow_api || null,
            modelDependencies: respA.model_dependencies || null,
          }
          const itemTaskInfo = await prepareOutputTask({ mode: 'batch', index: i + 1, text: text || `item-${i + 1}`, seed: payload.seed, startedAt: taskStartedAt, usesTxt2Img: true, summaryDir: batchSummaryDir })
          const batchEngine = respA.metadata?.engine || ''
          await writeTaskArtifacts({
            outputRoot: itemTaskInfo.outputRoot,
            taskDir: itemTaskInfo.taskDir,
            taskName: itemTaskInfo.taskName,
            paths: itemTaskInfo.paths,
            artifacts: { original: respA.png },
            metadata: null,
            runLog: buildRunLog({ task, taskInfo: itemTaskInfo, modeName: 'batch', text, prompt, seed: payload.seed, stage1Duration: s1Ms, status: 'vectorizing', usesTxt2Img: true, engine: batchEngine }),
            usesTxt2Img: true,
            workflowArtifacts: batchWorkflowArtifacts
          })

          // Stage 2: 矢量化
          const payloadB = {
            source_type: 'generated', text, prompt,
            negative: payload.negative || '',
            resolution: payload.resolution, format: payload.format, seed: payload.seed,
            vector: { ...payload.vector },
            __timeoutMs: 120000,
            generated_image: { file_path: itemTaskInfo.paths.original },
            image_base64: itemTaskInfo?.paths?.original ? undefined : respA.png,
            image_name: respA.image_name || `${safeName(text || 'batch')}-orig.png`
          }
          const t2 = Date.now()
          const vectorized = await vectorizeWithPathFallback(payloadB, respA.png)
          const respB = vectorized.response
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
          item.taskDir = itemTaskInfo.taskDir
          item.outputRoot = itemTaskInfo.outputRoot
          item.taskName = itemTaskInfo.taskName
          item.paths = itemTaskInfo.paths
          if (item.metadata) {
            item.metadata.generation = item.metadata.generation || {}
            item.metadata.generation.duration_ms = s1Ms
          }
          const batchStatus = resolveStatus(respA.metadata)
          item.metadata = augmentMetadata(item.metadata, { task, taskInfo: itemTaskInfo, modeName: 'batch', text, prompt, seed: payload.seed, usesTxt2Img: true })
          await writeTaskArtifacts({
            outputRoot: itemTaskInfo.outputRoot,
            taskDir: itemTaskInfo.taskDir,
            taskName: itemTaskInfo.taskName,
            paths: itemTaskInfo.paths,
            artifacts: { original: item.original, transparent: item.transparent, preview: item.preview, svg: item.svg },
            metadata: item.metadata,
            runLog: buildRunLog({ task, taskInfo: itemTaskInfo, modeName: 'batch', text, prompt, seed: payload.seed, stage1Duration: s1Ms, stage2Duration: s2Ms, status: batchStatus, usesTxt2Img: true, engine: batchEngine }),
            usesTxt2Img: true,
            summaryRow: { ...buildSummaryRow({ task, taskInfo: itemTaskInfo, modeName: 'batch', status: batchStatus, text, prompt, seed: payload.seed }), summary_path: batchSummaryPath },
            workflowArtifacts: batchWorkflowArtifacts
          })

          batchProgress.completed++

          // 自动选中最新成功的条目并展示结果
          selectedBatchIndex.value = i
          result.original = item.original
          result.transparent = item.transparent
          result.preview = item.preview
          result.image = item.preview
          result.svg = item.svg
          result.metadata = item.metadata
          currentTaskDir.value = item.taskDir || ''
          currentOutputRoot.value = item.outputRoot || ''
          currentTaskPaths.value = item.paths || null
        } catch (itemErr) {
          // 单条失败不中断整批
          const item = batchItems.value[i]
          item.status = 'failed'
          item.error = itemErr?.message || '生成失败'
          if (item.taskDir) {
            const failedInfo = { taskDir: item.taskDir, outputRoot: item.outputRoot, taskName: item.taskName, paths: { ...item.paths, summary: batchSummaryPath, summaryDir: batchSummaryDir } }
            await writeFailedTask({
              task,
              taskInfo: failedInfo,
              modeName: 'batch',
              text,
              prompt,
              seed: payload.seed,
              errorMessage: item.error,
              usesTxt2Img: true,
              stage1Duration: item.stage1Ms || 0,
              stage2Duration: item.stage2Ms || 0
            })
          }
          batchProgress.failed++
        }
      }

      // 构建文件列表（汇总所有成功条目的任务目录）
      const files = []
      const successItems = batchItems.value.filter(b => b.status === 'success')
      successItems.forEach((b, idx) => {
        files.push({ key: `task${idx + 1}`, name: b.taskName || `task_${idx + 1}`, data: b.taskDir || '', isPath: true })
      })
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

    // 持久化任务目录路径到 localStorage + IndexedDB（双保险）
    // 任务目录是真正的产物源；历史恢复时直接从文件读取即可。
    try {
      console.log('[save] currentTaskDir=', currentTaskDir.value, 'paths=', currentTaskPaths.value)
      let dirRecord = null
      if (mode.value === 'batch') {
        const successItems = batchItems.value.filter(b => b.status === 'success')
        if (successItems.length > 0) {
          const lastItem = successItems[successItems.length - 1]
          task.thumb = await makeThumbnail(lastItem.preview || lastItem.original)
          dirRecord = {
            taskDir: currentTaskDir.value,
            outputRoot: currentOutputRoot.value,
            taskName: task.taskName || (currentTaskDir.value ? basename(currentTaskDir.value) : ''),
            paths: currentTaskPaths.value,
            inputParams: {
              mode: 'batch',
              batch: payload.batch,
              negative: payload.negative,
              resolution: payload.resolution,
              format: payload.format,
              seed: payload.seed,
              vector: JSON.parse(JSON.stringify(payload.vector))
            }
          }
        }
      } else {
        task.thumb = await makeThumbnail(result.preview || result.original)
        dirRecord = {
          taskDir: currentTaskDir.value,
          outputRoot: currentOutputRoot.value,
          taskName: task.taskName || (currentTaskDir.value ? basename(currentTaskDir.value) : ''),
          paths: currentTaskPaths.value,
          inputParams: {
            mode: mode.value,
            text: payload.text,
            prompt: payload.prompt,
            negative: payload.negative,
            resolution: payload.resolution,
            format: payload.format,
            seed: payload.seed,
            vector: JSON.parse(JSON.stringify(payload.vector))
          }
        }
      }

      if (dirRecord && dirRecord.taskDir && dirRecord.paths) {
        setHistoryDir(task.id, dirRecord)
      } else {
        console.warn('[save] 跳过持久化：taskDir 或 paths 为空')
      }
    } catch (storageErr) {
      console.error('结果持久化失败:', storageErr)
      error.value = `结果保存失败: ${storageErr.message}`
    }

    persistHistory()
  } catch (err) {
    error.value = err?.message || '生成失败，请稍后重试。'
    task.status = '失败'
    try {
      await writeFailedTask({
        task,
        taskInfo,
        modeName: mode.value,
        text: payload.text,
        prompt: payload.prompt,
        seed: payload.seed,
        errorMessage: error.value,
        usesTxt2Img: mode.value !== 'vectorize',
        stage1Duration,
        stage2Duration
      })
    } catch (logErr) {
      console.error('失败日志写入失败:', logErr)
    }
    saveHistory()
  } finally {
    running.value = false
    // 如果异常退出，确保进度条关闭
    if (progressTimer) { clearInterval(progressTimer); progressTimer = null }
  }
}

const fileToDataUrl = (file) =>
  new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(new Error('图片读取失败，请重试'))
    reader.readAsDataURL(file)
  })

const pathToDataUrl = async (filePath, mime = 'image/png') => {
  if (!filePath) return ''
  try {
    return await readOutputFile({ filePath, encoding: 'dataUrl', mime })
  } catch (err) {
    console.warn('读取本地文件失败:', err)
    return ''
  }
}

const readTextPath = async (filePath) => {
  if (!filePath) return ''
  try {
    return await readOutputFile({ filePath, encoding: 'text' })
  } catch (err) {
    console.warn('读取本地文本失败:', err)
    return ''
  }
}

const resolveStatus = (metadata) => {
  if (!metadata) return 'success'
  if (metadata.engine === 'local-studio') return 'stub'
  if (metadata.fallback_tier > 0) return 'degraded'
  return 'success'
}

const buildRunLog = ({ task, taskInfo, modeName, text = '', prompt = '', seed = 0, stage1Duration = 0, stage2Duration = 0, status = 'success', error = '', usesTxt2Img = false, engine = '' }) => {
  const paths = taskInfo?.paths || {}
  return [
    `task_id=${task?.id || ''}`,
    `task_name=${taskInfo?.taskName || ''}`,
    `mode=${modeName}`,
    `text=${text}`,
    `prompt=${prompt}`,
    `seed=${seed}`,
    `stage1_ms=${stage1Duration}`,
    `stage2_ms=${stage2Duration}`,
    `uses_txt2img=${usesTxt2Img}`,
    `engine=${engine}`,
    `task_dir=${taskInfo?.taskDir || ''}`,
    `original_path=${paths.original || ''}`,
    `transparent_path=${paths.transparent || ''}`,
    `result_svg_path=${paths.svg || ''}`,
    `preview_path=${paths.preview || ''}`,
    `metadata_path=${paths.metadata || ''}`,
    `status=${status}`,
    error ? `error=${error}` : ''
  ].filter(Boolean).join('\n')
}

const augmentMetadata = (metadata, { task, taskInfo, modeName, text = '', prompt = '', seed = 0, usesTxt2Img = false }) => ({
  ...(metadata || {}),
  schema_version: metadata?.schema_version || 1,
  task_id: String(task?.id || ''),
  task_name: taskInfo?.taskName || '',
  mode: modeName,
  output_dir: taskInfo?.taskDir || '',
  generation: {
    ...(metadata?.generation || {}),
    text: metadata?.generation?.text || text,
    prompt: metadata?.generation?.prompt || prompt,
    seed: metadata?.generation?.seed ?? seed
  },
  paths: taskInfo?.paths
    ? {
        original: taskInfo.paths.original,
        transparent: taskInfo.paths.transparent,
        svg: taskInfo.paths.svg,
        preview: taskInfo.paths.preview,
        metadata: taskInfo.paths.metadata,
        log: taskInfo.paths.log
      }
    : {
        original: 'original.png',
        transparent: 'transparent.png',
        svg: 'result.svg',
        preview: 'preview.png',
        metadata: 'metadata.json',
        log: 'run.log'
      },
  workflow_paths: usesTxt2Img
    ? {
        workflow_api: 'workflows/workflow_api.json',
        nodes: 'workflows/nodes.md',
        model_dependencies: 'workflows/model_dependencies.json'
      }
    : null
})

const writeCurrentTask = async ({ task, taskInfo, artifacts, metadata, runLog, usesTxt2Img, summaryRow, workflowArtifacts }) => {
  const writeResult = await writeTaskArtifacts({
    outputRoot: taskInfo.outputRoot,
    taskDir: taskInfo.taskDir,
    taskName: taskInfo.taskName,
    paths: taskInfo.paths,
    artifacts,
    metadata,
    runLog,
    usesTxt2Img,
    summaryRow,
    workflowArtifacts
  })
  currentTaskDir.value = writeResult.taskDir
  currentOutputRoot.value = writeResult.outputRoot
  currentTaskPaths.value = writeResult.paths
  task.outputDir = writeResult.outputRoot
  task.taskDir = writeResult.taskDir
  task.taskName = writeResult.taskName
  task.summaryPath = writeResult.paths?.summary
  return writeResult
}

const vectorizeWithPathFallback = async (payloadB, fallbackImageBase64) => {
  try {
    const response = await vectorizeArtImage(payloadB)
    return { response, usedFallback: false, pathError: '' }
  } catch (pathErr) {
    if (!fallbackImageBase64) throw pathErr

    console.warn('[vectorize] 路径通信失败，回退到 base64：', pathErr)
    const fallbackPayload = {
      ...payloadB,
      image_path: undefined,
      generated_image: undefined,
      image_base64: fallbackImageBase64
    }
    const response = await vectorizeArtImage(fallbackPayload)
    return { response, usedFallback: true, pathError: pathErr?.message || String(pathErr) }
  }
}

const writeFailedTask = async ({ task, taskInfo, modeName, text = '', prompt = '', seed = 0, errorMessage = '', usesTxt2Img = false, stage1Duration = 0, stage2Duration = 0 }) => {
  if (!taskInfo) return
  const metadata = augmentMetadata({ error: errorMessage }, { task, taskInfo, modeName, text, prompt, seed, usesTxt2Img })
  const summaryTarget = modeName === 'batch' ? taskInfo?.paths?.summary : null
  await writeTaskArtifacts({
    outputRoot: taskInfo.outputRoot,
    taskDir: taskInfo.taskDir,
    taskName: taskInfo.taskName,
    paths: taskInfo.paths,
    artifacts: {},
    metadata,
    runLog: buildRunLog({ task, taskInfo, modeName, text, prompt, seed, stage1Duration, stage2Duration, status: 'failed', error: errorMessage, usesTxt2Img }),
    usesTxt2Img,
    summaryRow: { ...buildSummaryRow({ task, taskInfo, modeName, status: 'failed', text, prompt, seed, error: errorMessage }), summary_path: summaryTarget }
  })
}

const buildSummaryRow = ({ task, taskInfo, modeName, status = 'success', text = '', prompt = '', seed = 0, error = '' }) => ({
  task_id: String(task?.id || ''),
  task_name: taskInfo?.taskName || '',
  mode: modeName,
  status,
  text,
  prompt,
  seed,
  resolution: payload.resolution,
  task_dir: taskInfo?.taskDir || '',
  original_path: taskInfo?.paths?.original || '',
  transparent_path: taskInfo?.paths?.transparent || '',
  result_svg_path: taskInfo?.paths?.svg || '',
  preview_path: taskInfo?.paths?.preview || '',
  metadata_path: taskInfo?.paths?.metadata || '',
  run_log_path: taskInfo?.paths?.log || '',
  error
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
  currentTaskDir.value = ''
  currentOutputRoot.value = ''
  currentTaskPaths.value = null
  batchItems.value = []
  batchProgress.current = 0
  batchProgress.total = 0
  batchProgress.completed = 0
  batchProgress.failed = 0
  selectedBatchIndex.value = -1
  resetStageProgress()
}

// ── 模型下载（主窗口触发） ──

const startModelDownload = async () => {
  if (downloadingModels.value) return
  downloadingModels.value = true
  error.value = ''
  resetModelDownloadProgress()

  try {
    onSplashProgress((data) => {
      if (!data || typeof data !== 'object') return

      if (data.phase) modelDownloadProgress.phase = data.phase
      if (data.message) modelDownloadProgress.message = data.message
      if (data.fileIndex !== undefined) modelDownloadProgress.current = data.fileIndex || 0
      if (data.totalFiles !== undefined) modelDownloadProgress.total = data.totalFiles || 0
      if (data.fileName !== undefined) modelDownloadProgress.fileName = data.fileName || ''
      if (data.fileSize !== undefined) modelDownloadProgress.fileSize = data.fileSize || ''
      if (data.subdir !== undefined) modelDownloadProgress.subdir = data.subdir || ''
      if (data.percent !== undefined) modelDownloadProgress.percent = clampPercent(data.percent)
      if (data.filePercent !== undefined) modelDownloadProgress.filePercent = clampPercent(data.filePercent)
      if (data.speed !== undefined) modelDownloadProgress.speed = data.speed || ''
      if (data.eta !== undefined) modelDownloadProgress.eta = data.eta || ''
      if (data.result) modelDownloadProgress.result = data.result

      if (data.phase === 'downloading') {
        modelDownloadProgress.current = data.fileIndex || modelDownloadProgress.current
      } else if (data.phase === 'complete') {
        modelDownloadProgress.percent = 100
        if (modelDownloadProgress.total > 0) {
          modelDownloadProgress.current = modelDownloadProgress.total
        }
      }
    })

    const result = await downloadModels()
    if (result) modelDownloadProgress.result = result
    const failed = Number(result?.fail || 0)
    modelsSkipped.value = failed > 0
    modelsReady.value = failed === 0
    error.value = ''
  } catch (err) {
    modelDownloadProgress.phase = 'error'
    modelDownloadProgress.message = err?.message || '模型下载失败'
    error.value = `模型下载失败: ${err.message}`
  } finally {
    downloadingModels.value = false
    removeSplashProgressListener()
  }
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
  currentTaskDir.value = item.taskDir || ''
  currentOutputRoot.value = item.outputRoot || ''
  currentTaskPaths.value = item.paths || null
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

const openOutputDirectory = async () => {
  if (currentTaskDir.value) {
    await openPath(currentTaskDir.value)
    return
  }

  if (!result.original && !result.transparent && !result.preview && !result.svg && !result.metadata) {
    error.value = '当前没有可打开的输出目录。'
    return
  }

  try {
    const fallbackTask = { id: Date.now() }
    const taskInfo = await prepareOutputTask({ mode: mode.value, index: 1, text: payload.text || getFileNameBase(), seed: payload.seed, startedAt: new Date().toISOString(), usesTxt2Img: mode.value !== 'vectorize' })
    const metadata = augmentMetadata(result.metadata || {}, { task: fallbackTask, taskInfo, modeName: mode.value, text: payload.text, prompt: payload.prompt, seed: payload.seed, usesTxt2Img: mode.value !== 'vectorize' })
    const writeResult = await writeTaskArtifacts({
      outputRoot: taskInfo.outputRoot,
      taskDir: taskInfo.taskDir,
      taskName: taskInfo.taskName,
      paths: taskInfo.paths,
      artifacts: { original: result.original, transparent: result.transparent, preview: result.preview || result.image, svg: result.svg },
      metadata,
      runLog: buildRunLog({ task: fallbackTask, taskInfo, modeName: mode.value, text: payload.text, prompt: payload.prompt, seed: payload.seed, status: 'restored-export', usesTxt2Img: mode.value !== 'vectorize' }),
      usesTxt2Img: mode.value !== 'vectorize',
      summaryRow: buildSummaryRow({ task: fallbackTask, taskInfo, modeName: mode.value, status: 'restored-export', text: payload.text, prompt: payload.prompt, seed: payload.seed })
    })
    currentTaskDir.value = writeResult.taskDir
    currentOutputRoot.value = writeResult.outputRoot
    currentTaskPaths.value = writeResult.paths
    await openPath(writeResult.taskDir)
  } catch (err) {
    error.value = err?.message || '打开输出目录失败。'
  }
}

const deleteHistoryItem = async (id) => {
  const item = logs.value.find(l => l.id === id)
  // 删除任务输出目录（如果存在）
  const dirInfo = getHistoryDir(id)
  const targetDir = dirInfo?.taskDir || item?.taskDir || null
  if (targetDir) {
    try {
      await deleteOutputDir(targetDir)
    } catch (err) {
      console.warn('[history] 删除任务目录失败:', err)
    }
  }
  logs.value = logs.value.filter((entry) => entry.id !== id)
  deleteHistoryDir(id)
  persistHistory()
}

const restoreHistoryItem = async (id) => {
  const item = logs.value.find(l => l.id === id)
  if (!item || item.status === '运行中') return

  const saved = getHistoryDir(id)
  if (!saved || !saved.taskDir || !saved.paths) {
    error.value = '该记录的结果数据已丢失，请重新生成。'
    return
  }

  const restoredMode = saved.inputParams?.mode || (item.mode === '矢量化' ? 'vectorize' : 'single')

  // 新数据：{ taskDir, paths, inputParams } —— 任务目录是真正的产物源
  if (saved.taskDir && saved.paths) {
    try {
      mode.value = restoredMode === 'vectorize' ? 'vectorize' : restoredMode === 'batch' ? 'batch' : 'single'
      result.original = await pathToDataUrl(saved.paths.original)
      result.transparent = await pathToDataUrl(saved.paths.transparent)
      result.preview = await pathToDataUrl(saved.paths.preview)
      result.image = result.preview
      result.svg = await readTextPath(saved.paths.svg)
      const metadataText = await readTextPath(saved.paths.metadata)
      result.metadata = metadataText ? safeJsonParse(metadataText) : null

      currentTaskDir.value = saved.taskDir
      currentOutputRoot.value = saved.outputRoot || ''
      currentTaskPaths.value = saved.paths

      applyInputParamsToForm(saved.inputParams, restoredMode)
      activeTab.value = 'output'
      return
    } catch (err) {
      error.value = `恢复失败：${err?.message || '任务目录文件无法访问'}`
      return
    }
  }

  // 兜底（极少见）：老历史记录里仍有 base64 缓存 —— 把缓存填回 result，但任务目录不可用
  if (saved.original || saved.transparent || saved.preview || saved.svg) {
    mode.value = restoredMode === 'vectorize' ? 'vectorize' : restoredMode === 'batch' ? 'batch' : 'single'
    result.original = saved.original || ''
    result.transparent = saved.transparent || ''
    result.preview = saved.preview || ''
    result.image = result.preview
    result.svg = saved.svg || ''
    result.metadata = saved.metadata || null
    currentTaskDir.value = ''
    currentTaskPaths.value = null
    applyInputParamsToForm(saved.inputParams, restoredMode)
    activeTab.value = 'output'
    return
  }

  error.value = '该记录的结果数据已丢失，请重新生成。'
}

const applyInputParamsToForm = (inputParams, mode) => {
  if (!inputParams) return
  if (mode === 'batch') {
    payload.batch = inputParams.batch || ''
    payload.negative = inputParams.negative || ''
    payload.resolution = inputParams.resolution || '1024 x 1024'
    payload.format = inputParams.format || 'PNG'
    payload.seed = inputParams.seed || 0
  } else {
    payload.text = inputParams.text || ''
    payload.prompt = inputParams.prompt || ''
    payload.negative = inputParams.negative || ''
    payload.resolution = inputParams.resolution || '1024 x 1024'
    payload.format = inputParams.format || 'PNG'
    payload.seed = inputParams.seed || 0
  }
  if (inputParams.vector) {
    Object.assign(payload.vector, inputParams.vector)
  }
}

const safeJsonParse = (text) => {
  try { return JSON.parse(text) } catch { return null }
}
</script>
