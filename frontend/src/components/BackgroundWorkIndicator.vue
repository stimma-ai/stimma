<template>
  <!-- One glyph for the state of background work. Paused > spinner >
       failure > delete done > warning-only > pending. -->
  <svg v-if="isPaused && hasIncompleteWork" class="w-5 h-5 text-yellow-500" fill="currentColor" viewBox="0 0 24 24">
    <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z"/>
  </svg>
  <Spinner v-else-if="(isActivelyProcessing && !isPaused) || isDeleteRunning" hue="border-t-white/80" />
  <svg v-else-if="totalFailed > 0 || hasDeleteFailed" class="w-5 h-5 text-red-500" fill="currentColor" viewBox="0 0 24 24">
    <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>
  </svg>
  <svg v-else-if="hasDeleteCompleted" class="w-5 h-5 text-green-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
    <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
  </svg>
  <svg v-else-if="systemWarnings.length > 0 && totalPending === 0 && totalProcessing === 0" class="w-5 h-5 text-yellow-500" fill="currentColor" viewBox="0 0 24 24">
    <path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>
  </svg>
  <Spinner v-else hue="border-t-amber-500" />
</template>

<script setup>
import Spinner from './ui/Spinner.vue'
import { useBackgroundWork } from '../composables/useBackgroundWork'

const {
  isPaused, hasIncompleteWork, isActivelyProcessing, isDeleteRunning, totalFailed,
  hasDeleteFailed, hasDeleteCompleted, systemWarnings, totalPending, totalProcessing,
} = useBackgroundWork()
</script>
