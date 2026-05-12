<template>
  <div class="page">
    <header class="hero">
      <div>
        <p class="eyebrow">Local-first studio</p>
        <h1>矢量艺术字生成应用</h1>
        <p class="subtitle">单条提示词、批量提示词、已有图片矢量化三种模式一站式管理。</p>
      </div>
      <div class="hero-card">
        <div>
          <p class="hero-label">模型版本</p>
          <p class="hero-value">v3.1.0 · Open Model</p>
        </div>
        <div>
          <p class="hero-label">工作流版本</p>
          <p class="hero-value">flow-2026.05</p>
        </div>
        <div>
          <p class="hero-label">运行环境</p>
          <p class="hero-value">本地 GPU · 低延迟</p>
        </div>
      </div>
    </header>

    <section class="mode-switch">
      <button
        v-for="item in modes"
        :key="item.value"
        :class="['mode-pill', { active: mode === item.value }]"
        @click="mode = item.value"
      >
        {{ item.label }}
      </button>
      <span class="mode-note">支持 GUI 与命令行入口</span>
    </section>

    <main class="grid">
      <section class="panel">
        <div class="panel-header">
          <h2>生成配置</h2>
          <div class="status">
            <span class="dot"></span>
            <span>Idle</span>
          </div>
        </div>

        <div class="panel-body">
          <div v-if="mode === 'single'" class="form">
            <div class="field">
              <label>文字内容</label>
              <input v-model="payload.text" type="text" placeholder="例如：霓虹之风" />
            </div>
            <div class="field">
              <label>风格提示词</label>
              <input v-model="payload.prompt" type="text" placeholder="例如：霓虹渐变、金属质感" />
            </div>
          </div>

          <div v-else-if="mode === 'batch'" class="form">
            <div class="field">
              <label>批量提示词</label>
              <textarea
                v-model="payload.batch"
                rows="5"
                placeholder="每行一条：\n晨曦之城 | 清透玻璃风\n深海波纹 | 水纹渐变"
              ></textarea>
            </div>
          </div>

          <div v-else class="form">
            <div class="field">
              <label>选择图片</label>
              <input type="file" />
              <p class="hint">支持 PNG / JPG，自动生成透明 PNG 与 SVG。</p>
            </div>
          </div>

          <div class="form two-col">
            <div class="field">
              <label>负面提示词</label>
              <input v-model="payload.negative" type="text" placeholder="例如：模糊、锯齿、断裂" />
            </div>
            <div class="field">
              <label>分辨率</label>
              <select v-model="payload.resolution">
                <option>1024 x 1024</option>
                <option>1024 x 768</option>
                <option>2048 x 2048</option>
              </select>
            </div>
            <div class="field">
              <label>输出格式</label>
              <select v-model="payload.format">
                <option>PNG + SVG</option>
                <option>SVG Only</option>
                <option>PNG + JSON</option>
              </select>
            </div>
            <div class="field">
              <label>随机种子</label>
              <input v-model="payload.seed" type="number" placeholder="0 表示随机" />
            </div>
          </div>

          <div class="form">
            <div class="field">
              <label>矢量化参数</label>
              <div class="vector-grid">
                <div>
                  <span>平滑度</span>
                  <input v-model="payload.vector.smooth" type="range" min="1" max="10" />
                </div>
                <div>
                  <span>阈值</span>
                  <input v-model="payload.vector.threshold" type="range" min="1" max="100" />
                </div>
                <div>
                  <span>颜色数</span>
                  <input v-model="payload.vector.colors" type="number" min="2" max="32" />
                </div>
              </div>
            </div>
          </div>

          <div class="actions">
            <button class="primary" @click="simulateRun">开始生成</button>
            <button class="ghost" @click="resetForm">重置</button>
          </div>
        </div>
      </section>

      <aside class="panel side">
        <div class="panel-header">
          <h2>运行记录</h2>
          <button class="ghost small">导出日志</button>
        </div>
        <div class="panel-body">
          <div class="log">
            <div class="log-item" v-for="item in logs" :key="item.id">
              <div>
                <p class="log-title">{{ item.title }}</p>
                <p class="log-meta">{{ item.time }} · {{ item.status }}</p>
              </div>
              <span class="tag">{{ item.mode }}</span>
            </div>
          </div>

          <div class="meta-block">
            <h3>输出文件</h3>
            <ul>
              <li>原始生成图</li>
              <li>透明 PNG</li>
              <li>SVG 矢量图</li>
              <li>PNG 预览图</li>
              <li>JSON 元数据</li>
              <li>日志文件</li>
            </ul>
          </div>

          <div class="meta-block">
            <h3>记录字段</h3>
            <p>生成过程、模型版本、工作流版本、关键参数、耗时、错误信息、输出路径。</p>
          </div>
        </div>
      </aside>
    </main>

    <section class="panel footer">
      <div>
        <h2>命令行入口</h2>
        <p class="hint">适用于批处理和自动化脚本，参数与界面同步。</p>
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
  { label: '已有图片矢量化', value: 'vectorize' }
]

const mode = ref('single')

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
  { id: 2, title: '批量：4 条提示词', time: '10:58', status: '完成', mode: '批量' },
  { id: 3, title: '图片矢量化', time: '10:33', status: '失败', mode: '矢量化' }
])

const simulateRun = () => {
  const label = mode.value === 'single' ? payload.text || '未命名任务' : '批处理任务'
  logs.value.unshift({
    id: Date.now(),
    title: label,
    time: '刚刚',
    status: '运行中',
    mode: mode.value === 'single' ? '单条' : mode.value === 'batch' ? '批量' : '矢量化'
  })
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

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 28px;
  padding: 32px clamp(20px, 5vw, 48px) 60px;
}

.hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
}

.eyebrow {
  text-transform: uppercase;
  letter-spacing: 0.2em;
  font-size: 12px;
  color: var(--text-muted);
}

h1 {
  margin: 8px 0 10px;
  font-size: clamp(32px, 5vw, 48px);
}

.subtitle {
  max-width: 520px;
  color: var(--text-muted);
}

.hero-card {
  display: grid;
  gap: 14px;
  padding: 18px 20px;
  border-radius: 16px;
  background: var(--panel);
  min-width: 240px;
  box-shadow: var(--shadow-soft);
}

.hero-label {
  font-size: 12px;
  color: var(--text-muted);
  margin: 0;
}

.hero-value {
  margin: 4px 0 0;
  font-weight: 600;
}

.mode-switch {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}

.mode-pill {
  border-radius: 999px;
  padding: 8px 16px;
  border: 1px solid transparent;
  background: var(--panel);
  color: var(--text);
  cursor: pointer;
  transition: 0.2s ease;
}

.mode-pill.active {
  border-color: var(--accent);
  background: var(--accent-soft);
  color: var(--accent-strong);
}

.mode-note {
  color: var(--text-muted);
  font-size: 14px;
}

.grid {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
  gap: 24px;
}

.panel {
  background: var(--panel);
  border-radius: 18px;
  padding: 22px;
  box-shadow: var(--shadow-soft);
  border: 1px solid rgba(255, 255, 255, 0.3);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #3bd66f;
  box-shadow: 0 0 12px rgba(59, 214, 111, 0.7);
}

.panel-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.form {
  display: grid;
  gap: 16px;
}

.two-col {
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
}

.field {
  display: grid;
  gap: 8px;
}

label {
  font-size: 14px;
  font-weight: 600;
}

input,
select,
textarea {
  border-radius: 10px;
  border: 1px solid transparent;
  padding: 10px 12px;
  background: #fff;
  font: inherit;
  box-shadow: inset 0 0 0 1px rgba(17, 24, 39, 0.06);
}

textarea {
  resize: vertical;
}

.hint {
  font-size: 12px;
  color: var(--text-muted);
}

.vector-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}

.vector-grid span {
  display: block;
  font-size: 12px;
  margin-bottom: 6px;
  color: var(--text-muted);
}

.actions {
  display: flex;
  gap: 12px;
}

.primary {
  background: var(--accent-strong);
  color: #fff;
  border: none;
  padding: 12px 20px;
  border-radius: 12px;
  cursor: pointer;
}

.ghost {
  background: transparent;
  border: 1px solid rgba(0, 0, 0, 0.1);
  color: var(--text);
  padding: 12px 18px;
  border-radius: 12px;
  cursor: pointer;
}

.ghost.small {
  padding: 6px 12px;
  font-size: 12px;
}

.side {
  min-height: 100%;
}

.log {
  display: grid;
  gap: 12px;
}

.log-item {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.7);
}

.log-title {
  margin: 0;
  font-weight: 600;
}

.log-meta {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}

.tag {
  align-self: center;
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent-strong);
  font-size: 12px;
}

.meta-block {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(0, 0, 0, 0.06);
}

.meta-block ul {
  margin: 8px 0 0;
  padding-left: 18px;
  color: var(--text-muted);
}

.footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

code {
  background: #111827;
  color: #f8fafc;
  padding: 10px 14px;
  border-radius: 12px;
}

@media (max-width: 960px) {
  .grid {
    grid-template-columns: 1fr;
  }
  .hero {
    align-items: flex-start;
  }
  .panel,
  .hero-card {
    width: 100%;
  }
}
</style>