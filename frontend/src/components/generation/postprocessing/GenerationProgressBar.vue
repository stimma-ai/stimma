<template>
  <div class="group relative flex items-center gap-2.5 h-[52px] px-2.5 rounded-lg bg-surface-raised border border-edge overflow-hidden">
    <!-- Thumbnail slot (spinner while generating) -->
    <div class="w-9 h-9 rounded-md bg-surface flex items-center justify-center flex-shrink-0 overflow-hidden">
      <div
        v-if="status === 'processing'"
        class="w-4.5 h-4.5 w-[18px] h-[18px] border-2 border-edge-strong border-t-blue-500 rounded-full animate-spin"
      ></div>
      <div
        v-else-if="status === 'enhancing'"
        class="w-[18px] h-[18px] border-2 border-edge-strong border-t-purple-500 rounded-full animate-spin"
      ></div>
      <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-content-muted">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clip-rule="evenodd" />
      </svg>
    </div>

    <!-- Label + thin progress -->
    <div class="flex-1 min-w-0">
      <div class="flex items-baseline gap-2">
        <span class="text-xs font-medium text-content">{{ statusLabel }}</span>
        <span v-if="sublabel" class="text-[11px] text-content-muted truncate">{{ sublabel }}</span>
      </div>
      <div class="mt-1.5 h-1 rounded-full bg-surface overflow-hidden">
        <div
          v-if="progress != null"
          class="h-full bg-blue-500 transition-all duration-300"
          :style="{ width: `${Math.round(progress * 100)}%` }"
        ></div>
        <div v-else-if="status !== 'queued'" class="h-full w-1/2 bg-blue-500/60 animate-pulse rounded-full"></div>
      </div>
    </div>

    <!-- Info + Cancel -->
    <button
      v-if="showInfo"
      @click.stop="$emit('info')"
      class="w-6 h-6 flex items-center justify-center rounded text-content-muted/50 hover:text-content-secondary transition-colors opacity-0 group-hover:opacity-100"
      title="Show info"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
        <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clip-rule="evenodd" />
      </svg>
    </button>
    <button
      v-if="showCancel"
      @click.stop="$emit('cancel')"
      class="w-6 h-6 flex items-center justify-center rounded text-content-muted/50 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100"
      title="Cancel"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
        <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
      </svg>
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  /** 'queued' | 'processing' | 'enhancing' */
  status: string
  /** e.g. the prompt snippet */
  sublabel?: string
  /** 0..1 for determinate progress (batches); omit for indeterminate */
  progress?: number | null
  label?: string
  showCancel?: boolean
  showInfo?: boolean
}>(), {
  sublabel: '',
  progress: null,
  label: '',
  showCancel: true,
  showInfo: true,
})

defineEmits<{
  (e: 'cancel'): void
  (e: 'info'): void
}>()

const statusLabel = computed(() => {
  if (props.label) return props.label
  if (props.status === 'enhancing') return 'Enhancing prompt'
  if (props.status === 'processing') return 'Generating'
  return 'Queued'
})
</script>
