<template>
  <div class="app-shell">
    <header class="hero">
      <div class="hero-content">
        <p class="eyebrow">Local-first studio</p>
        <h1>矢量艺术字生成器</h1>
        <p class="subtitle">
          管理单条提示词、批量提示词和已有图片矢量化流程，面向后续模型接入与桌面端打包。
        </p>
      </div>

      <div class="hero-panel" aria-label="运行概览">
        <div>
          <span>模型版本</span>
          <strong>v3.1.0</strong>
        </div>
        <div>
          <span>工作流版本</span>
          <strong>flow-2026.05</strong>
        </div>
        <div>
          <span>运行环境</span>
          <strong>本地 GPU</strong>
        </div>
      </div>
    </header>

    <section class="mode-switch" aria-label="任务类型">
      <button
        v-for="item in modes"
        :key="item.value"
        type="button"
        :class="['mode-button', { active: mode === item.value }]"
        @click="mode = item.value"
      >
        {{ item.label }}
      </button>
      <span>支持图形界面与命令行入口</span>
    </section>

    <main class="workspace">
      <section class="panel main-panel">
        <div class="panel-header">
          <div>
            <p class="section-kicker">Generation</p>
            <h2>生成配置</h2>
          </div>
          <div class="status">
            <span class="status-dot"></span>
            <span>{{ running ? 'Running' : 'Idle' }}</span>
          </div>
        </div>

        <div class="panel-body">
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
              <input type="file" accept="image/png,image/jpeg,image/jpg" />
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
            <button class="primary-button" type="button" @click="simulateRun">开始生成</button>
            <button class="secondary-button" type="button" @click="resetForm">重置</button>
          </div>
        </div>
      </section>

      <aside class="panel side-panel">
        <div class="panel-header">
          <div>
            <p class="section-kicker">History</p>
            <h2>运行记录</h2>
          </div>
          <button class="secondary-button small" type="button">导出日志</button>
        </div>

        <div class="log-list">
          <article v-for="item in logs" :key="item.id" class="log-item">
            <div>
              <h3>{{ item.title }}</h3>
              <p>{{ item.time }} / {{ item.status }}</p>
            </div>
            <span>{{ item.mode }}</span>
          </article>
        </div>

        <div class="meta-block">
          <h3>输出文件</h3>
          <ul>
            <li>原始生成图</li>
            <li>透明 PNG</li>
            <li>SVG 矢量图</li>
            <li>JSON 元数据</li>
            <li>运行日志</li>
          </ul>
        </div>

        <div class="meta-block">
          <h3>记录字段</h3>
          <p>生成过程、模型版本、工作流版本、关键参数、耗时、错误信息与输出路径。</p>
        </div>
      </aside>
    </main>

    <section class="panel command-panel">
      <div>
        <p class="section-kicker">CLI</p>
        <h2>命令行入口</h2>
        <p>适用于批处理和自动化脚本，参数与界面保持一致。</p>
      </div>
      <code>art-text-gen --mode batch --input prompts.txt --out ./output</code>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'

const modes = [
  { label: '单条提示词', value: 'single' },
  { label: '批量提示词', value: 'batch' },
  { label: '图片矢量化', value: 'vectorize' }
]

const mode = ref('single')
const running = ref(false)

const payload = reactive({
  text: '',
  prompt: '',
  negative: '',
  batch: '',
  resolution: '1024 x 1024',
  format: 'PNG + SVG',
  seed: 0,
  vector: {
    smooth: 6,
    threshold: 42,
    colors: 8
  }
})

const logs = ref([
  { id: 1, title: '霓虹之风', time: '11:12', status: '完成', mode: '单条' },
  { id: 2, title: '批量：12 条提示词', time: '10:58', status: '完成', mode: '批量' },
  { id: 3, title: '图片矢量化', time: '10:33', status: '失败', mode: '矢量化' }
])

const simulateRun = () => {
  running.value = true

  const title =
    mode.value === 'single'
      ? payload.text || '未命名任务'
      : mode.value === 'batch'
        ? '批处理任务'
        : '图片矢量化任务'

  logs.value.unshift({
    id: Date.now(),
    title,
    time: '刚刚',
    status: '运行中',
    mode: mode.value === 'single' ? '单条' : mode.value === 'batch' ? '批量' : '矢量化'
  })

  window.setTimeout(() => {
    running.value = false
  }, 700)
}

const resetForm = () => {
  payload.text = ''
  payload.prompt = ''
  payload.negative = ''
  payload.batch = ''
  payload.resolution = '1024 x 1024'
  payload.format = 'PNG + SVG'
  payload.seed = 0
  payload.vector.smooth = 6
  payload.vector.threshold = 42
  payload.vector.colors = 8
}
</script>
