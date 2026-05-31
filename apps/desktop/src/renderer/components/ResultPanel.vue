<template>
  <section class="result-panel">
    <!-- 批量进度条 -->
    <div v-if="isBatch && (running || batchItems.length > 0)" class="batch-progress-bar">
      <div class="progress-info">
        <span class="progress-label">批量进度</span>
        <span class="progress-count">{{ batchProgress.completed }}/{{ batchProgress.total }} 完成</span>
        <span v-if="batchProgress.failed > 0" class="progress-failed">{{ batchProgress.failed }} 失败</span>
      </div>
      <div class="progress-track">
        <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
      </div>
    </div>

    <!-- 单条/矢量化模式：生成进度 -->
    <div v-if="!isBatch && running" class="gen-progress">
      <div class="gen-progress-spinner"></div>
      <div class="gen-progress-info">
        <div class="gen-progress-steps">
          <span v-if="mode !== 'vectorize'" :class="['gen-step', { active: stageProgress.stage1.active, done: !stageProgress.stage1.active && result.original }]">
            <span class="gen-step-dot"></span>生成位图
          </span>
          <span class="gen-step-arrow" v-if="mode !== 'vectorize'">→</span>
          <span :class="['gen-step', { active: stageProgress.stage2.active, done: !stageProgress.stage2.active && (result.transparent || result.preview) }]">
            <span class="gen-step-dot"></span>矢量化
          </span>
        </div>
        <p class="gen-progress-text">
          <template v-if="stageProgress.stage1.active">正在生成位图，请稍候…</template>
          <template v-else-if="stageProgress.stage2.active">正在矢量化处理，请稍候…</template>
          <template v-else>准备中…</template>
        </p>
      </div>
    </div>

    <!-- 批量模式：双栏布局 -->
    <div v-if="isBatch && batchItems.length > 0" class="batch-layout">
      <!-- 左栏：条目列表 -->
      <div class="batch-list">
        <div class="batch-list-header">
          <span>任务列表</span>
          <span class="batch-list-count">{{ batchItems.length }} 条</span>
        </div>
        <div class="batch-list-body">
          <div
            v-for="(item, idx) in batchItems"
            :key="idx"
            :class="['batch-item', { active: selectedBatchIndex === idx, failed: item.status === 'failed' }]"
            @click="$emit('select-batch-item', idx)"
          >
            <div class="batch-item-thumb">
              <img v-if="item.preview || item.original" :src="item.preview || item.original" alt="" />
              <span v-else class="batch-item-placeholder">—</span>
            </div>
            <div class="batch-item-info">
              <div class="batch-item-title">{{ item.text || `第 ${idx + 1} 条` }}</div>
              <div class="batch-item-meta">
                <span v-if="item.status === 'running'" class="status-running">生成中…</span>
                <span v-else-if="item.status === 'success'" class="status-success">
                  ✓ {{ item.stage1Ms + item.stage2Ms }}ms
                </span>
                <span v-else-if="item.status === 'failed'" class="status-failed">
                  ✕ {{ item.error }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右栏：选中条目详情 -->
      <div class="batch-detail" v-if="selectedBatchIndex >= 0 && batchItems[selectedBatchIndex]?.status === 'success'">
        <div class="result-header">
          <div>
            <p class="section-kicker">Result #{{ selectedBatchIndex + 1 }}</p>
            <div class="title-row">
              <h2>{{ batchItems[selectedBatchIndex].text || '生成结果' }}</h2>
              <div class="bg-toggle">
                <button
                  :class="['bg-toggle-btn', { active: previewBg === 'white' }]"
                  title="白色背景"
                  @click="previewBg = 'white'"
                >白</button>
                <button
                  :class="['bg-toggle-btn', { active: previewBg === 'black' }]"
                  title="黑色背景"
                  @click="previewBg = 'black'"
                >黑</button>
              </div>
            </div>
          </div>
          <div class="download-actions">
            <button class="secondary-button small" type="button" :disabled="!result.original" @click="$emit('download', 'original')">原始图像</button>
            <button class="secondary-button small" type="button" :disabled="!result.transparent" @click="$emit('download', 'transparent')">透明化图像</button>
            <button class="secondary-button small" type="button" :disabled="!result.preview && !result.image" @click="$emit('download', 'preview')">矢量化预览</button>
            <button class="secondary-button small" type="button" :disabled="!result.svg" @click="$emit('download', 'svg')">SVG</button>
            <button class="secondary-button small" type="button" :disabled="!result.metadata" @click="$emit('download', 'json')">JSON</button>
            <button class="primary-button small" type="button" :disabled="!hasResultContent" @click="$emit('save-all')">打包下载</button>
          </div>
        </div>

        <div class="preview-grid" v-if="result.original || result.transparent || result.preview || result.image">
          <div class="preview-card" v-if="result.original">
            <div class="preview-label">原始图像</div>
            <div class="preview-frame" :style="{ background: previewBg === 'white' ? '#fff' : '#1a1a1a' }"><img :src="result.original" alt="原始图像" /></div>
          </div>
          <div class="preview-card" v-if="result.transparent">
            <div class="preview-label">透明化图像</div>
            <div class="preview-frame" :style="{ background: previewBg === 'white' ? '#fff' : '#1a1a1a' }"><img :src="result.transparent" alt="透明化图像" /></div>
          </div>
          <div class="preview-card" v-if="result.preview || result.image">
            <div class="preview-label">矢量化预览</div>
            <div class="preview-frame" :style="{ background: previewBg === 'white' ? '#fff' : '#1a1a1a' }"><img :src="result.preview || result.image" alt="矢量化预览" /></div>
          </div>
        </div>

        <div class="metrics-block" v-if="result.metadata">
          <h3>处理指标</h3>
          <div class="metrics-grid">
            <table class="metrics-table">
              <thead><tr><th>耗时统计</th><th>数值</th></tr></thead>
              <tbody>
                <tr>
                  <td>生成图片耗时</td>
                  <td v-if="result.metadata.generation?.duration_ms">{{ result.metadata.generation.duration_ms }} ms</td>
                  <td v-else class="muted">用户上传图片</td>
                </tr>
                <tr v-if="result.metadata.stats?.elapsed_ms !== undefined">
                  <td>矢量化耗时</td>
                  <td>{{ result.metadata.stats.elapsed_ms }} ms</td>
                </tr>
              </tbody>
            </table>
            <table class="metrics-table">
              <thead><tr><th>质量指标</th><th>数值</th></tr></thead>
              <tbody>
                <tr v-if="result.metadata.preprocess?.png_transparency !== undefined && result.metadata.preprocess?.png_transparency !== null">
                  <td>PNG 透明度</td>
                  <td>{{ result.metadata.preprocess.png_transparency }}%</td>
                </tr>
                <tr v-if="result.metadata.quality?.svg_fidelity !== undefined && result.metadata.quality?.svg_fidelity !== null">
                  <td>SVG 还原度</td>
                  <td>{{ result.metadata.quality.svg_fidelity }}%</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- 右栏：失败条目 -->
      <div v-else-if="selectedBatchIndex >= 0 && batchItems[selectedBatchIndex]?.status === 'failed'" class="batch-detail batch-detail-empty">
        <div class="batch-fail-card">
          <span class="fail-icon">✕</span>
          <p>第 {{ selectedBatchIndex + 1 }} 条生成失败</p>
          <p class="fail-reason">{{ batchItems[selectedBatchIndex].error }}</p>
        </div>
      </div>
      <!-- 右栏：无选中 -->
      <div v-else class="batch-detail batch-detail-empty">
        <p class="empty-hint">← 点击左侧条目查看结果</p>
      </div>
    </div>

    <!-- 非批量模式：原有单条布局 -->
    <template v-if="!isBatch">
      <div class="result-header">
        <div>
          <p class="section-kicker">Result</p>
          <div class="title-row">
            <h2>生成结果</h2>
            <div class="bg-toggle">
              <button
                :class="['bg-toggle-btn', { active: previewBg === 'white' }]"
                title="白色背景"
                @click="previewBg = 'white'"
              >白</button>
              <button
                :class="['bg-toggle-btn', { active: previewBg === 'black' }]"
                title="黑色背景"
                @click="previewBg = 'black'"
              >黑</button>
            </div>
          </div>
        </div>
        <div class="download-actions">
          <button class="secondary-button small" type="button" :disabled="!result.original" @click="$emit('download', 'original')">原始图像</button>
          <button class="secondary-button small" type="button" :disabled="!result.transparent" @click="$emit('download', 'transparent')">透明化图像</button>
          <button class="secondary-button small" type="button" :disabled="!result.preview && !result.image" @click="$emit('download', 'preview')">矢量化预览</button>
          <button class="secondary-button small" type="button" :disabled="!result.svg" @click="$emit('download', 'svg')">SVG</button>
          <button class="secondary-button small" type="button" :disabled="!result.metadata" @click="$emit('download', 'json')">JSON</button>
          <button class="primary-button small" type="button" :disabled="!hasResultContent" @click="$emit('save-all')">打包下载</button>
        </div>
      </div>

      <div class="preview-grid" v-if="shouldShowPreviewGrid">
        <!-- 原始图像 -->
        <div class="preview-card" v-if="result.original || stageProgress.stage1.active || (running && mode !== 'vectorize')">
          <div class="preview-label">原始图像</div>
          <div class="preview-frame" :style="{ background: previewBg === 'white' ? '#fff' : '#1a1a1a' }">
            <img v-if="result.original" :src="result.original" alt="原始图像" />
            <div v-else class="preview-loading">
              <div class="loading-spinner"></div>
              <span class="loading-text">正在生成中<span class="loading-dots"><i>.</i><i>.</i><i>.</i></span></span>
            </div>
          </div>
        </div>
        <!-- 透明化图像 -->
        <div class="preview-card" v-if="result.transparent || stageProgress.stage2.active || running">
          <div class="preview-label">透明化图像</div>
          <div class="preview-frame" :style="{ background: previewBg === 'white' ? '#fff' : '#1a1a1a' }">
            <img v-if="result.transparent" :src="result.transparent" alt="透明化图像" />
            <div v-else class="preview-loading">
              <div class="loading-spinner"></div>
              <span class="loading-text">正在生成中<span class="loading-dots"><i>.</i><i>.</i><i>.</i></span></span>
            </div>
          </div>
        </div>
        <!-- 矢量化预览 -->
        <div class="preview-card" v-if="(result.preview || result.image) || stageProgress.stage2.active || running">
          <div class="preview-label">矢量化预览</div>
          <div class="preview-frame" :style="{ background: previewBg === 'white' ? '#fff' : '#1a1a1a' }">
            <img v-if="result.preview || result.image" :src="result.preview || result.image" alt="矢量化预览" />
            <div v-else class="preview-loading">
              <div class="loading-spinner"></div>
              <span class="loading-text">正在生成中<span class="loading-dots"><i>.</i><i>.</i><i>.</i></span></span>
            </div>
          </div>
        </div>
      </div>

      <div class="metrics-block" v-if="result.metadata">
        <h3>处理指标</h3>
        <div class="metrics-grid">
          <table class="metrics-table">
            <thead><tr><th>耗时统计</th><th>数值</th></tr></thead>
            <tbody>
              <tr>
                <td>生成图片耗时</td>
                <td v-if="result.metadata.generation?.duration_ms">{{ result.metadata.generation.duration_ms }} ms</td>
                <td v-else class="muted">用户上传图片</td>
              </tr>
              <tr v-if="result.metadata.stats?.elapsed_ms !== undefined">
                <td>矢量化耗时</td>
                <td>{{ result.metadata.stats.elapsed_ms }} ms</td>
              </tr>
            </tbody>
          </table>
          <table class="metrics-table">
            <thead><tr><th>质量指标</th><th>数值</th></tr></thead>
            <tbody>
              <tr v-if="result.metadata.preprocess?.png_transparency !== undefined && result.metadata.preprocess?.png_transparency !== null">
                <td>PNG 透明度</td>
                <td>{{ result.metadata.preprocess.png_transparency }}%</td>
              </tr>
              <tr v-if="result.metadata.quality?.svg_fidelity !== undefined && result.metadata.quality?.svg_fidelity !== null">
                <td>SVG 还原度</td>
                <td>{{ result.metadata.quality.svg_fidelity }}%</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- 空状态 -->
    <div v-if="!hasContent && !running" class="empty-state">
      <div class="empty-icon">📭</div>
      <p class="empty-title">无输出任务</p>
      <p class="empty-desc">在输入面板生成内容后，结果将显示在此处</p>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  result: Object,
  mode: { type: String, default: 'single' },
  batchItems: { type: Array, default: () => [] },
  batchProgress: { type: Object, default: () => ({ current: 0, total: 0, completed: 0, failed: 0 }) },
  selectedBatchIndex: { type: Number, default: -1 },
  running: { type: Boolean, default: false },
  stageProgress: { type: Object, default: () => ({ stage1: { active: false, percent: 0 }, stage2: { active: false, percent: 0 } }) }
})

const emit = defineEmits(['download', 'save-all', 'open-svg', 'select-batch-item'])

const previewBg = ref('white')  // 'white' | 'black'

const isBatch = computed(() => props.mode === 'batch')

const progressPercent = computed(() => {
  if (!props.batchProgress.total) return 0
  return Math.round(((props.batchProgress.completed + props.batchProgress.failed) / props.batchProgress.total) * 100)
})

const hasContent = computed(() => {
  if (isBatch.value && props.batchItems.length > 0) return true
  return props.result.original || props.result.transparent || props.result.preview || props.result.image || props.result.metadata
})

const hasResultContent = computed(() => {
  return props.result.original || props.result.transparent || props.result.preview || props.result.image || props.result.metadata
})

// 非批量模式下：有结果数据 或 正在运行时显示预览网格
const shouldShowPreviewGrid = computed(() => {
  if (isBatch.value) return false
  return hasResultContent.value || props.running
})
</script>

<style scoped>
.result-panel {
  margin-top: 0;
  padding: 18px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  box-shadow: var(--shadow-soft);
}

.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.result-header h2 {
  margin: 0;
  font-size: 18px;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.bg-toggle {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}

.bg-toggle-btn {
  padding: 3px 10px;
  font-size: 12px;
  font-weight: 500;
  border: none;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  transition: all 0.15s;
  line-height: 1.5;
}

.bg-toggle-btn:hover {
  background: rgba(31, 41, 55, 0.06);
  color: var(--text);
}

.bg-toggle-btn.active {
  background: var(--accent);
  color: #fff;
}

.bg-toggle-btn + .bg-toggle-btn {
  border-left: 1px solid var(--border);
}

.download-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.preview-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.preview-card {
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}

.preview-label {
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-muted);
  background: rgba(31, 41, 55, 0.03);
  border-bottom: 1px solid var(--border);
}

.preview-frame {
  aspect-ratio: 1;
  overflow: auto;
  padding: 8px;
}

.preview-frame img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}

/* ── 加载中覆盖层 ── */
.preview-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  width: 100%;
  height: 100%;
  min-height: 160px;
}

.loading-spinner {
  width: 36px;
  height: 36px;
  border: 3px solid rgba(15, 118, 110, 0.15);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading-text {
  font-size: 14px;
  font-weight: 600;
  color: var(--accent);
  letter-spacing: 0.02em;
}

.loading-dots i {
  font-style: normal;
  animation: dot-bounce 1.4s infinite;
}
.loading-dots i:nth-child(2) { animation-delay: 0.2s; }
.loading-dots i:nth-child(3) { animation-delay: 0.4s; }

@keyframes dot-bounce {
  0%, 60%, 100% { opacity: 0.2; }
  30% { opacity: 1; }
}

.metrics-block {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

.metrics-block h3 {
  margin: 0 0 12px;
  font-size: 14px;
}

.metrics-table {
  width: auto;
  min-width: 250px;
  border-collapse: collapse;
  font-size: 13px;
}

.metrics-table th,
.metrics-table td {
  padding: 8px 12px;
  text-align: left;
  border: 1px solid var(--border);
}

.metrics-table th {
  background: rgba(31, 41, 55, 0.04);
  font-weight: 600;
}

.metrics-table td:last-child {
  font-weight: 600;
  color: var(--accent);
}

.metrics-table td:last-child.muted {
  font-weight: 400;
  color: var(--text-muted);
  font-style: italic;
}

.metrics-grid {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.metrics-grid .metrics-table {
  flex: 1;
  min-width: 240px;
}

@media (max-width: 768px) {
  .preview-grid {
    grid-template-columns: 1fr;
  }
  .batch-layout {
    grid-template-columns: 1fr;
  }
}

/* ── 单条生成进度 ── */
.gen-progress {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 18px;
  margin-bottom: 16px;
  border: 1px solid rgba(15, 118, 110, 0.15);
  border-radius: 10px;
  background: rgba(15, 118, 110, 0.04);
}

.gen-progress-spinner {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border: 3px solid rgba(15, 118, 110, 0.15);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.gen-progress-info {
  flex: 1;
  min-width: 0;
}

.gen-progress-steps {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.gen-step {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-muted);
}

.gen-step.active {
  color: var(--accent);
}

.gen-step.done {
  color: #16a34a;
}

.gen-step-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--border);
}

.gen-step.active .gen-step-dot {
  background: var(--accent);
  box-shadow: 0 0 0 3px rgba(15, 118, 110, 0.2);
}

.gen-step.done .gen-step-dot {
  background: #16a34a;
}

.gen-step-arrow {
  color: var(--text-muted);
  font-size: 12px;
}

.gen-progress-text {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
}

/* ── 批量进度条 ── */
.batch-progress-bar {
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}

.progress-info {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 13px;
}

.progress-label {
  font-weight: 700;
  color: var(--text);
}

.progress-count {
  color: var(--accent);
  font-weight: 600;
}

.progress-failed {
  color: var(--danger);
  font-weight: 600;
}

.progress-track {
  width: 100%;
  height: 6px;
  border-radius: 3px;
  background: rgba(31, 41, 55, 0.08);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 3px;
  background: var(--accent);
  transition: width 0.3s ease;
}

/* ── 批量双栏布局 ── */
.batch-layout {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 16px;
  min-height: 400px;
}

/* ── 左栏：条目列表 ── */
.batch-list {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.5);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.batch-list-header {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  flex-shrink: 0;
}

.batch-list-count {
  color: var(--text-muted);
  font-weight: 400;
}

.batch-list-body {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}

.batch-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
  margin-bottom: 2px;
  border: 1px solid transparent;
}

.batch-item:hover {
  background: rgba(15, 118, 110, 0.06);
}

.batch-item.active {
  background: var(--accent-soft);
  border-color: rgba(15, 118, 110, 0.25);
}

.batch-item.failed {
  opacity: 0.7;
}

.batch-item-thumb {
  width: 40px;
  height: 40px;
  border-radius: 4px;
  overflow: hidden;
  flex-shrink: 0;
  background: rgba(31, 41, 55, 0.04);
  display: flex;
  align-items: center;
  justify-content: center;
}

.batch-item-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.batch-item-placeholder {
  color: var(--text-muted);
  font-size: 12px;
}

.batch-item-info {
  flex: 1;
  min-width: 0;
}

.batch-item-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.batch-item-meta {
  margin-top: 2px;
  font-size: 11px;
}

.status-running {
  color: var(--accent);
}

.status-success {
  color: #16a34a;
}

.status-failed {
  color: var(--danger);
}

/* ── 右栏：详情 ── */
.batch-detail {
  min-width: 0;
}

.batch-detail-empty {
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-hint {
  color: var(--text-muted);
  font-size: 14px;
}

.batch-fail-card {
  text-align: center;
  padding: 32px;
}

.fail-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: rgba(185, 28, 28, 0.1);
  color: var(--danger);
  font-size: 24px;
  margin-bottom: 12px;
}

.batch-fail-card p {
  margin: 4px 0;
  color: var(--text);
}

.fail-reason {
  color: var(--text-muted) !important;
  font-size: 13px;
}

/* ── 空状态 ── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  text-align: center;
}

.empty-icon {
  font-size: 40px;
  margin-bottom: 12px;
  opacity: 0.7;
}

.empty-title {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
}

.empty-desc {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-muted);
}
</style>
