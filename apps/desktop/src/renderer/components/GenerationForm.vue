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

      <div v-if="mode === 'single'" class="form-grid">
        <label class="field">
          <span>文字内容</span>
          <input v-model="payload.text" type="text" placeholder="例如：霓虹之风" />
        </label>
        <label class="field">
          <span>风格提示词</span>
          <input v-model="payload.prompt" type="text" placeholder="例如：霓虹渐变、金属质感" />
        </label>
      </div>

      <div v-else-if="mode === 'batch'" class="form-grid">
        <label class="field">
          <span>批量提示词</span>
          <textarea
            v-model="payload.batch"
            rows="5"
            placeholder="每行一条：&#10;晨曦之城 | 透明玻璃风&#10;深海波纹 | 水纹渐变"
          ></textarea>
        </label>
      </div>

      <div v-else class="form-grid">
        <label class="field">
          <span>选择图片</span>
          <input type="file" accept="image/png,image/jpeg,image/jpg" @change="$emit('file-change', $event)" />
          <small>支持 PNG / JPG，后续可自动生成透明 PNG 与 SVG。</small>
        </label>
      </div>

      <div class="form-grid two-columns">
        <label class="field">
          <span>负面提示词</span>
          <input v-model="payload.negative" type="text" placeholder="例如：模糊、锯齿、断裂" />
        </label>
        <label class="field">
          <span>分辨率</span>
          <select v-model="payload.resolution">
            <option>1024 x 1024</option>
            <option>1024 x 768</option>
            <option>2048 x 2048</option>
          </select>
        </label>
        <label class="field">
          <span>输出格式</span>
          <select v-model="payload.format">
            <option>PNG + SVG</option>
            <option>SVG Only</option>
            <option>PNG + JSON</option>
          </select>
        </label>
        <label class="field">
          <span>随机种子</span>
          <input v-model.number="payload.seed" type="number" placeholder="0 表示随机" />
        </label>
      </div>

      <div class="vector-settings">
        <label>
          <span>平滑度</span>
          <input v-model.number="payload.vector.smooth" type="range" min="1" max="10" />
        </label>
        <label>
          <span>阈值</span>
          <input v-model.number="payload.vector.threshold" type="range" min="1" max="100" />
        </label>
        <label class="compact-number">
          <span>颜色数</span>
          <input v-model.number="payload.vector.colors" type="number" min="2" max="32" />
        </label>
      </div>

      <div class="actions">
        <button class="primary-button" type="button" :disabled="running" @click="$emit('submit')">开始生成</button>
        <button class="secondary-button" type="button" :disabled="running" @click="$emit('reset')">重置</button>
      </div>
    </div>
  </section>
</template>

<script setup>
const props = defineProps({
  mode: String,
  payload: Object,
  running: Boolean,
  error: String
})

const emit = defineEmits(['file-change', 'submit', 'reset'])
</script>
