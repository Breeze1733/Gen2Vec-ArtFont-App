<template>
  <section class="result-panel" v-if="result.original || result.transparent || result.preview || result.image || result.metadata">
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
        <button class="primary-button small" type="button" :disabled="!result.original && !result.transparent && !result.preview && !result.image && !result.metadata" @click="$emit('save-all')">打包下载</button>
      </div>
    </div>

    <div class="preview-grid" v-if="result.original || result.transparent || result.preview || result.image">
      <div class="preview-card" v-if="result.original">
        <div class="preview-label">原始图像</div>
        <div class="preview-frame">
          <img :src="result.original" alt="原始图像" />
        </div>
      </div>
      <div class="preview-card" v-if="result.transparent">
        <div class="preview-label">透明化图像</div>
        <div class="preview-frame">
          <img :src="result.transparent" alt="透明化图像" />
        </div>
      </div>
      <div class="preview-card" v-if="result.preview || result.image">
        <div class="preview-label">矢量化预览</div>
        <div class="preview-frame">
          <img :src="result.preview || result.image" alt="矢量化预览" />
        </div>
      </div>
    </div>

    <div class="metrics-block" v-if="result.metadata">
      <h3>矢量化指标</h3>
      <table class="metrics-table">
        <thead>
          <tr>
            <th>指标</th>
            <th>数值</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="result.metadata.preprocess?.png_transparency !== undefined">
            <td>PNG 透明度</td>
            <td>{{ result.metadata.preprocess.png_transparency }}%</td>
          </tr>
          <tr v-if="result.metadata.quality?.svg_fidelity !== undefined">
            <td>SVG 还原度</td>
            <td>{{ result.metadata.quality.svg_fidelity }}%</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
const props = defineProps({
  result: Object
})

const emit = defineEmits(['download', 'save-all', 'open-svg'])
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

@media (max-width: 768px) {
  .preview-grid {
    grid-template-columns: 1fr;
  }
}
</style>
