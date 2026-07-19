<template>
  <!-- Dismissed interstitial: compact notice with restore -->
  <div v-if="dismissed" class="relative mb-3 overflow-hidden">
    <div class="flex items-center gap-3 py-2">
      <div class="text-xs text-content-muted flex-1">
        Remix cleared — prompt changed significantly
      </div>
      <button
        @click="$emit('restore')"
        class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-md text-purple-400 hover:text-purple-300 hover:bg-overlay-subtle transition-colors duration-150 cursor-pointer bg-transparent whitespace-nowrap"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="w-3 h-3"><path fill-rule="evenodd" d="M2 8a6 6 0 1 1 10.735 3.697l-.001.002-.001.001-2.086 2.456a.75.75 0 1 1-1.143-.975l1.608-1.89A4.5 4.5 0 1 0 3.5 8a.75.75 0 0 1-1.5 0Z" clip-rule="evenodd" /></svg>
        Restore
      </button>
      <button
        @click="$emit('dismiss')"
        class="p-0.5 text-content-muted hover:text-content transition-colors duration-150 rounded-md hover:bg-overlay-subtle cursor-pointer"
        title="Dismiss"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
          <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
        </svg>
      </button>
    </div>
    <!-- Countdown bar -->
    <div class="absolute bottom-0 left-0 h-px bg-purple-500/40 transition-all duration-1000 ease-linear" :style="{ width: countdownPercent + '%' }" />
  </div>

  <!-- Normal remix banner: hairline row, no filled banner -->
  <div v-else class="relative mb-3">
    <div class="flex items-start gap-3">
      <div
        class="flex-shrink-0 w-14 h-14 rounded-media bg-matte overflow-hidden hover:ring-1 hover:ring-purple-400/60 transition-shadow duration-150 cursor-pointer"
        draggable="true"
        @dragstart="onDragStart"
        @dragend="handleDragEnd"
        @click="$emit('view-source')"
        title="View source image — drag to reference images"
      >
        <img
          :src="thumbnailUrl"
          alt="Inspiration source"
          class="w-full h-full object-cover pointer-events-none"
        />
      </div>

      <div class="min-w-0 pt-1 pr-6 overflow-hidden" style="flex: 1 1 0%;">
        <div class="text-xs font-medium text-purple-400 mb-0.5">Remix of</div>
        <div v-if="promptSnippet" class="text-[11px] text-content-muted leading-tight line-clamp-3">{{ promptSnippet }}</div>

        <!-- Action chips -->
        <div class="flex flex-wrap gap-1.5 mt-2">
          <button
            @click="$emit('copy-prompt')"
            class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-md text-content-secondary hover:text-content hover:bg-overlay-subtle transition-colors duration-150 cursor-pointer bg-transparent"
            title="Use original prompt (with wildcards)"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="w-3 h-3"><path d="M5.5 3.5A1.5 1.5 0 0 1 7 2h2.879a1.5 1.5 0 0 1 1.06.44l2.122 2.12a1.5 1.5 0 0 1 .439 1.061V9.5A1.5 1.5 0 0 1 12 11V8.621a3 3 0 0 0-.879-2.121L9 4.379A3 3 0 0 0 6.879 3.5H5.5Z" /><path d="M4 5a1.5 1.5 0 0 0-1.5 1.5v6A1.5 1.5 0 0 0 4 14h5a1.5 1.5 0 0 0 1.5-1.5V8.621a1.5 1.5 0 0 0-.44-1.06L7.94 5.439A1.5 1.5 0 0 0 6.878 5H4Z" /></svg>
            Use Prompt
          </button>

          <button
            v-if="hasExactPrompt"
            @click="$emit('copy-exact-prompt')"
            class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-md text-content-secondary hover:text-content hover:bg-overlay-subtle transition-colors duration-150 cursor-pointer bg-transparent"
            title="Use the exact rendered prompt (wildcards expanded)"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="w-3 h-3"><path fill-rule="evenodd" d="M11.986 3H12a2 2 0 0 1 2 2v6a2 2 0 0 1-1.5 1.937V7A2.5 2.5 0 0 0 10 4.5H4.063A2 2 0 0 1 6 3h.014A2.25 2.25 0 0 1 8.25 1h1.5a2.25 2.25 0 0 1 2.236 2ZM10.5 4v-.75a.75.75 0 0 0-.75-.75h-1.5a.75.75 0 0 0-.75.75V4h3Z" clip-rule="evenodd" /><path fill-rule="evenodd" d="M2 7a1 1 0 0 1 1-1h7a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V7Zm6.585 1.08a.75.75 0 0 1 .336 1.005l-1.75 3.5a.75.75 0 0 1-1.16.234l-1.25-1.25a.75.75 0 0 1 1.06-1.06l.522.521 1.238-2.475a.75.75 0 0 1 1.004-.476Z" clip-rule="evenodd" /></svg>
            Use Exact Prompt
          </button>

          <button
            v-if="showUseImage"
            @click="$emit('use-image')"
            class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-md text-content-secondary hover:text-content hover:bg-overlay-subtle transition-colors duration-150 cursor-pointer bg-transparent"
            title="Add this image to reference images"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="w-3 h-3"><path d="M2 4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4Zm10.5 5.707a.5.5 0 0 0-.146-.353l-2.5-2.5a.5.5 0 0 0-.708 0L7.5 8.5 6.354 7.354a.5.5 0 0 0-.708 0l-2.5 2.5a.5.5 0 0 0-.146.353V12a.5.5 0 0 0 .5.5h9a.5.5 0 0 0 .5-.5V9.707ZM12 5a1 1 0 1 1-2 0 1 1 0 0 1 2 0Z" /></svg>
            Use Image
          </button>

          <button
            v-if="seed != null"
            @click="$emit('use-seed')"
            class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded-md text-content-secondary hover:text-content hover:bg-overlay-subtle transition-colors duration-150 cursor-pointer bg-transparent"
            title="Use the same seed for reproducible results"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="w-3 h-3"><path fill-rule="evenodd" d="M8 1a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 8 1ZM10.5 8a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0ZM12.95 4.11a.75.75 0 1 0-1.06-1.06l-1.062 1.06a.75.75 0 0 0 1.061 1.06l1.06-1.06ZM15 8a.75.75 0 0 1-.75.75h-1.5a.75.75 0 0 1 0-1.5h1.5A.75.75 0 0 1 15 8ZM11.89 12.95a.75.75 0 0 0 1.06-1.06l-1.06-1.062a.75.75 0 0 0-1.06 1.061l1.06 1.06ZM8 12a.75.75 0 0 1 .75.75v1.5a.75.75 0 0 1-1.5 0v-1.5A.75.75 0 0 1 8 12ZM4.11 11.89a.75.75 0 1 0-1.06 1.06l1.06 1.06a.75.75 0 1 0 1.06-1.06l-1.06-1.06ZM4 8a.75.75 0 0 1-.75.75h-1.5a.75.75 0 0 1 0-1.5h1.5A.75.75 0 0 1 4 8ZM4.11 4.11a.75.75 0 0 0-1.06-1.06l-1.06 1.06a.75.75 0 1 0 1.06 1.06l1.06-1.06Z" clip-rule="evenodd" /></svg>
            Use Seed
          </button>
        </div>
      </div>

      <button
        @click="$emit('dismiss')"
        class="absolute top-1 right-0 p-1 text-content-muted hover:text-content transition-colors duration-150 rounded-md hover:bg-overlay-subtle cursor-pointer"
        title="Dismiss"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
          <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
import { createDragPreview, handleDragEnd } from '../../composables/useDragPreview'

const props = defineProps<{
  thumbnailUrl: string
  promptSnippet: string
  mediaId: number
  currentPrompt?: string
  renderedPrompt?: string
  showUseImage?: boolean
  seed?: number | null
  dismissed?: boolean
}>()

const emit = defineEmits<{
  (e: 'dismiss'): void
  (e: 'restore'): void
  (e: 'view-source'): void
  (e: 'copy-prompt'): void
  (e: 'copy-exact-prompt'): void
  (e: 'use-image'): void
  (e: 'use-seed'): void
  (e: 'expired'): void
}>()

// Show "Copy Exact Prompt" only when rendered differs from original
const hasExactPrompt = computed(() => {
  return props.renderedPrompt && props.renderedPrompt !== props.promptSnippet
})

// Countdown for dismissed interstitial (30s)
const DISMISS_DURATION = 30000
const countdownPercent = ref(100)
let countdownInterval: ReturnType<typeof setInterval> | null = null
let expireTimeout: ReturnType<typeof setTimeout> | null = null

function startCountdown() {
  stopCountdown()
  const startTime = Date.now()
  countdownPercent.value = 100

  countdownInterval = setInterval(() => {
    const elapsed = Date.now() - startTime
    countdownPercent.value = Math.max(0, 100 - (elapsed / DISMISS_DURATION) * 100)
  }, 200)

  expireTimeout = setTimeout(() => {
    stopCountdown()
    emit('expired')
  }, DISMISS_DURATION)
}

function stopCountdown() {
  if (countdownInterval) { clearInterval(countdownInterval); countdownInterval = null }
  if (expireTimeout) { clearTimeout(expireTimeout); expireTimeout = null }
}

watch(() => props.dismissed, (val) => {
  if (val) startCountdown()
  else stopCountdown()
}, { immediate: true })

onUnmounted(stopCountdown)

function onDragStart(event: DragEvent) {
  createDragPreview(event, props.thumbnailUrl, props.mediaId)
}
</script>
