<template>
  <section class="panel main-panel">
    <div class="panel-header">
      <div>
        <p class="section-kicker">Vectorization</p>
        <h2>矢量化参数</h2>
      </div>
    </div>

    <div class="panel-body">
      <div class="panel-section">
        <h3>预设选择</h3>
        <div class="presets">
          <label v-for="(p, key) in vectorPresets" :key="key" class="preset">
            <input
              type="radio"
              name="preset"
              :value="key"
              :checked="vector.preset === key"
              @change="$emit('preset-change', key)"
            />
            <span>{{ presetLabels[key] }}</span>
          </label>
        </div>
      </div>

      <div class="panel-section">
        <h3>参数调整</h3>
        <div class="vector-grid">
          <label>
            <span>颜色精度 (1-16)</span>
            <input
              :value="vector.color_precision"
              @input="$emit('update:vector', { ...vector, color_precision: Number($event.target.value) })"
              type="number"
              min="1"
              max="16"
            />
          </label>
          <label>
            <span>斑点过滤 (1-50)</span>
            <input
              :value="vector.filter_speckle"
              @input="$emit('update:vector', { ...vector, filter_speckle: Number($event.target.value) })"
              type="number"
              min="1"
              max="50"
            />
          </label>
          <label>
            <span>拐角阈值 (1-100)</span>
            <input
              :value="vector.corner_threshold"
              @input="$emit('update:vector', { ...vector, corner_threshold: Number($event.target.value) })"
              type="number"
              min="1"
              max="100"
            />
          </label>
          <label>
            <span>长度阈值 (1-50)</span>
            <input
              :value="vector.length_threshold"
              @input="$emit('update:vector', { ...vector, length_threshold: Number($event.target.value) })"
              type="number"
              min="1"
              max="50"
            />
          </label>
          <label>
            <span>图层差异 (1-50)</span>
            <input
              :value="vector.layer_difference"
              @input="$emit('update:vector', { ...vector, layer_difference: Number($event.target.value) })"
              type="number"
              min="1"
              max="50"
            />
          </label>
          <label>
            <span>放大倍数 (1-4)</span>
            <input
              :value="vector.scale"
              @input="$emit('update:vector', { ...vector, scale: Number($event.target.value) })"
              type="number"
              min="1"
              max="4"
            />
          </label>
        </div>
      </div>

      <div class="actions">
        <button class="primary-button submit-btn" type="button" :disabled="running" @click="$emit('submit')">开始生成</button>
      </div>
    </div>
  </section>
</template>

<script setup>
const props = defineProps({
  vector: {
    type: Object,
    required: true
  },
  vectorPresets: {
    type: Object,
    required: true
  },
  running: {
    type: Boolean,
    default: false
  }
})

const presetLabels = {
  clean: '清爽',
  balanced: '平衡',
  detailed: '精细',
  ultra: '超清'
}

defineEmits(['update:vector', 'preset-change', 'submit'])
</script>

<style scoped>
.panel {
  height: 615px;
  display: flex;
  flex-direction: column;
}

.panel-body {
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}

.vector-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.vector-grid label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.vector-grid input[type="number"] {
  width: 80px;
  min-height: 32px;
}

.submit-btn {
  font-size: 24px;
  padding: 0 24px;
  min-height: 46px;
}
</style>
