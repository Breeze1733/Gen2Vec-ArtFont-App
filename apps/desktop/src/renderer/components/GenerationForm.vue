<template>
  <section class="panel main-panel">
    <div class="panel-header">
      <div>
        <p class="section-kicker">Generation</p>
        <h2>生成配置</h2>
      </div>
      <div class="status">
        <span class="status-dot" :class="{ active: running }"></span>
        <span>{{ running ? '运行中' : '空闲' }}</span>
      </div>
    </div>

    <div class="panel-body">
      <div v-if="error" class="status-banner error">{{ error }}</div>
      <div v-else-if="running" class="status-banner info">正在生成，请稍候…</div>

      <!-- 模式切换由顶部 ModeSwitcher 控制（局部切换面板已移除） -->

      <!-- 生成参数面板 -->
      <div class="panel-section generation-params">
        <h3>生成参数</h3>

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
            <textarea v-model="payload.negative" rows="3" placeholder="缺字，错字，笔画断裂，杂乱背景，低清晰度"></textarea>
          </label>
          <label class="field two-col">
            <div>
              <span>分辨率</span>
              <select v-model="payload.resolution">
                <option>1024 x 1024</option>
                <option>1280 x 720</option>
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
            <textarea v-model="payload.negative" rows="3" placeholder="应用于所有批量任务"></textarea>
          </label>
          <label class="field">
            <span>全局分辨率</span>
            <select v-model="payload.resolution">
              <option>1024 x 1024</option>
              <option>1280 x 720</option>
              <option>1920 x 1080</option>
            </select>
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
            <small>支持拖拽上传（开发版请使用桌面端以便保存结果）</small>
          </label>
        </div>
      </div>

      <!-- 矢量化参数面板（通用） -->
      <div class="panel-section vector-panel">
        <h3>矢量化参数</h3>
        <div class="presets">
          <label v-for="(p, key) in vectorPresets" :key="key" class="preset">
            <input type="radio" name="preset" :value="key" v-model="payload.vector.preset" @change="$emit('preset-change', payload.vector.preset)" />
            <span>{{ presetLabels[key] }}</span>
          </label>
        </div>
        <div class="vector-grid">
          <label>
            <span>颜色精度 (color_precision)</span>
            <input v-model.number="payload.vector.color_precision" type="number" min="1" max="16" />
            <small>（1-16）</small>
          </label>
          <label>
            <span>斑点过滤 (filter_speckle)</span>
            <input v-model.number="payload.vector.filter_speckle" type="number" min="1" max="50" />
            <small>（1-50）</small>
          </label>
          <label>
            <span>拐角阈值 (corner_threshold)</span>
            <input v-model.number="payload.vector.corner_threshold" type="number" min="1" max="100" />
            <small>（1-100）</small>
          </label>
          <label>
            <span>长度阈值 (length_threshold)</span>
            <input v-model.number="payload.vector.length_threshold" type="number" min="1" max="50" />
            <small>（1-50）</small>
          </label>
          <label>
            <span>图层差异 (layer_difference)</span>
            <input v-model.number="payload.vector.layer_difference" type="number" min="1" max="50" />
            <small>（1-50）</small>
          </label>
          <label>
            <span>放大倍数 (scale)</span>
            <input v-model.number="payload.vector.scale" type="number" min="1" max="4" />
            <small>（1-4）</small>
          </label>
        </div>
      </div>

      <div class="actions">
        <button class="primary-button" type="button" :disabled="running" @click="$emit('submit')">开始生成</button>
        <button class="secondary-button" type="button" :disabled="running" @click="$emit('reset')">重置</button>
        <button class="secondary-button" type="button" @click="$emit('preset-change', 'balanced')">恢复默认预设</button>
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
  vectorPresets: Object
})

const presetLabels = {
  clean: '清爽',
  balanced: '平衡',
  detailed: '精细',
  ultra: '超清'
}

const emit = defineEmits(['file-change', 'submit', 'reset', 'preset-change', 'update:mode', 'batch-file'])

import { ref } from 'vue'

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
  payload.batch = text
  emit('batch-file', { name: file.name, content: text })
}

const onImageFileChange = async (event) => {
  const file = event.target.files?.[0]
  if (!file) return
  payload.imageFile = file
  const url = await fileToDataUrl(file)
  previewThumb.value = url
  emit('file-change', event)
}

const fileToDataUrl = (file) => new Promise((resolve, reject) => {
  const r = new FileReader()
  r.onload = () => resolve(String(r.result || ''))
  r.onerror = () => reject(new Error('读取失败'))
  r.readAsDataURL(file)
})

</script>
