<template>
  <section class="result-panel" v-if="hasContent">
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
            <h2>{{ batchItems[selectedBatchIndex].text || '生成结果' }}</h2>
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
            <div class="preview-frame"><img :src="result.original" alt="原始图像" /></div>
          </div>
          <div class="preview-card" v-if="result.transparent">
            <div class="preview-label">透明化图像</div>
            <div class="preview-frame"><img :src="result.transparent" alt="透明化图像" /></div>
          </div>
          <div class="preview-card" v-if="result.preview || result.image">
            <div class="preview-label">矢量化预览</div>
            <div class="preview-frame"><img :src="result.preview || result.image" alt="矢量化预览" /></div>
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
          <h2>生成结果</h2>
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
          <div class="preview-frame"><img :src="result.original" alt="原始图像" /></div>
        </div>
        <div class="preview-card" v-if="result.transparent">
          <div class="preview-label">透明化图像</div>
          <div class="preview-frame"><img :src="result.transparent" alt="透明化图像" /></div>
        </div>
        <div class="preview-card" v-if="result.preview || result.image">
          <div class="preview-label">矢量化预览</div>
          <div class="preview-frame"><img :src="result.preview || result.image" alt="矢量化预览" /></div>
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
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  result: Object,
  mode: { type: String, default: 'single' },
  batchItems: { type: Array, default: () => [] },
  batchProgress: { type: Object, default: () => ({ current: 0, total: 0, completed: 0, failed: 0 }) },
  selectedBatchIndex: { type: Number, default: -1 },
  running: { type: Boolean, default: false }
})

const emit = defineEmits(['download', 'save-all', 'open-svg', 'select-batch-item'])

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
</style>
