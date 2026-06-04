<template>
  <div v-if="progress" class="bg-surface-raised border-b border-edge px-4 py-3 flex-shrink-0">
    <div class="flex gap-4 items-center text-sm mb-2">
      <span class="font-semibold text-content">{{ progress.current_operation }}</span>
      <span class="text-content-tertiary">
        {{ progress.processed_files }} / {{ progress.total_files }}
        ({{ progress.progress_percent }}%)
      </span>
      <span v-if="progress.rate > 0" class="text-content-tertiary">
        {{ progress.rate }} files/sec
      </span>
      <span v-if="progress.eta_seconds" class="text-content-tertiary">
        ETA: {{ formatEta(progress.eta_seconds) }}
      </span>
    </div>
    <div class="h-1 bg-surface rounded-sm overflow-hidden">
      <div class="progress-fill h-full bg-gradient-to-r from-green-600 to-lime-500" :style="{ width: `${progress.progress_percent}%` }"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useMediaApi } from '../composables/useMediaApi'

const { getProgressStream } = useMediaApi()

const progress = ref(null)
let eventSource = null

function formatEta(seconds) {
  if (seconds < 60) {
    return `${Math.round(seconds)}s`
  }
  const mins = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  return `${mins}m ${secs}s`
}

onMounted(() => {
  eventSource = getProgressStream()

  eventSource.addEventListener('progress', (event) => {
    try {
      const data = JSON.parse(event.data)
      progress.value = data
    } catch (error) {
      console.error('Failed to parse progress data:', error)
    }
  })

  eventSource.addEventListener('open', () => {
    console.log('Progress stream connected')
  })

  eventSource.onerror = (error) => {
    console.error('Progress stream error:', error)
    // Reconnect after 5 seconds
    setTimeout(() => {
      if (eventSource) {
        eventSource.close()
        eventSource = getProgressStream()
      }
    }, 5000)
  }
})

onUnmounted(() => {
  if (eventSource) {
    eventSource.close()
  }
})
</script>

<style scoped>
.progress-fill {
  transition: width 0.3s ease;
}
</style>
