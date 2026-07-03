<template>
  <div class="w-4 h-4" v-html="svg" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { PAINT_TOOL_ICONS, type PaintToolIconName } from '../../utils/paintToolIcons'
import { sanitizeSvg } from '../../utils/sanitizeHtml'

const props = defineProps<{ name: PaintToolIconName }>()

const svg = computed(() => {
  const def = PAINT_TOOL_ICONS[props.name]
  if (!def) return ''
  return sanitizeSvg(
    `<svg viewBox="${def.viewBox}" fill="none" stroke-width="1.5" stroke="currentColor">${def.inner}</svg>`
  )
})
</script>
