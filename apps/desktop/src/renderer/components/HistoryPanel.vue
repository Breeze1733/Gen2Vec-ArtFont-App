<template>
  <aside class="panel side-panel">
    <div class="panel-header">
      <div>
        <p class="section-kicker">History</p>
        <h2>运行记录</h2>
      </div>
      <button class="secondary-button small" type="button" @click="$emit('export-history')">导出日志</button>
    </div>

    <div class="log-list">
      <article v-for="item in logs" :key="item.id" class="log-item">
        <div>
          <h3>{{ item.title }}</h3>
          <p>{{ item.time }} / {{ item.status }}</p>
        </div>
        <span>{{ item.mode }}</span>
      </article>
      <p v-if="logs.length === 0" class="empty-log">暂无运行记录</p>
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
</template>

<script setup>
const props = defineProps({ logs: Array })

const emit = defineEmits(['export-history'])
</script>
