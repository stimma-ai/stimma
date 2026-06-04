<template>
  <div class="scored-results bg-surface rounded-lg p-4 max-w-4xl">
    <!-- Header -->
    <div class="flex items-center gap-2 mb-3 text-sm text-content-tertiary">
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
      </svg>
      <span>Scored Results</span>
      <span v-if="scoredData.criteria" class="text-content-muted">— {{ scoredData.criteria }}</span>
    </div>

    <!-- Grid of scored images -->
    <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
      <div
        v-for="item in scoredData.items"
        :key="item.media_id"
        class="relative group cursor-pointer"
      >
        <!-- Rank badge -->
        <div class="absolute top-1 left-1 z-10 bg-black/70 text-content text-xs font-bold px-1.5 py-0.5 rounded pointer-events-none">
          #{{ item.rank }}
        </div>

        <!-- Score badge -->
        <div
          class="absolute top-1 right-1 z-10 text-xs font-bold px-1.5 py-0.5 rounded pointer-events-none"
          :class="getScoreClass(item.total_score)"
        >
          {{ formatScore(item.total_score) }}
        </div>

        <!-- Image - using MediaImage for drag-drop and context menu support -->
        <div class="aspect-square bg-surface-raised rounded overflow-hidden">
          <MediaImage
            :media-id="item.media_id"
            :thumbnail="true"
            :thumbnail-size="256"
            container-class="w-full h-full"
            @click="$emit('view-image', item.media_id)"
          />
        </div>

        <!-- Error indicator -->
        <div v-if="item.error" class="absolute inset-0 bg-red-500/15 flex items-center justify-center pointer-events-none">
          <span class="text-red-500 text-xs font-medium">Error</span>
        </div>

        <!-- Score details on hover -->
        <div class="absolute inset-0 bg-black/80 opacity-0 group-hover:opacity-100 transition-opacity p-2 flex flex-col justify-end text-xs pointer-events-none">
          <div v-if="item.scores && Object.keys(item.scores).length > 0" class="space-y-0.5">
            <div
              v-for="(value, key) in item.scores"
              :key="key"
              class="flex justify-between text-content-tertiary"
            >
              <span class="truncate">{{ formatKey(key) }}</span>
              <span class="text-content font-medium">{{ value }}</span>
            </div>
          </div>
          <div v-else-if="item.error" class="text-red-500 text-xs">
            {{ item.error }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { MediaImage } from '../media'

defineProps({
  scoredData: {
    type: Object,
    required: true,
    default: () => ({ criteria: '', items: [] })
  }
})

defineEmits(['view-image'])

function formatScore(score) {
  if (score === null || score === undefined) return '?'
  return (score * 100).toFixed(0) + '%'
}

function getScoreClass(score) {
  if (score === null || score === undefined) return 'bg-gray-500/70 text-content'
  if (score >= 0.8) return 'bg-green-500/90 text-white'
  if (score >= 0.6) return 'bg-yellow-500/90 text-black'
  if (score >= 0.4) return 'bg-orange-500/90 text-white'
  return 'bg-red-500/90 text-white'
}

function formatKey(key) {
  // Convert snake_case to Title Case
  return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}
</script>

<style scoped>
.scored-results {
  border: 1px solid rgba(255, 255, 255, 0.1);
}
</style>
