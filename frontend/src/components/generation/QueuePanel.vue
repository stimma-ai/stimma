<template>
  <div class="w-full p-4 overflow-y-auto scrollbar-stable bg-surface-overlay">
    <!-- No "Queue" heading or floating options menu — queue options live on the
         page header's button strip now. -->
    <JobsGrid
      :jobs="jobs"
      :markers="markers"
      :media-hashes="mediaHashes"
      :media-markers="mediaMarkers"
      :media-generation-times="mediaGenerationTimes"
      :batch-jobs="batchJobs"
      :is-video="isVideo"
      :image-mode="imageMode"
      :empty-message="emptyMessage"
      @job-click="$emit('job-click', $event)"
      @toggle-marker="$emit('toggle-marker', $event)"
      @dismiss-job="$emit('dismiss-job', $event)"
      @retry-job="$emit('retry-job', $event)"
      @cancel-job="$emit('cancel-job', $event)"
      @cancel-and-dismiss-batch="$emit('cancel-and-dismiss-batch', $event)"
      @dismiss-batch="$emit('dismiss-batch', $event)"
      @clear-queue="$emit('clear-queue')"
      @media-load-error="$emit('media-load-error', $event)"
      @show-job-info="$emit('show-job-info', $event)"
    />
  </div>
</template>

<script setup>
import JobsGrid from './JobsGrid.vue'

// Queue options (clear queue, image mode) now live on the page header's button
// strip, so this panel is just the jobs grid. Events are forwarded to the parent.
defineProps({
  jobs: { type: Array, required: true },
  markers: { type: Array, default: () => [] },
  mediaHashes: { type: Object, default: () => ({}) },
  mediaMarkers: { type: Object, default: () => ({}) },
  mediaGenerationTimes: { type: Object, default: () => ({}) },
  batchJobs: { type: Object, default: () => ({}) },
  emptyMessage: { type: String, default: 'No jobs yet.' },
  imageMode: { type: String, default: 'fit' },
  isVideo: { type: Boolean, default: false }
})

defineEmits([
  'job-click',
  'toggle-marker',
  'dismiss-job',
  'retry-job',
  'cancel-job',
  'cancel-and-dismiss-batch',
  'dismiss-batch',
  'media-load-error',
  'show-job-info'
])
</script>
