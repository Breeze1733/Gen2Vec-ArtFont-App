<template>
  <section class="result-panel" v-if="result.svg || result.image || result.metadata || result.original">
    <div class="result-header">
      <div>
        <p class="section-kicker">Result</p>
        <h2>生成结果</h2>
      </div>
      <div class="download-actions">
        <button class="secondary-button" type="button" :disabled="!result.image" @click="$emit('download', 'png')">下载 PNG</button>
        <button class="secondary-button" type="button" :disabled="!result.svg" @click="$emit('download', 'svg')">下载 SVG</button>
        <button class="secondary-button" type="button" :disabled="!result.metadata" @click="$emit('download', 'json')">下载 JSON</button>
        <button class="secondary-button" type="button" :disabled="!result.image && !result.svg && !result.metadata" @click="$emit('save-all')">保存全部</button>
        <button class="secondary-button small" type="button" :disabled="!result.svg" @click="$emit('open-svg', 'raw')">打开原始 SVG</button>
        <button class="secondary-button small" type="button" :disabled="!result.svg" @click="$emit('open-svg', 'clean')">打开清理后 SVG</button>
      </div>
    </div>

    <div class="result-body">
      <div class="preview-block" v-if="result.image || result.original">
        <span>PNG 预览 / 原始</span>
        <div class="side-by-side">
          <div class="preview-item" v-if="result.image">
            <div class="preview-label">生成 PNG</div>
            <img :src="result.image" alt="生成预览" />
          </div>
          <div class="preview-item" v-if="result.original">
            <div class="preview-label">原始图像</div>
            <img :src="result.original" alt="原始图像" />
          </div>
        </div>
      </div>
      <div class="preview-block svg-block" v-if="result.svg">
        <span>SVG 代码（仅文本，不渲染）</span>
        <div class="svg-code">
          <div class="svg-actions">
            <button class="secondary-button small" @click="copySvg" :disabled="!result.svg">复制 SVG 代码</button>
          </div>
          <pre class="code-block"><code>{{ result.svg }}</code></pre>
        </div>
      </div>
      <div class="metadata-block" v-if="result.metadata">
        <h3>元数据</h3>
        <pre>{{ result.metadata }}</pre>
        <div class="comparison" v-if="result.metadata && result.metadata.quality">
          <h4>对比指标</h4>
          <ul>
            <li>Mask IOU: {{ result.metadata.quality.mask_iou ?? 'N/A' }}</li>
            <li>轮廓 Chamfer 距离 (px): {{ result.metadata.quality.contour_chamfer_px ?? 'N/A' }}</li>
          </ul>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
const props = defineProps({
  result: Object
})

const emit = defineEmits(['download', 'save-all', 'open-svg'])

const copySvg = async () => {
  if (!props.result || !props.result.svg) return
  try {
    await navigator.clipboard.writeText(props.result.svg)
  } catch (e) {
    console.warn('复制 SVG 失败', e)
  }
}
</script>
