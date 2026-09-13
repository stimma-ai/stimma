<template>
  <span class="font-mono text-[10px] font-semibold bg-surface-raised rounded-md w-8 h-8 shrink-0 flex items-center justify-center" :class="color">{{ name.split('.').pop()?.toUpperCase().slice(0, 5) || 'FILE' }}</span>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { fileKind } from '../../utils/fileRefs'
const props = defineProps<{ name: string; mime?: string }>()
const colors: Record<string, string> = {
  text: 'text-[rgb(var(--file-type-code-rgb))]',
  table: 'text-[rgb(var(--file-type-table-rgb))]',
  markdown: 'text-[rgb(var(--file-type-markdown-rgb))]',
  zip: 'text-[rgb(var(--file-type-archive-rgb))]',
  json: 'text-[rgb(var(--file-type-json-rgb))]',
  image: 'text-[rgb(var(--file-type-image-rgb))]',
}
const color = computed(() => colors[fileKind(props.name, props.mime)] || 'text-content-secondary')
</script>
