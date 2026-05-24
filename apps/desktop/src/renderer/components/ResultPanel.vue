<template>
  <section class="result-panel" v-if="result.original || result.transparent || result.preview || result.image || result.metadata">
    <div class="result-header">
      <div>
        <p class="section-kicker">Result</p>
        <h2>生成结果</h2>
      </div>
      <div class="download-actions">
        <button class="secondary-button" type="button" :disabled="!result.original" @click="$emit('download', 'original')">下载原始图像</button>
        <button class="secondary-button" type="button" :disabled="!result.transparent" @click="$emit('download', 'transparent')">下载透明化图像</button>
        <button class="secondary-button" type="button" :disabled="!result.preview && !result.image" @click="$emit('download', 'preview')">下载矢量化预览</button>
        <button class="secondary-button" type="button" :disabled="!result.svg" @click="$emit('download', 'svg')">下载 SVG</button>
        <button class="secondary-button" type="button" :disabled="!result.metadata" @click="$emit('download', 'json')">下载 JSON</button>
        <button class="secondary-button" type="button" :disabled="!result.original && !result.transparent && !result.preview && !result.image && !result.metadata" @click="$emit('save-all')">打包下载</button>
      </div>
    </div>

    <div class="result-body">
      <div class="preview-block" v-if="result.original || result.transparent || result.preview || result.image">
        <span>图像结果</span>
        <div class="side-by-side">
          <div class="preview-item" v-if="result.original">
            <div class="preview-label">1. 原始图像</div>
            <img :src="result.original" alt="原始图像" />
          </div>
          <div class="preview-item" v-if="result.transparent">
            <div class="preview-label">2. 透明化图像</div>
            <img :src="result.transparent" alt="透明化图像" />
          </div>
          <div class="preview-item" v-if="result.preview || result.image">
            <div class="preview-label">3. 矢量化图像预览</div>
            <img :src="result.preview || result.image" alt="矢量化图像预览" />
          </div>
        </div>
      </div>
      <!--
      <div class="preview-block svg-block" v-if="result.svg">
        <span>SVG 代码（仅文本，不渲染）</span>
        <div class="svg-code">
          <div class="svg-actions">
            <button class="secondary-button small" @click="copySvg" :disabled="!result.svg">复制 SVG 代码</button>
          </div>
          <pre class="code-block"><code>{{ result.svg }}</code></pre>
        </div>
      </div>
      -->
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
