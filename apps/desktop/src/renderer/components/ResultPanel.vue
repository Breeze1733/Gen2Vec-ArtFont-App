<template>
  <section class="result-panel" v-if="result.svg || result.image || result.metadata">
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
      </div>
    </div>

    <div class="result-body">
      <div class="preview-block" v-if="result.image">
        <span>PNG 预览</span>
        <img :src="result.image" alt="生成预览" />
      </div>
      <div class="preview-block svg-block" v-if="result.svg">
        <span>SVG 预览</span>
        <div class="svg-preview" v-html="result.svg"></div>
      </div>
      <div class="metadata-block" v-if="result.metadata">
        <h3>元数据</h3>
        <pre>{{ result.metadata }}</pre>
      </div>
    </div>
  </section>
</template>

<script setup>
const props = defineProps({
  result: Object
})

const emit = defineEmits(['download', 'save-all'])
</script>
