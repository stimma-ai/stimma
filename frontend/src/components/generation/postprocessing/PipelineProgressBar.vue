<template>
  <div
    :title="compact ? tooltip : undefined"
    :class="[
      'group relative flex items-center rounded-lg border overflow-hidden',
      compact ? 'gap-2 min-h-[40px] px-2 py-2' : 'gap-2.5 min-h-[58px] px-2.5 py-2',
      failed ? 'bg-red-500/10 border-red-500/40' : 'bg-surface-raised border-edge',
    ]"
  >
    <!-- Leading icon: thumbnail when we have one (chains carry their last good
         output), otherwise a status spinner / queued clock. In compact (narrow
         Stage rail) it shrinks so the track gets the room. -->
    <div
      :class="[
        'relative rounded-md bg-surface flex items-center justify-center flex-shrink-0 overflow-hidden',
        compact ? 'w-6 h-6' : 'w-9 h-9',
      ]"
    >
      <template v-if="thumbMediaId">
        <MediaImage
          :media-id="thumbMediaId"
          :thumbnail="true"
          :thumbnail-size="128"
          container-class="w-full h-full"
        />
        <div v-if="!failed" class="absolute inset-0 flex items-center justify-center bg-black/30">
          <div class="w-[18px] h-[18px] border-2 border-white/30 border-t-blue-400 rounded-full animate-spin"></div>
        </div>
      </template>
      <template v-else>
        <svg
          v-if="failed"
          xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-red-500"
        >
          <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
        </svg>
        <div
          v-else-if="status === 'processing'"
          class="w-[18px] h-[18px] border-2 border-edge-strong border-t-blue-500 rounded-full animate-spin"
        ></div>
        <div
          v-else-if="status === 'enhancing'"
          class="w-[18px] h-[18px] border-2 border-edge-strong border-t-purple-500 rounded-full animate-spin"
        ></div>
        <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-content-muted">
          <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clip-rule="evenodd" />
        </svg>
      </template>
    </div>

    <!-- Tool name · pipeline track · current-stage line. In compact mode the
         name + status line are dropped (they only truncated to "LT…" / "Ge…" at
         160px) — the track gets the full width and the details move to the row
         tooltip. -->
    <div class="flex-1 min-w-0">
      <div v-if="!compact" class="text-xs font-medium text-content truncate whitespace-nowrap">{{ name }}</div>

      <!-- Segmented pipeline: one segment per stage (generation + each
           post-processing step). Determinate fill is used for batches. -->
      <div :class="compact ? '' : 'mt-1.5'">
        <div v-if="segments && segments.length" class="flex items-center gap-1 h-1.5">
          <div
            v-for="(seg, i) in segments"
            :key="i"
            :title="seg.title"
            :class="[
              'relative flex-1 h-full rounded-full overflow-hidden',
              seg.status === 'done' ? 'bg-blue-500' :
              seg.status === 'failed' ? 'bg-red-500' :
              seg.status === 'skipped' ? 'bg-amber-500/50' :
              seg.status === 'active' ? 'bg-blue-500/35' :
              'bg-surface',
            ]"
          >
            <!-- Calm solid-blue active segment identifies the stage; a dim,
                 narrow band drifts slowly across it. Larger bg length keeps the
                 highlight a small fraction of the bar even when it's wide. -->
            <span
              v-if="seg.status === 'active'"
              class="absolute inset-0 animate-shimmer bg-gradient-to-r from-transparent via-blue-300/40 to-transparent bg-[length:300%_100%]"
            ></span>
          </div>
        </div>
        <!-- Determinate (batches): real fraction -->
        <div v-else class="h-1.5 rounded-full bg-surface overflow-hidden">
          <div
            v-if="progress != null"
            class="h-full bg-blue-500 transition-all duration-300"
            :style="{ width: `${Math.round(progress * 100)}%` }"
          ></div>
        </div>
      </div>

      <div v-if="!compact" :class="['mt-1.5 text-[11px] truncate whitespace-nowrap', failed ? 'text-red-500' : 'text-content-muted']">
        {{ label }}
      </div>
    </div>

    <!-- Failed → Retry + Dismiss; otherwise the hover Cancel. -->
    <template v-if="failed">
      <button
        v-if="showRetry"
        @click.stop="$emit('retry')"
        :class="[
          'flex items-center gap-1 rounded bg-blue-500/15 border border-blue-500/50 text-blue-500 hover:bg-blue-500/30 text-[11px] font-medium transition-colors',
          compact ? 'w-6 h-6 justify-center' : 'px-2 py-1',
        ]"
        title="Retry the failed step"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3">
          <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0v2.43l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z" clip-rule="evenodd" />
        </svg>
        <span v-if="!compact">Retry</span>
      </button>
      <button
        @click.stop="$emit('dismiss')"
        class="w-6 h-6 flex items-center justify-center rounded text-content-muted/50 hover:text-content-secondary transition-colors"
        title="Dismiss"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
          <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
        </svg>
      </button>
    </template>
    <button
      v-else-if="showCancel"
      @click.stop="$emit('cancel')"
      :class="[
        'w-6 h-6 flex items-center justify-center rounded text-content-muted/50 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100',
        compact ? 'absolute top-1 right-1 z-10 bg-surface-raised/80 backdrop-blur-sm' : '',
      ]"
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
import { MediaImage } from '../../media'

export type SegmentStatus = 'done' | 'active' | 'pending' | 'failed' | 'skipped'
export interface PipelineSegment {
  status: SegmentStatus
  /** Hover tooltip, e.g. "Face fix — running". */
  title?: string
}

withDefaults(defineProps<{
  /** Tool/model name (e.g. "SeedVR2 Image Upscale 3B"). */
  name: string
  /** Current-stage line under the track (e.g. "Upscaling — step 3 of 5"). */
  label: string
  /** One segment per pipeline stage. Omit to use the determinate `progress`. */
  segments?: PipelineSegment[] | null
  /** 0..1 determinate fill (batches) when `segments` is omitted. */
  progress?: number | null
  /** 'queued' | 'processing' | 'enhancing' — drives the leading spinner. */
  status?: string
  /** Optional thumbnail (chains pass their last good output). */
  thumbMediaId?: number | null
  failed?: boolean
  showCancel?: boolean
  showRetry?: boolean
}>(), {
  segments: null,
  progress: null,
  status: 'processing',
  thumbMediaId: null,
  failed: false,
  showCancel: true,
  showRetry: true,
})

defineEmits<{
  (e: 'cancel'): void
  (e: 'retry'): void
  (e: 'dismiss'): void
}>()
</script>
