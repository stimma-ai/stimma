<template>
  <!-- Terminal failure for a single job. Deliberately NOT a PipelineProgressBar:
       a finished failure has no progress to show, so there's no track. A thin red
       left accent + small icon marks the row as failed without washing the whole
       card red (which becomes a wall when many failures stack). -->
  <div
    :class="[
      'group relative overflow-hidden rounded-lg border border-edge-subtle bg-surface-raised',
      compact ? 'flex flex-col gap-1.5 px-2 py-2' : 'flex items-start gap-2.5 px-3 py-2.5',
    ]"
  >
    <!-- Red left accent bar -->
    <span class="absolute inset-y-0 left-0 w-[3px] bg-red-500/70"></span>

    <!-- Compact (stage strip): stacked so nothing clips at 160px -->
    <template v-if="compact">
      <div class="flex items-start gap-1.5">
        <span class="flex-shrink-0 flex items-center justify-center w-[22px] h-[22px] rounded-md bg-red-500/15 text-red-500 dark:text-red-400 overflow-hidden">
          <MediaImage v-if="thumbMediaId" :media-id="thumbMediaId" :thumbnail="true" :thumbnail-size="128" container-class="w-full h-full" />
          <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-3.5 h-3.5">
            <path fill-rule="evenodd" d="M9.401 3.003c1.155-2 4.043-2 5.197 0l7.355 12.748c1.154 2-.29 4.5-2.599 4.5H4.645c-2.309 0-3.752-2.5-2.598-4.5L9.4 3.003zM12 8.25a.75.75 0 01.75.75v3.75a.75.75 0 01-1.5 0V9a.75.75 0 01.75-.75zm0 8.25a.75.75 0 100-1.5.75.75 0 000 1.5z" clip-rule="evenodd" />
          </svg>
        </span>
        <div class="text-[12px] font-medium text-content leading-tight line-clamp-2">{{ name }}</div>
      </div>
      <div class="text-[10.5px] leading-tight text-red-500 dark:text-red-400 line-clamp-2" :title="error || undefined">
        {{ error || 'Failed — click for details' }}
      </div>
      <div class="flex items-center gap-1.5">
        <button
          v-if="showRetry"
          @click.stop="$emit('retry')"
          class="flex-1 flex items-center justify-center gap-1 px-2 py-1 rounded-md bg-accent/15 text-accent hover:bg-accent/25 text-[11px] font-medium transition-colors duration-150"
          title="Retry"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3">
            <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0v2.43l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z" clip-rule="evenodd" />
          </svg>
          Retry
        </button>
        <button
          @click.stop="$emit('dismiss')"
          class="w-6 h-6 flex-shrink-0 flex items-center justify-center rounded-md text-content-muted/60 hover:text-content-secondary hover:bg-overlay-subtle transition-colors duration-150"
          title="Dismiss"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
            <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
          </svg>
        </button>
      </div>
    </template>

    <!-- Studio (wide column): single row, error wraps to two lines -->
    <template v-else>
      <span class="flex-shrink-0 flex items-center justify-center w-[30px] h-[30px] mt-px rounded-md bg-red-500/15 text-red-500 dark:text-red-400 overflow-hidden">
        <MediaImage v-if="thumbMediaId" :media-id="thumbMediaId" :thumbnail="true" :thumbnail-size="128" container-class="w-full h-full" />
        <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-[18px] h-[18px]">
          <path fill-rule="evenodd" d="M9.401 3.003c1.155-2 4.043-2 5.197 0l7.355 12.748c1.154 2-.29 4.5-2.599 4.5H4.645c-2.309 0-3.752-2.5-2.598-4.5L9.4 3.003zM12 8.25a.75.75 0 01.75.75v3.75a.75.75 0 01-1.5 0V9a.75.75 0 01.75-.75zm0 8.25a.75.75 0 100-1.5.75.75 0 000 1.5z" clip-rule="evenodd" />
        </svg>
      </span>

      <div class="flex-1 min-w-0 pt-px">
        <div class="text-[13px] font-medium text-content truncate">{{ name }}</div>
        <div class="mt-0.5 text-[11.5px] leading-snug text-red-500 dark:text-red-400 line-clamp-2" :title="error || undefined">
          {{ error || 'Failed — click for details' }}
        </div>
      </div>

      <div class="flex items-center gap-1 flex-shrink-0">
        <button
          v-if="showRetry"
          @click.stop="$emit('retry')"
          class="flex items-center gap-1 px-2.5 py-1 rounded-md bg-accent/15 text-accent hover:bg-accent/25 text-[11px] font-medium transition-colors duration-150"
          title="Retry the failed step"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3">
            <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0v2.43l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z" clip-rule="evenodd" />
          </svg>
          Retry
        </button>
        <button
          @click.stop="$emit('dismiss')"
          class="w-6 h-6 flex items-center justify-center rounded-md text-content-muted/60 hover:text-content-secondary hover:bg-overlay-subtle transition-colors duration-150"
          title="Dismiss"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
            <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
          </svg>
        </button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { MediaImage } from '../media'

withDefaults(defineProps<{
  /** Tool/model name (e.g. "Flux.2 Klein 9B"). */
  name: string
  /** Raw failure message; shown clamped to two lines, full text on hover. */
  error?: string | null
  /** Stage strip (160px) → stacked layout so nothing clips. */
  compact?: boolean
  /** Optional last-good thumbnail (shown in place of the error glyph). */
  thumbMediaId?: number | null
  showRetry?: boolean
}>(), {
  error: null,
  compact: false,
  thumbMediaId: null,
  showRetry: true,
})

defineEmits<{
  (e: 'retry'): void
  (e: 'dismiss'): void
}>()
</script>
