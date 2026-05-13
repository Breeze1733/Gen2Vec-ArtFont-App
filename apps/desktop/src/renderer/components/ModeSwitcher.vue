<template>
  <section class="mode-switch" aria-label="任务类型">
    <button
      v-for="item in modes"
      :key="item.value"
      type="button"
      :class="['mode-button', { active: modelValue === item.value }]"
      @click="$emit('update:modelValue', item.value)"
    >
      {{ item.label }}
    </button>
    <span>支持图形界面与命令行入口</span>
  </section>
</template>

<script setup>
const props = defineProps({
  modes: Array,
  modelValue: String
})

const emit = defineEmits(['update:modelValue'])
</script>
