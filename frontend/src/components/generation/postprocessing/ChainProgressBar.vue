<template>
  <div
    :class="[
      'group relative flex items-center gap-2.5 h-[52px] px-2.5 rounded-lg border overflow-hidden',
      failed ? 'bg-red-500/10 border-red-500/40' : 'bg-surface-raised border-edge',
    ]"
  >
    <!-- Thumbnail: last good output (falls back to the base generation) -->
    <div class="relative w-9 h-9 rounded-md bg-surface flex items-center justify-center flex-shrink-0 overflow-hidden">
      <MediaImage
        v-if="thumbMediaId"
        :media-id="thumbMediaId"
        :thumbnail="true"
        :thumbnail-size="128"
        container-class="w-full h-full"
      />
      <div
        v-if="!failed"
        class="absolute inset-0 flex items-center justify-center bg-black/30"
      >
        <div class="w-[18px] h-[18px] border-2 border-white/30 border-t-blue-400 rounded-full animate-spin"></div>
      </div>
    </div>

    <!-- Label + step dots -->
    <div class="flex-1 min-w-0">
      <div class="flex items-baseline gap-2">
        <span :class="['text-xs font-medium', failed ? 'text-red-500' : 'text-content']">
          {{ failed ? 'Post-processing failed' : 'Post-processing' }}
        </span>
        <span class="text-[11px] text-content-muted truncate">{{ currentStepLabel }}</span>
      </div>
      <div class="mt-1.5 flex items-center gap-1.5">
        <!-- Step dots: done = green, running = blue ring, failed = red, queued = hollow -->
        <span
          v-for="(dot, i) in dots"
          :key="i"
          :class="[
            'inline-block w-2 h-2 rounded-full flex-shrink-0',
            dot === 'done' ? 'bg-green-500' :
            dot === 'running' ? 'bg-transparent ring-2 ring-blue-500' :
            dot === 'failed' ? 'bg-red-500' :
            dot === 'skipped' ? 'bg-amber-500/60' :
            'bg-transparent ring-1 ring-edge-strong',
          ]"
          :title="dotTitle(i)"
        ></span>
        <span class="text-[10px] text-content-muted ml-1">{{ doneCount }} of {{ run.step_count }}</span>
      </div>
    </div>

    <!-- Failed: Retry (no Stop button by design) -->
    <button
      v-if="failed"
      @click.stop="$emit('retry', run.id)"
      class="flex items-center gap-1 px-2 py-1 rounded bg-blue-500/15 border border-blue-500/50 text-blue-500 hover:bg-blue-500/30 text-[11px] font-medium transition-colors"
      title="Retry the failed step"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3">
        <path fill-rule="evenodd" d="M15.312 11.424a5.5 5.5 0 01-9.201 2.466l-.312-.311h2.433a.75.75 0 000-1.5H3.989a.75.75 0 00-.75.75v4.242a.75.75 0 001.5 0v-2.43l.31.31a7 7 0 0011.712-3.138.75.75 0 00-1.449-.39zm1.23-3.723a.75.75 0 00.219-.53V2.929a.75.75 0 00-1.5 0v2.43l-.31-.31A7 7 0 003.239 8.188a.75.75 0 101.448.389A5.5 5.5 0 0113.89 6.11l.311.31h-2.432a.75.75 0 000 1.5h4.243a.75.75 0 00.53-.219z" clip-rule="evenodd" />
      </svg>
      Retry
    </button>
    <button
      v-if="failed"
      @click.stop="$emit('dismiss', run.id)"
      class="w-6 h-6 flex items-center justify-center rounded text-content-muted/50 hover:text-content-secondary transition-colors"
      title="Dismiss"
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

interface ChainRun {
  id: number
  job_id: number
  base_media_id: number
  chain: any[]
  step_index: number
  step_count: number
  step_results: Array<{ status: string; media_id?: number; error?: string }>
  status: string
  last_good_media_id?: number
  final_media_id?: number
  error?: string
}

const props = defineProps<{
  run: ChainRun
}>()

defineEmits<{
  (e: 'retry', runId: number): void
  (e: 'dismiss', runId: number): void
}>()

const failed = computed(() => props.run.status === 'paused' || props.run.status === 'failed')

const thumbMediaId = computed(() => props.run.last_good_media_id || props.run.base_media_id)

const dots = computed(() =>
  (props.run.step_results || []).map(r =>
    r.status === 'done' ? 'done' :
    r.status === 'running' ? 'running' :
    r.status === 'failed' ? 'failed' :
    r.status === 'skipped_incompatible' ? 'skipped' :
    'queued'
  )
)

const doneCount = computed(() =>
  (props.run.step_results || []).filter(r => r.status === 'done').length
)

function stepLabel(step: any): string {
  if (!step) return ''
  return step.kind === 'filter' ? (step.filter_id || 'filter') : (step.tool_name || step.tool_id || 'tool')
}

const currentStepLabel = computed(() => {
  const idx = Math.min(props.run.step_index, (props.run.chain || []).length - 1)
  const step = (props.run.chain || [])[idx]
  if (failed.value) return props.run.error || stepLabel(step)
  return stepLabel(step)
})

function dotTitle(i: number): string {
  const step = (props.run.chain || [])[i]
  const status = (props.run.step_results || [])[i]?.status || 'queued'
  return `${stepLabel(step)} — ${status === 'skipped_incompatible' ? 'skipped (incompatible input)' : status}`
}
</script>
