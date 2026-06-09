<template>
  <div class="group relative flex items-center gap-2.5 h-[52px] px-2.5 rounded-lg bg-surface-raised border border-edge overflow-hidden">
    <!-- Spinner / queued indicator -->
    <div class="w-9 h-9 rounded-md bg-surface flex items-center justify-center flex-shrink-0">
      <div
        v-if="status === 'processing'"
        class="w-[18px] h-[18px] border-2 border-edge-strong border-t-blue-500 rounded-full animate-spin"
      ></div>
      <div
        v-else-if="status === 'enhancing'"
        class="w-[18px] h-[18px] border-2 border-edge-strong border-t-purple-500 rounded-full animate-spin"
      ></div>
      <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-content-muted">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clip-rule="evenodd" />
      </svg>
    </div>

    <!-- Tool name + thin progress. Nothing else — keep it simple. -->
    <div class="flex-1 min-w-0">
      <div class="text-xs font-medium text-content truncate whitespace-nowrap">{{ name }}</div>
      <div class="mt-1.5 h-1 rounded-full bg-surface overflow-hidden">
        <div
          v-if="progress != null"
          class="h-full bg-blue-500 transition-all duration-300"
          :style="{ width: `${Math.round(progress * 100)}%` }"
        ></div>
        <div v-else-if="status !== 'queued'" class="h-full w-1/2 bg-blue-500/60 animate-pulse rounded-full"></div>
      </div>
    </div>

    <!-- Cancel (hover) -->
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
withDefaults(defineProps<{
  /** The tool/model that is running. */
  name: string
  /** 'queued' | 'processing' | 'enhancing' */
  status: string
  /** 0..1 for determinate progress (batches); omit for indeterminate */
  progress?: number | null
  showCancel?: boolean
}>(), {
  progress: null,
  showCancel: true,
})

defineEmits<{
  (e: 'cancel'): void
}>()
</script>
