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
              :checked="!presetDirty && vector.preset === key"
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
            <span>颜色精度 (1-8)</span>
            <input
              :value="vector.color_precision"
              @input="$emit('update:vector', { ...vector, color_precision: Number($event.target.value) })"
              type="number"
              min="1"
              max="8"
            />
          </label>
          <label>
            <span>斑点过滤 (0-64)</span>
            <input
              :value="vector.filter_speckle"
              @input="$emit('update:vector', { ...vector, filter_speckle: Number($event.target.value) })"
              type="number"
              min="0"
              max="64"
            />
          </label>
          <label>
            <span>拐角阈值 (1-180)</span>
            <input
              :value="vector.corner_threshold"
              @input="$emit('update:vector', { ...vector, corner_threshold: Number($event.target.value) })"
              type="number"
              min="1"
              max="180"
            />
          </label>
          <label>
            <span>长度阈值 (1-64)</span>
            <input
              :value="vector.length_threshold"
              @input="$emit('update:vector', { ...vector, length_threshold: Number($event.target.value) })"
              type="number"
              min="1"
              max="64"
            />
          </label>
          <label>
            <span>图层差异 (1-64)</span>
            <input
              :value="vector.layer_difference"
              @input="$emit('update:vector', { ...vector, layer_difference: Number($event.target.value) })"
              type="number"
              min="1"
              max="64"
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
import { computed } from 'vue'

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

const PARAM_KEYS = [
  'color_precision',
  'filter_speckle',
  'corner_threshold',
  'length_threshold',
  'layer_difference',
  'scale'
]

// 参数偏离当前预设时取消预设按钮高亮，重新点击预设后恢复
const presetDirty = computed(() => {
  const preset = props.vectorPresets[props.vector.preset]
  if (!preset) return true
  return PARAM_KEYS.some((key) => Number(props.vector[key]) !== Number(preset[key]))
})
</script>

<style scoped>
.panel {
  height: 622px;
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
