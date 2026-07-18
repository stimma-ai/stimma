<template>
  <div
    :title="compact ? tooltip : undefined"
    :class="[
      'group relative flex items-center overflow-hidden',
      // Compact (narrow Stage rail): drop the card chrome — a framed surface is
      // mostly empty here and reads as a hollow card. Active items become a tight
      // stack of borderless slim loading bars. Failed keeps a subtle red frame so
      // it's still noticeable.
      compact
        ? (failed ? 'gap-2 px-2 py-1.5 rounded-md border bg-red-500/10 border-red-500/40' : 'gap-2.5 px-1 py-1.5')
        : ['min-h-[58px] gap-2.5 px-2.5 py-2 rounded-lg border', failed ? 'bg-red-500/10 border-red-500/40' : 'bg-surface-raised border-edge'],
    ]"
  >
    <!-- Leading icon: thumbnail when we have one (chains carry their last good
         output), otherwise a status spinner / queued clock. In compact, the
         boxed background is dropped for the bare spinner so the row stays light;
         thumbnails keep a small framed tile. -->
    <div
      :class="[
        'relative flex items-center justify-center flex-shrink-0 overflow-hidden',
        thumbMediaId
          ? (compact ? 'w-6 h-6 rounded bg-surface' : 'w-9 h-9 rounded-md bg-surface')
          : (compact ? 'w-3.5 h-3.5' : 'w-9 h-9 rounded-md bg-surface'),
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
          <Spinner size="sm" hue="border-t-blue-500" />
        </div>
      </template>
      <template v-else>
        <svg
          v-if="failed"
          xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" :class="[compact ? 'w-3.5 h-3.5' : 'w-4 h-4', 'text-red-500']"
        >
          <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
        </svg>
        <Spinner
          v-else-if="status === 'processing'"
          :size="compact ? 'sm' : 'md'"
          hue="border-t-blue-500"
        />
        <Spinner
          v-else-if="status === 'enhancing'"
          :size="compact ? 'sm' : 'md'"
          hue="border-t-purple-500"
        />
        <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" :class="[compact ? 'w-3.5 h-3.5' : 'w-4 h-4', 'text-content-muted']">
          <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clip-rule="evenodd" />
        </svg>
      </template>
    </div>

    <!-- Tool name · pipeline track · current-stage line. In compact mode the
         name + status line are dropped (they only truncated to "LT…" / "Ge…" at
         160px) — the track gets the full width and the details move to the row
         tooltip. -->
    <div class="flex-1 min-w-0">
      <!-- Compact (narrow Stage rail): no progress bar — the leading spinner is
           the only "working" cue, and the bar in its place just read as a lonely
           line. Show a single truncated line of text instead (tool name, or the
           "N of M" count for batches); the full status lives in the row tooltip. -->
      <!-- Fade the name out at the right edge instead of a hard ellipsis — the
           tool name almost always overflows this 160px rail, and "…" on every row
           is noisy. The mask is set via inline style (not an arbitrary Tailwind
           class) so JIT purging can't drop it; `-webkit-` is required in the
           Tauri WebKit webview. Short names don't reach the fade zone, so crisp. -->
      <div
        v-if="compact"
        :class="['text-xs font-medium whitespace-nowrap overflow-hidden', failed ? 'text-red-500' : 'text-content']"
        :style="fadeMaskStyle"
      >{{ compactText }}</div>

      <template v-else>
        <div class="text-xs font-medium text-content truncate whitespace-nowrap">{{ name }}</div>

        <!-- Segmented pipeline: one segment per stage (generation + each
             post-processing step). Determinate fill is used for batches. -->
        <div class="mt-1.5">
          <div v-if="segments && segments.length" class="flex items-center gap-1 h-1.5">
            <div
              v-for="(seg, i) in segments"
              :key="i"
              :title="seg.title"
              :class="[
                'relative flex-1 h-full rounded-full overflow-hidden',
                seg.status === 'done' ? dotClass('done') :
                seg.status === 'failed' ? dotClass('failed') :
                seg.status === 'skipped' ? dotClass('skipped') :
                seg.status === 'active' ? 'bg-blue-500/35' :
                'bg-surface',
              ]"
            >
              <!-- Calm solid-blue active segment identifies the stage; a dim,
                   narrow band drifts slowly across it. -->
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

        <div :class="['mt-1.5 text-[11px] truncate whitespace-nowrap', failed ? 'text-red-500' : 'text-content-muted']">
          {{ label }}
        </div>
      </template>
    </div>

    <!-- Failed → Retry + Dismiss; otherwise the hover Cancel. -->
    <template v-if="failed">
      <button
        v-if="showRetry"
        @click.stop="$emit('retry')"
        :class="[
          'flex items-center gap-1 rounded bg-accent/15 text-accent-hi hover:bg-accent/25 text-[11px] font-medium transition-colors',
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
        'flex items-center justify-center rounded text-content-muted/50 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100',
        compact ? 'absolute right-0 top-1/2 -translate-y-1/2 z-10 w-5 h-5 bg-surface/90 backdrop-blur-sm' : 'w-6 h-6',
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
import Spinner from '../../ui/Spinner.vue'
import { dotClass } from '../../../utils/statusColors'

export type SegmentStatus = 'done' | 'active' | 'pending' | 'failed' | 'skipped'
export interface PipelineSegment {
  status: SegmentStatus
  /** Hover tooltip, e.g. "Face fix — running". */
  title?: string
}

const props = withDefaults(defineProps<{
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
  /** Narrow Stage rail: drop name/label text, fill the track, details on hover. */
  compact?: boolean
}>(), {
  segments: null,
  progress: null,
  status: 'processing',
  thumbMediaId: null,
  failed: false,
  showCancel: true,
  showRetry: true,
  compact: false,
})

// Compact rows hide the text, so the name + current-stage line move to the row
// tooltip (e.g. "LTX Video — Generating…").
const tooltip = computed(() =>
  [props.name, props.label].filter(Boolean).join(' — ')
)

// The single line shown in compact rows: the tool/step name, except for
// determinate batches where the "N of M" count is the useful bit.
const compactText = computed(() =>
  props.progress != null ? props.label : props.name
)

// Right-edge fade for the compact name (see template). Both standard and
// -webkit- (Tauri runs WebKit) so it can't silently no-op.
const fadeMask = 'linear-gradient(to right, #000 82%, transparent)'
const fadeMaskStyle = { maskImage: fadeMask, WebkitMaskImage: fadeMask }

defineEmits<{
  (e: 'cancel'): void
  (e: 'retry'): void
  (e: 'dismiss'): void
}>()
</script>
