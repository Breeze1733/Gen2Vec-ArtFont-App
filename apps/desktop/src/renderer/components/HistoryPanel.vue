<template>
  <aside class="sidebar">
    <div class="sidebar-header">
      <p class="section-kicker">History</p>
      <h2>运行记录</h2>
      <button class="secondary-button small" type="button" @click="$emit('export-history')">导出日志</button>
    </div>

    <div class="sidebar-content">
      <article
        v-for="item in logs"
        :key="item.id"
        :class="['log-item', { clickable: item.status !== '运行中' }]"
        @click="item.status !== '运行中' && $emit('restore-history', item.id)"
      >
        <div class="log-thumb" aria-hidden="true">
          <img v-if="item.thumb" :src="item.thumb" alt="" />
          <span v-else class="log-thumb-icon">{{ item.mode === '矢量化' ? '📐' : '🎨' }}</span>
        </div>
        <div class="log-main">
          <h3>{{ item.title }}</h3>
          <p class="muted">{{ item.time }} • {{ item.status }} • {{ item.mode }}</p>
        </div>
        <div class="log-actions">
          <button class="secondary-button tiny" type="button" @click.stop="$emit('delete-history', item.id)">删除</button>
        </div>
      </article>
      <p v-if="logs.length === 0" class="empty-log">暂无运行记录</p>
    </div>
  </aside>
</template>

<script setup>
const props = defineProps({ logs: Array, currentFiles: { type: Array, required: false } })

const emit = defineEmits(['export-history', 'delete-history', 'restore-history'])
</script>

<style scoped>
.sidebar {
  width: 100%;
  height: 615px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: var(--shadow-soft);
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.sidebar-header h2 {
  margin: 0;
  font-size: 16px;
}

.sidebar-content {
  padding: 12px;
  overflow-y: auto;
  flex: 1;
}

.log-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.68);
  margin-bottom: 8px;
  transition: border-color 0.15s, background 0.15s;
}

.log-item.clickable {
  cursor: pointer;
}

.log-item.clickable:hover {
  border-color: rgba(15, 118, 110, 0.3);
  background: rgba(15, 118, 110, 0.04);
}

.log-thumb {
  width: 40px;
  height: 40px;
  border-radius: 4px;
  background: rgba(31, 41, 55, 0.04);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 10px;
  flex-shrink: 0;
  overflow: hidden;
}

.log-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.log-thumb-icon {
  font-size: 18px;
}

.log-main {
  flex: 1;
  min-width: 0;
}

.log-main h3 {
  margin: 0;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.log-main .muted {
  margin: 2px 0 0;
  color: var(--text-muted);
  font-size: 11px;
}

.empty-log {
  color: var(--text-muted);
  font-size: 13px;
  padding: 16px 0;
  text-align: center;
}
</style>
