<script setup lang="ts">
import Spinner from './Spinner.vue'
defineProps<{ label: string; busy?: boolean; warning?: boolean; disabled?: boolean }>()
defineEmits<{ click: [MouseEvent] }>()
</script>
<template>
  <button type="button" :disabled="disabled" :aria-label="label" @click="$emit('click', $event)"
    class="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 ring-accent/60 disabled:opacity-60 disabled:cursor-default"
    :class="warning ? 'border-amber-500/50 text-amber-500 bg-amber-500/10' : 'border-accent/50 text-accent-hi bg-accent/15 hover:bg-accent/25'">
    <Spinner v-if="busy" size="sm" />
    <svg v-else class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4" /></svg>
    <span>{{ label }}</span>
  </button>
</template>
