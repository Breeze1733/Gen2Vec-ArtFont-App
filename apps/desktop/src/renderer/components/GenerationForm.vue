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

      <div v-if="mode === 'vectorize'" class="vector-settings">
        <label>
          <span>矢量化预设</span>
          <small>选择一个内置预设来快速设置参数。</small>
          <select v-model="payload.vector.preset" @change="$emit('preset-change', payload.vector.preset)">
            <option v-for="(value, key) in vectorPresets" :key="key" :value="key">{{ presetLabels[key] || key }}</option>
          </select>
        </label>
        <label>
          <span>颜色精度</span>
          <small>控制色彩分层数量，数值越大细节越丰富。</small>
          <input
            v-model.number="payload.vector.color_precision"
            type="number"
            min="1"
            max="8"
            step="1"
          />
        </label>
        <label>
          <span>斑点过滤</span>
          <small>过滤小噪点与斑点，数值越大清晰越干净。</small>
          <input
            v-model.number="payload.vector.filter_speckle"
            type="number"
            min="1"
            max="20"
            step="1"
          />
        </label>
        <label>
          <span>拐角阈值</span>
          <small>控制拐角保留和折线优化，数值越小保留越多细节。</small>
          <input
            v-model.number="payload.vector.corner_threshold"
            type="number"
            min="1"
            max="120"
            step="1"
          />
        </label>
        <label>
          <span>长度阈值</span>
          <small>控制短路径过滤，数值越大删除越多短路径。</small>
          <input
            v-model.number="payload.vector.length_threshold"
            type="number"
            min="1"
            max="20"
            step="1"
          />
        </label>
        <label>
          <span>图层差异</span>
          <small>控制相邻图层合并差异，数值越小保留越多图层。</small>
          <input
            v-model.number="payload.vector.layer_difference"
            type="number"
            min="1"
            max="30"
            step="1"
          />
        </label>
        <label class="compact-number">
          <span>放大倍数</span>
          <small>预处理放大输入图像以提升细节保留。</small>
          <input v-model.number="payload.vector.scale" type="number" min="1" max="4" />
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
  error: String,
  vectorPresets: Object
})

const presetLabels = {
  clean: 'clean（清爽）',
  balanced: 'balanced（平衡）',
  detailed: 'detailed（精细）',
  ultra: 'ultra（超清）'
}

const emit = defineEmits(['file-change', 'submit', 'reset', 'preset-change'])

</script>
