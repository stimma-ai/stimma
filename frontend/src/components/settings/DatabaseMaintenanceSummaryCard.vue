<template>
  <div class="rounded-lg border p-3" :class="toneClass">
    <p class="text-xs text-content-tertiary">{{ label }}</p>
    <p class="mt-1 text-xl font-semibold" :class="valueClass">{{ Number(value || 0).toLocaleString() }}</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: Number, required: true },
  tone: { type: String, default: 'neutral' },
})

const toneClass = computed(() => props.tone === 'blue'
  ? 'border-blue-500/50 bg-blue-500/15'
  : 'border-edge-subtle bg-overlay-light')
const valueClass = computed(() => props.tone === 'blue' ? 'text-blue-500' : 'text-content')
</script>
