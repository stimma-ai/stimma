<template>
  <!-- Terminal failure for a single job, in the same tile language as every
       other item in the strip: it occupies the slot its result would have
       taken, at the same aspect. Quiet by default — matte with a red hairline
       and a small mark, not a red card — so a run of failures reads as a set
       of empty slots rather than a wall of alarm. Actions appear on hover;
       clicking the tile opens the failure details. -->
  <div
    :class="[
      'jobs-tile group relative w-full rounded-media overflow-hidden bg-matte cursor-pointer',
      'ring-1 ring-inset', ringClass('failed'),
    ]"
    :style="{ aspectRatio: aspect || '1 / 1' }"
    :title="name"
  >
    <div :class="['absolute inset-0 flex flex-col items-center justify-center text-center', compact ? 'gap-1 px-1.5' : 'gap-1.5 px-3']">
      <svg
        xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"
        :class="[compact ? 'w-4 h-4' : 'w-5 h-5', 'flex-shrink-0', textClass('failed')]"
      >
        <path fill-rule="evenodd" d="M9.401 3.003c1.155-2 4.043-2 5.197 0l7.355 12.748c1.154 2-.29 4.5-2.599 4.5H4.645c-2.309 0-3.752-2.5-2.598-4.5L9.4 3.003zM12 8.25a.75.75 0 01.75.75v3.75a.75.75 0 01-1.5 0V9a.75.75 0 01.75-.75zm0 8.25a.75.75 0 100-1.5.75.75 0 000 1.5z" clip-rule="evenodd" />
      </svg>
      <div
        :class="['max-w-full line-clamp-2', textClass('failed'), compact ? 'text-[10.5px] leading-tight' : 'text-[11px] leading-snug']"
        :title="error || undefined"
      >{{ error || 'Failed' }}</div>
    </div>

    <div class="absolute top-1.5 right-1.5 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
      <button
        v-if="showRetry"
        @click.stop="$emit('retry')"
        class="w-6 h-6 flex items-center justify-center rounded-md bg-black/55 text-white/80 hover:text-accent-hi transition-colors"
        title="Retry"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
          <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0v2.43l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z" clip-rule="evenodd" />
        </svg>
      </button>
      <button
        @click.stop="$emit('dismiss')"
        class="w-6 h-6 flex items-center justify-center rounded-md bg-black/55 text-white/70 hover:text-white transition-colors"
        title="Dismiss"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
          <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ringClass, textClass } from '../../utils/statusColors'

withDefaults(defineProps<{
  /** Tool/model name (e.g. "Flux.2 Klein 9B"). */
  name: string
  /** Raw failure message; clamped to two lines, full text on hover. */
  error?: string | null
  /** CSS aspect-ratio of the result this job would have produced. */
  aspect?: string | null
  /** Narrow Stage rail: drop the name, tighten the type. */
  compact?: boolean
  showRetry?: boolean
}>(), {
  error: null,
  aspect: null,
  compact: false,
  showRetry: true,
})

defineEmits<{
  (e: 'retry'): void
  (e: 'dismiss'): void
}>()
</script>
