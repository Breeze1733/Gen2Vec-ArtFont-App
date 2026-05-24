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
        <div class="log-thumb" aria-hidden="true"></div>
        <div class="log-main">
          <h3>{{ item.title }}</h3>
          <p class="muted">{{ item.time }} • {{ item.status }} • {{ item.mode }}</p>
        </div>
        <div class="log-actions">
          <button class="secondary-button small" type="button" @click="$emit('delete-history', item.id)">删除</button>
        </div>
      </article>
      <p v-if="logs.length === 0" class="empty-log">暂无运行记录</p>
    </div>

    <div class="meta-block">
      <h3>输出文件</h3>
      <ul>
        <li v-if="currentFiles && currentFiles.length" v-for="f in currentFiles" :key="f.name" class="output-file-item">
          <strong>{{ f.name }}</strong>
          <button class="secondary-button small" @click="downloadFile(f)">下载</button>
        </li>
        <template v-else>
          <li>原始生成图</li>
          <li>透明 PNG</li>
          <li>SVG 矢量图</li>
          <li>JSON 元数据</li>
          <li>运行日志</li>
        </template>
      </ul>
    </div>

    <div class="meta-block">
      <h3>记录字段</h3>
      <p>生成过程、模型版本、工作流版本、关键参数、耗时、错误信息与输出路径。</p>
    </div>
  </aside>
</template>

<script setup>
const props = defineProps({ logs: Array, currentFiles: { type: Array, required: false } })

const emit = defineEmits(['export-history', 'delete-history'])

const downloadFile = (file) => {
  try {
    if (!file) return
    if (file.isText) {
      const blob = new Blob([file.data], { type: 'text/plain;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = file.name
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      return
    }

    // image data: if already data URL
    if (typeof file.data === 'string' && file.data.startsWith('data:')) {
      const a = document.createElement('a')
      a.href = file.data
      a.download = file.name
      document.body.appendChild(a)
      a.click()
      a.remove()
      return
    }

    // fallback: assume base64 without header, try to create blob
    if (typeof file.data === 'string') {
      const matches = file.data.match(/^data:(.*);base64,(.*)$/)
      if (matches) {
        const mime = matches[1]
        const bstr = atob(matches[2])
        let n = bstr.length
        const u8 = new Uint8Array(n)
        while (n--) u8[n] = bstr.charCodeAt(n)
        const blob = new Blob([u8], { type: mime })
        downloadBlob(blob, file.name)
        return
      }
    }
  } catch (e) {
    console.warn('下载文件失败', e)
  }
}

const downloadBlob = (blob, name) => {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
</script>
