<template>
  <section class="panel main-panel">
    <div class="panel-header">
      <div class="header-top">
        <div>
          <p class="section-kicker">Input</p>
          <h2>模式选择</h2>
        </div>
        <button class="reset-btn secondary-button small" type="button" :disabled="running" @click="$emit('reset')">重置</button>
      </div>
      <div class="mode-switch">
        <button
          v-for="item in modes"
          :key="item.value"
          type="button"
          :class="['mode-button', { active: mode === item.value, disabled: item.requiresGpu && !hasUsableGpu }]"
          :disabled="item.requiresGpu && !hasUsableGpu"
          @click="handleModeChange(item.value)"
          :title="item.requiresGpu && !hasUsableGpu ? '未检测到可用的 GPU' : (item.requiresGpu && gpuTier === 'integrated' ? '使用集成显卡，生成速度可能较慢' : '')"
        >
          {{ item.label }}
        </button>
      </div>
    </div>

    <div class="panel-body">
      <div v-if="error" class="status-banner error">{{ error }}</div>
      <div v-else-if="running" class="status-banner info">正在生成，请稍候…</div>

      <!-- 生成参数面板 -->

      <div v-if="mode === 'single'" class="gen-single">
        <label class="field">
          <span>文字内容</span>
          <input v-model="payload.text" type="text" placeholder="支持 2-8 个字符，示例：霓虹之风" />
        </label>
        <label class="field">
          <span>风格提示词</span>
          <textarea v-model="payload.prompt" rows="4" placeholder="例如：霓虹渐变、金属质感"></textarea>
        </label>
        <label class="field">
          <span>负面提示词</span>
          <textarea v-model="payload.negative" rows="2" placeholder="缺字，错字，笔画断裂，杂乱背景，低清晰度"></textarea>
        </label>
        <label class="field two-col">
          <div>
            <span>分辨率</span>
            <select v-model="payload.resolution">
              <option>1024 x 1024</option>
              <option>1664 x 928</option>
              <option>1920 x 1080</option>
              <option value="custom">自定义</option>
            </select>
          </div>
          <div v-if="payload.resolution === 'custom'">
            <input v-model="customRes" placeholder="例如 1400x800" />
          </div>
        </label>
        <!-- 输出格式已移除，默认由后台或全局配置决定 -->
        <label class="field seed-field">
          <span>随机种子</span>
          <input v-model.number="payload.seed" type="number" />
        </label>
      </div>

      <div v-else-if="mode === 'batch'" class="gen-batch">
        <label class="field">
          <span>批量提示词（或上传文件 CSV/TXT/JSON）</span>
          <textarea v-model="payload.batch" rows="5" placeholder="每行一条：文本 | 风格"></textarea>
          <div class="batch-upload">
            <input type="file" accept=".txt,.csv,.json" @change="onBatchFileChange" />
          </div>
        </label>
        <label class="field">
          <span>全局负面提示词</span>
          <textarea v-model="payload.negative" rows="2" placeholder="应用于所有批量任务"></textarea>
        </label>
        <label class="field two-col">
          <div>
            <span>全局分辨率</span>
            <select v-model="payload.resolution">
              <option>1024 x 1024</option>
              <option>1664 x 928</option>
              <option>1920 x 1080</option>
              <option value="custom">自定义</option>
            </select>
          </div>
          <div v-if="payload.resolution === 'custom'">
            <input v-model="customRes" placeholder="例如 1400x800" />
          </div>
        </label>
        <!-- 全局输出格式已移除 -->
        <label class="field seed-field">
          <span>全局随机种子</span>
          <input v-model.number="payload.seed" type="number" />
        </label>
      </div>

      <div v-else class="gen-image">
        <label class="field">
          <span>选择图片（PNG/JPG）</span>
          <input type="file" accept="image/png,image/jpeg" @change="onImageFileChange" />
          <div v-if="previewThumb" class="thumb"><img :src="previewThumb" alt="thumb" /></div>
          <small>支持拖拽上传</small>
        </label>
      </div>
      
    </div>
  </section>
</template>

<script setup>
const props = defineProps({
  mode: String,
  payload: Object,
  running: Boolean,
  error: String,
  hasUsableGpu: {
    type: Boolean,
    default: false
  },
  gpuTier: {
    type: String,
    default: 'unknown'
  }
})

const modes = [
  { label: '单条提示词', value: 'single', requiresGpu: true },
  { label: '批量提示词', value: 'batch', requiresGpu: true },
  { label: '图片矢量化', value: 'vectorize', requiresGpu: false }
]

const emit = defineEmits(['file-change', 'update:mode', 'batch-file', 'reset'])

import { ref, computed } from 'vue'

const handleModeChange = (newMode) => {
  // 仅在完全没有 GPU 时限制为矢量化模式
  if (!props.hasUsableGpu && newMode !== 'vectorize') {
    return
  }
  emit('update:mode', newMode)
}

const customRes = ref('')
const previewThumb = ref('')

// 随机种子功能已移除

const onBatchFileChange = async (event) => {
  const file = event.target.files?.[0]
  if (!file) return
  const text = await new Promise((res, rej) => {
    const r = new FileReader()
    r.onload = () => res(String(r.result || ''))
    r.onerror = () => rej(new Error('文件读取失败'))
    r.readAsText(file)
  })
  // 简单解析：每行一条，分隔符可为 | 或 ,
  props.payload.batch = text
  emit('batch-file', { name: file.name, content: text })
}

const onImageFileChange = async (event) => {
  const file = event.target.files?.[0]
  if (!file) return
  props.payload.imageFile = file
  emit('file-change', file)
  const url = await fileToDataUrl(file)
  previewThumb.value = url
}

const fileToDataUrl = (file) => new Promise((resolve, reject) => {
  const r = new FileReader()
  r.onload = () => resolve(String(r.result || ''))
  r.onerror = () => reject(new Error('读取失败'))
  r.readAsDataURL(file)
})

</script>

<style scoped>
.main-panel {
  display: flex;
  flex-direction: column;
  height: 622px;
}

.panel-header {
  flex-shrink: 0;
  flex-direction: column;
  align-items: stretch;
  margin-bottom: -2px;
}

.header-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 10px;
}

.mode-switch {
  display: flex;
  gap: 6px;
}

.mode-button.disabled {
  opacity: 0.5;
  cursor: not-allowed;
  filter: grayscale(100%);
}

.panel-body {
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}

.panel-body textarea {
  min-height: auto;
}

.two-col select,
.two-col input {
  height: 42px;
  min-height: 42px;
  max-height: 42px;
  box-sizing: border-box;
}

.reset-btn {
  background: #1f2937;
  color: #fff;
  border: none;
}

.reset-btn:hover {
  background: #374151;
}
</style>
