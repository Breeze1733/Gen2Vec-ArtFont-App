<template>
  <div class="app-shell">
    <header class="hero">
      <div class="hero-content">
        <h1>矢量艺术字生成器</h1>
        <div class="hero-tabs">
          <button
            :class="['tab-button', { active: activeTab === 'input' }]"
            type="button"
            @click="switchTab('input')"
          >
            输入面板
          </button>
          <button
            :class="['tab-button', { active: activeTab === 'output' }]"
            type="button"
            @click="switchTab('output')"
          >
            输出面板
          </button>
          <button
            :class="['tab-button', { active: activeTab === 'history' }]"
            type="button"
            @click="switchTab('history')"
          >
            历史任务
          </button>
          <button
            class="tab-button"
            type="button"
            @click="handleAcceptanceTest"
          >
            验收测试
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
import { generateArtBitmap, openPath, parseBatchInput, prepareOutputTask, readOutputFile, deleteOutputDir, saveFile, saveResults, scanFsHistory, vectorizeArtImage, writeTaskArtifacts, getStartupStatus, downloadModels, launchAcceptanceTest, onSplashProgress, removeSplashProgressListener } from './api'
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
const dirname = (p) => {
  if (!p) return ''
  const slash = Math.max(p.lastIndexOf('/'), p.lastIndexOf('\\'))
  return slash >= 0 ? p.slice(0, slash) : ''
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

  // 启动时扫描文件系统历史（合并 CLI 产生的任务）
  await mergeFsHistory()
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
    color_precision: 6,
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

const handleAcceptanceTest = async () => {
  try {
    await launchAcceptanceTest()
  } catch (err) {
    console.error('启动验收测试失败:', err)
  }
}

const switchTab = async (tab) => {
  activeTab.value = tab
  if (tab === 'history') {
    await mergeFsHistory()
  }
}

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

// ── 文件系统历史扫描与合并 ──

/**
 * 扫描文件系统中的 tasks-index.json，将 CLI 等外部工具产生的任务
 * 合并到 localStorage 历史列表中。
 */
async function mergeFsHistory() {
  try {
    const fsEntries = await scanFsHistory()
    if (!fsEntries || !Array.isArray(fsEntries) || fsEntries.length === 0) return

    const existingIds = new Set(logs.value.map(l => String(l.id)))
    const existingDirIds = new Set(
      Object.values(historyDirs.value).map(d => d.taskDir).filter(Boolean)
    )
    let added = 0

    for (const entry of fsEntries) {
      // 跳过已存在的
      if (existingIds.has(String(entry.id))) continue
      if (existingDirIds.has(entry.taskDir)) continue

      // 构造与 localStorage 兼容的历史条目
      const taskId = entry.id
      const modeLabel = entry.mode === 'batch' ? '批量'
        : entry.mode === 'vectorize' ? '矢量化'
        : '单条'

      logs.value.unshift({
        id: taskId,
        title: String(entry.title || ''),
        time: new Date(entry.time || Date.now()).toLocaleTimeString('zh-CN', { hour12: false }),
        status: entry.status || '完成',
        mode: modeLabel,
        thumb: '',
      })

      // 构造 historyDirs 记录
      const paths = entry.paths || {}
      setHistoryDir(taskId, {
        taskDir: entry.taskDir || '',
        outputRoot: entry.outputRoot || '',
        taskName: String(entry.title || ''),
        paths,
        inputParams: entry.inputParams || { mode: entry.mode || 'single' },
      })

      added++
    }

    if (added > 0) {
      // 排序：按时间的倒序排列（最新的在前）
      logs.value.sort((a, b) => {
        const timeA = new Date(a.time || 0).getTime()
        const timeB = new Date(b.time || 0).getTime()
        return timeB - timeA
      })
      // 保留最多 50 条
      logs.value = logs.value.slice(0, 50)
      persistHistory()
      console.log(`[mergeFsHistory] 从文件系统合并了 ${added} 条历史记录`)
    }
  } catch (err) {
    console.warn('[mergeFsHistory] 扫描文件系统历史失败:', err.message)
  }
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
        seed: payload.seed,
        __timeoutMs: 300000
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
      // 通过主进程解析（与 CLI 一致的 | \t , 分隔和 CSV 引号转义逻辑）
      const entries = await parseBatchInput(payload.batch || '')
      batchItems.value = []
      batchProgress.current = 0
      batchProgress.total = entries.length
      batchProgress.completed = 0
      batchProgress.failed = 0
      selectedBatchIndex.value = -1

      const batchTaskInfo = await prepareOutputTask({ mode: 'batch-batch', index: 0, text: 'batch-run', seed: payload.seed, startedAt: taskStartedAt, usesTxt2Img: false })
      const batchSummaryDir = batchTaskInfo.taskDir
      currentTaskDir.value = batchTaskInfo.taskDir
      currentOutputRoot.value = batchTaskInfo.outputRoot
      currentTaskPaths.value = { ...batchTaskInfo.paths, summary: joinPath(batchSummaryDir, 'batch_summary.csv') }
      const batchSummaryPath = joinPath(batchSummaryDir, 'batch_summary.csv')

      for (let i = 0; i < entries.length; i++) {
        const entry = entries[i]
        const text = entry.text || ''
        const prompt = entry.prompt || ''
        const itemNegative = entry.negative || payload.negative || ''
        const itemResolution = entry.resolution || payload.resolution
        const itemSeed = entry.seed === undefined || entry.seed === '' ? payload.seed : Number(entry.seed)

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
          // Stage 1: 生成位图（批量首条含模型加载，超时放宽到 600s）
          const payloadA = { text, prompt, negative: itemNegative, resolution: itemResolution, format: payload.format, seed: itemSeed, __timeoutMs: 600000 }
          const t1 = Date.now()
          const respA = await generateArtBitmap(payloadA)
          const s1Ms = Date.now() - t1
          const batchWorkflowArtifacts = {
            workflowApi: respA.workflow_api || null,
            modelDependencies: respA.model_dependencies || null,
          }
          const itemTaskInfo = await prepareOutputTask({ mode: 'batch', index: i + 1, text: text || `item-${i + 1}`, seed: itemSeed, startedAt: taskStartedAt, usesTxt2Img: true, outputRoot: batchSummaryDir, summaryDir: batchSummaryDir })
          const batchEngine = respA.metadata?.engine || ''
          await writeTaskArtifacts({
            outputRoot: itemTaskInfo.outputRoot,
            taskDir: itemTaskInfo.taskDir,
            taskName: itemTaskInfo.taskName,
            paths: itemTaskInfo.paths,
            artifacts: { original: respA.png },
            metadata: null,
            runLog: buildRunLog({ task, taskInfo: itemTaskInfo, modeName: 'batch', text, prompt, seed: itemSeed, stage1Duration: s1Ms, status: 'vectorizing', usesTxt2Img: true, engine: batchEngine }),
            usesTxt2Img: true,
            workflowArtifacts: batchWorkflowArtifacts
          })

          // Stage 2: 矢量化
          const payloadB = {
            source_type: 'generated', text, prompt,
            negative: itemNegative,
            resolution: itemResolution, format: payload.format, seed: itemSeed,
            vector: { ...payload.vector },
            __timeoutMs: 300000,
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
          item.metadata = augmentMetadata(item.metadata, { task, taskInfo: itemTaskInfo, modeName: 'batch', text, prompt, seed: itemSeed, usesTxt2Img: true })
          await writeTaskArtifacts({
            outputRoot: itemTaskInfo.outputRoot,
            taskDir: itemTaskInfo.taskDir,
            taskName: itemTaskInfo.taskName,
            paths: itemTaskInfo.paths,
            artifacts: { original: item.original, transparent: item.transparent, preview: item.preview, svg: item.svg },
            metadata: item.metadata,
            runLog: buildRunLog({ task, taskInfo: itemTaskInfo, modeName: 'batch', text, prompt, seed: itemSeed, stage1Duration: s1Ms, stage2Duration: s2Ms, status: batchStatus, usesTxt2Img: true, engine: batchEngine }),
            usesTxt2Img: true,
            summaryRow: {
              ...buildSummaryRow({
                task,
                taskInfo: itemTaskInfo,
                modeName: 'batch',
                status: batchStatus,
                text,
                prompt,
                seed: itemSeed,
                metadata: item.metadata,
                generationMs: s1Ms,
                vectorMs: s2Ms
              }),
              summary_path: batchSummaryPath
            },
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
              seed: itemSeed,
              errorMessage: item.error,
              usesTxt2Img: true,
              stage1Duration: item.stage1Ms || 0,
              stage2Duration: item.stage2Ms || 0
            })
          }
          batchProgress.failed++
        }
      }

      // 构建文件列表：批量根目录、汇总 CSV，以及每条成功/失败的子任务目录。
      currentFiles.value = buildBatchCurrentFiles(batchSummaryDir, batchSummaryPath, batchItems.value)
      currentTaskDir.value = batchSummaryDir
      currentOutputRoot.value = batchTaskInfo.outputRoot
      currentTaskPaths.value = { ...batchTaskInfo.paths, summary: batchSummaryPath, summaryDir: batchSummaryDir }

      // 设置最终任务状态
      if (batchProgress.failed === entries.length) {
        task.status = '失败'
        error.value = '所有批量任务均失败。'
      } else if (batchProgress.failed > 0) {
        task.status = `部分完成（${batchProgress.completed}/${entries.length}）`
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

const parseCsvRows = (csvText) => {
  const rows = []
  let row = []
  let field = ''
  let inQuotes = false

  for (let i = 0; i < csvText.length; i++) {
    const char = csvText[i]
    const next = csvText[i + 1]

    if (inQuotes) {
      if (char === '"' && next === '"') {
        field += '"'
        i++
      } else if (char === '"') {
        inQuotes = false
      } else {
        field += char
      }
      continue
    }

    if (char === '"') {
      inQuotes = true
    } else if (char === ',') {
      row.push(field)
      field = ''
    } else if (char === '\n') {
      row.push(field)
      rows.push(row)
      row = []
      field = ''
    } else if (char !== '\r') {
      field += char
    }
  }

  if (field || row.length) {
    row.push(field)
    rows.push(row)
  }

  const [rawHeader = [], ...body] = rows.filter(r => r.some(cell => String(cell || '').trim() !== ''))
  const header = rawHeader.map(key => String(key || '').replace(/^\uFEFF/, ''))
  return body.map(values => Object.fromEntries(header.map((key, index) => [key, values[index] || ''])))
}

const isAbsoluteOutputPath = (value) => (
  /^[a-zA-Z]:[\\/]/.test(value || '') ||
  String(value || '').startsWith('\\\\') ||
  String(value || '').startsWith('/')
)

const resolveSummaryRelativePath = (value, summaryPath) => {
  if (!value) return ''
  if (isAbsoluteOutputPath(value)) return value
  return joinPath(dirname(summaryPath), value)
}

const toNumberOrZero = (value) => {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

const parseKeyValueLog = (text) => {
  const map = {}
  String(text || '').split(/\r?\n/).forEach((line) => {
    const idx = line.indexOf('=')
    if (idx > 0) map[line.slice(0, idx)] = line.slice(idx + 1)
  })
  return map
}

const buildMetricMetadata = ({ text = '', prompt = '', seed = 0, generationMs = 0, vectorMs = 0, pngTransparency = '', svgFidelity = '' } = {}) => ({
  generation: {
    text,
    prompt,
    seed,
    ...(generationMs ? { duration_ms: generationMs } : {})
  },
  stats: vectorMs ? { elapsed_ms: vectorMs } : {},
  preprocess: pngTransparency !== '' ? { png_transparency: pngTransparency } : {},
  quality: svgFidelity !== '' ? { svg_fidelity: svgFidelity } : {}
})

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
    `generation_ms=${stage1Duration}`,
    `vector_ms=${stage2Duration}`,
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
    summaryRow: {
      ...buildSummaryRow({
        task,
        taskInfo,
        modeName,
        status: 'failed',
        text,
        prompt,
        seed,
        error: errorMessage,
        generationMs: stage1Duration,
        vectorMs: stage2Duration
      }),
      summary_path: summaryTarget
    }
  })
}

const buildSummaryRow = ({ task, taskInfo, modeName, status = 'success', text = '', prompt = '', seed = 0, error = '', metadata = null, generationMs = 0, vectorMs = 0 }) => {
  const metrics = {
    generation_ms: generationMs || metadata?.generation?.duration_ms || '',
    vector_ms: vectorMs || metadata?.stats?.elapsed_ms || '',
    png_transparency: metadata?.preprocess?.png_transparency ?? '',
    svg_fidelity: metadata?.quality?.svg_fidelity ?? ''
  }
  return {
    task_id: String(task?.id || ''),
    task_name: taskInfo?.taskName || '',
    mode: modeName,
    status,
    text,
    prompt,
    seed,
    resolution: payload.resolution,
    task_dir: taskInfo?.taskDir || '',
    run_log_path: taskInfo?.paths?.log || '',
    ...metrics,
    error
  }
}

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
        modelDownloadProgress.speed = ''
        modelDownloadProgress.eta = ''
        modelDownloadProgress.filePercent = -1
        if (modelDownloadProgress.total > 0) {
          modelDownloadProgress.current = modelDownloadProgress.total
        }
      } else if (data.phase === 'error') {
        modelDownloadProgress.speed = ''
        modelDownloadProgress.eta = ''
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

const ensureBatchItemArtifacts = async (item) => {
  if (!item || item.assetsLoaded || !item.paths) return

  const [original, transparent, preview, svg, metadataText] = await Promise.all([
    pathToDataUrl(item.paths.original),
    pathToDataUrl(item.paths.transparent),
    pathToDataUrl(item.paths.preview),
    readTextPath(item.paths.svg),
    readTextPath(item.paths.metadata)
  ])

  item.original = original || item.original || ''
  item.transparent = transparent || item.transparent || ''
  item.preview = preview || item.preview || ''
  item.svg = svg || item.svg || ''

  const parsedMetadata = metadataText ? safeJsonParse(metadataText) : null
  if (parsedMetadata) {
    parsedMetadata.generation = parsedMetadata.generation || {}
    parsedMetadata.stats = parsedMetadata.stats || {}
    parsedMetadata.preprocess = parsedMetadata.preprocess || {}
    parsedMetadata.quality = parsedMetadata.quality || {}
    if (item.stage1Ms && !parsedMetadata.generation.duration_ms) parsedMetadata.generation.duration_ms = item.stage1Ms
    if (item.stage2Ms && !parsedMetadata.stats.elapsed_ms) parsedMetadata.stats.elapsed_ms = item.stage2Ms
    if (item.metadata?.preprocess?.png_transparency !== undefined && parsedMetadata.preprocess.png_transparency === undefined) {
      parsedMetadata.preprocess.png_transparency = item.metadata.preprocess.png_transparency
    }
    if (item.metadata?.quality?.svg_fidelity !== undefined && parsedMetadata.quality.svg_fidelity === undefined) {
      parsedMetadata.quality.svg_fidelity = item.metadata.quality.svg_fidelity
    }
    item.metadata = parsedMetadata
  }

  item.assetsLoaded = true
}

const buildBatchCurrentFiles = (batchRoot, summaryPath, items) => {
  const files = [
    { key: 'batchRoot', name: basename(batchRoot) || 'batch-run', data: batchRoot, isPath: true },
    { key: 'batchSummary', name: 'batch_summary.csv', data: summaryPath, isPath: true }
  ]
  items.forEach((entry, idx) => {
    if (!entry.taskDir) return
    files.push({ key: `task${idx + 1}`, name: entry.taskName || `task_${idx + 1}`, data: entry.taskDir, isPath: true })
  })
  return files
}

const restoreBatchHistory = async (item, saved) => {
  const summaryPath = saved.paths?.summary || joinPath(saved.taskDir, 'batch_summary.csv')
  const summaryText = await readTextPath(summaryPath)
  if (!summaryText) throw new Error('batch_summary.csv is missing or unreadable')

  const rows = parseCsvRows(summaryText)
  if (!rows.length) throw new Error('batch_summary.csv has no rows')

  const restoredItems = []
  for (let i = 0; i < rows.length; i++) {
    const row = rows[i]
    const taskDir = resolveSummaryRelativePath(row.task_dir, summaryPath)
    const paths = {
      original: row.original_path ? resolveSummaryRelativePath(row.original_path, summaryPath) : joinPath(taskDir, 'original.png'),
      transparent: row.transparent_path ? resolveSummaryRelativePath(row.transparent_path, summaryPath) : joinPath(taskDir, 'transparent.png'),
      svg: row.result_svg_path ? resolveSummaryRelativePath(row.result_svg_path, summaryPath) : joinPath(taskDir, 'result.svg'),
      preview: row.preview_path ? resolveSummaryRelativePath(row.preview_path, summaryPath) : joinPath(taskDir, 'preview.png'),
      metadata: row.metadata_path ? resolveSummaryRelativePath(row.metadata_path, summaryPath) : joinPath(taskDir, 'metadata.json'),
      log: row.run_log_path ? resolveSummaryRelativePath(row.run_log_path, summaryPath) : joinPath(taskDir, 'run.log'),
      summary: summaryPath,
      summaryDir: dirname(summaryPath)
    }

    const runLog = parseKeyValueLog(await readTextPath(paths.log))
    const generationMs = toNumberOrZero(row.generation_ms || runLog.generation_ms)
    const vectorMs = toNumberOrZero(row.vector_ms || runLog.vector_ms)
    const status = row.status === 'failed' || row.error ? 'failed' : 'success'

    restoredItems.push({
      index: i,
      text: row.text || '',
      prompt: row.prompt || '',
      status,
      rawStatus: row.status || '',
      error: row.error || '',
      original: '',
      transparent: '',
      preview: '',
      svg: '',
      metadata: buildMetricMetadata({
        text: row.text || '',
        prompt: row.prompt || '',
        seed: toNumberOrZero(row.seed),
        generationMs,
        vectorMs,
        pngTransparency: row.png_transparency,
        svgFidelity: row.svg_fidelity
      }),
      stage1Ms: generationMs,
      stage2Ms: vectorMs,
      taskDir,
      outputRoot: saved.outputRoot || dirname(summaryPath),
      taskName: row.task_name || basename(taskDir) || `task_${i + 1}`,
      paths,
      assetsLoaded: false
    })
  }

  mode.value = 'batch'
  batchItems.value = restoredItems
  batchProgress.total = restoredItems.length
  batchProgress.completed = restoredItems.filter(entry => entry.status === 'success').length
  batchProgress.failed = restoredItems.filter(entry => entry.status === 'failed').length
  batchProgress.current = restoredItems.length

  currentFiles.value = buildBatchCurrentFiles(saved.taskDir, summaryPath, restoredItems)
  currentTaskDir.value = saved.taskDir
  currentOutputRoot.value = saved.outputRoot || dirname(summaryPath)
  currentTaskPaths.value = { ...(saved.paths || {}), summary: summaryPath, summaryDir: dirname(summaryPath) }

  applyInputParamsToForm(saved.inputParams, 'batch')
  activeTab.value = 'output'

  const firstSuccess = restoredItems.findIndex(entry => entry.status === 'success')
  if (firstSuccess >= 0) {
    await selectBatchItem(firstSuccess)
  } else {
    selectedBatchIndex.value = 0
    result.original = ''
    result.transparent = ''
    result.preview = ''
    result.image = ''
    result.svg = ''
    result.metadata = null
  }
}

const selectBatchItem = async (index) => {
  const item = batchItems.value[index]
  selectedBatchIndex.value = index
  if (!item) return

  if (item.status !== 'success') {
    result.original = ''
    result.transparent = ''
    result.preview = ''
    result.image = ''
    result.svg = ''
    result.metadata = null
    currentTaskDir.value = item.taskDir || currentTaskDir.value
    currentOutputRoot.value = item.outputRoot || currentOutputRoot.value
    currentTaskPaths.value = item.paths || currentTaskPaths.value
    return
  }

  await ensureBatchItemArtifacts(item)
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
      if (restoredMode === 'batch') {
        await restoreBatchHistory(item, saved)
        return
      }

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
