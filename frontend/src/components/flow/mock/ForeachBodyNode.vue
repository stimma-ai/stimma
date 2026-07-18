<template>
  <div class="relative" :style="{ width: NODE_W + 'px' }">
    <div
      class="relative rounded-lg border-2 overflow-hidden flex flex-col"
      :class="[cardClass, node.optional ? 'opacity-90' : '']"
      :style="{ height: NODE_H + 'px' }"
    >
      <!-- Header: gradient icon box + title + optional badge -->
      <div class="flex items-center gap-2 px-2 pt-1.5 pb-1 min-w-0">
        <div
          class="w-7 h-7 rounded-md flex items-center justify-center flex-shrink-0"
          :class="iconBgClass"
        >
          <svg
            class="w-3.5 h-3.5 text-white"
            fill="none"
            viewBox="0 0 24 24"
            stroke-width="1.75"
            stroke="currentColor"
          >
            <path stroke-linecap="round" stroke-linejoin="round" :d="iconPath" />
          </svg>
        </div>
        <div class="flex-1 min-w-0 flex flex-col justify-center">
          <span class="truncate text-[12px] leading-tight text-content font-medium">{{ node.title }}</span>
          <span
            v-if="node.subtitle"
            class="truncate text-[10px] leading-tight text-content-muted"
          >{{ node.subtitle }}</span>
        </div>
        <span
          v-if="node.optional"
          class="flex-shrink-0 text-[9.5px] uppercase tracking-wide text-content-muted/80 italic"
        >optional</span>
      </div>

      <!-- Middle: ribbon (aggregate) or focused iteration tile -->
      <div class="flex-1 min-h-0 px-2 pb-1 flex items-center">
        <!-- Aggregate: indexed status ribbon -->
        <div v-if="focusedIdx === null" class="w-full">
          <div class="flex items-center gap-[1px] h-5 rounded-sm overflow-hidden bg-overlay-faint">
            <div
              v-for="seg in ribbonSegments"
              :key="seg.key"
              class="h-full"
              :class="seg.class"
              :style="{ flex: seg.flex, opacity: seg.opacity }"
              :title="seg.title"
            />
          </div>
        </div>

        <!-- Focused: IterationCard-style mini tile -->
        <div v-else class="w-full flex items-center gap-2">
          <div
            class="w-12 h-12 flex-shrink-0 rounded-md border overflow-hidden flex items-center justify-center"
            :class="focusedTileClass"
          >
            <template v-if="focusedStatus === 'computing'">
              <Spinner size="sm" hue="border-t-blue-400" />
            </template>
            <template v-else-if="focusedStatus === 'failed'">
              <svg class="w-4 h-4 text-red-400" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </template>
            <template v-else-if="focusedStatus === 'completed'">
              <svg class="w-4 h-4 text-green-400" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
            </template>
            <template v-else-if="focusedStatus === 'awaiting_input'">
              <svg class="w-4 h-4 text-purple-400" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
              </svg>
            </template>
            <template v-else-if="focusedStatus === null">
              <span class="text-[9px] text-content-muted/70 italic">n/a</span>
            </template>
            <template v-else>
              <svg class="w-3.5 h-3.5 text-content-muted/60" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6l4 2m5-2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </template>
          </div>
          <div class="flex-1 min-w-0 text-[10.5px] text-content-muted leading-tight">
            <div class="truncate text-content">{{ focusedLabel }}</div>
            <div v-if="focusedDuration" class="tabular-nums">{{ focusedDuration }}</div>
            <div v-else-if="focusedStatus === null" class="italic">not in this iteration</div>
          </div>
        </div>
      </div>

      <!-- Footer: summary counts (aggregate) or status label (focused) -->
      <div class="flex items-center gap-1.5 px-2 pb-1.5 flex-shrink-0 text-[10.5px]">
        <template v-if="focusedIdx === null">
          <span class="w-2 h-2 rounded-full flex-shrink-0" :class="summaryDotClass" />
          <span class="truncate" :class="summaryLabelClass">{{ summaryLabel }}</span>
        </template>
        <template v-else>
          <Spinner v-if="focusedStatus === 'computing'" size="sm" hue="border-t-blue-400" />
          <svg
            v-else-if="focusedStatus === 'completed'"
            class="w-3.5 h-3.5 text-green-400 flex-shrink-0"
            fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
          <svg
            v-else-if="focusedStatus === 'failed'"
            class="w-3.5 h-3.5 text-red-400 flex-shrink-0"
            fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
          <span v-else class="w-2 h-2 rounded-full border border-content-muted/40 flex-shrink-0" />
          <span class="flex-1 italic truncate" :class="focusedLabelClass">{{ focusedStatusLabel }}</span>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { MockBodyNode, MockStatus } from './foreachMockData'
import { aggregateCounts } from './foreachMockData'
import { dotClass, textClass, cardFrameClass, tileBgClass, type StatusBucket } from '../../../utils/statusColors'
import Spinner from '../../ui/Spinner.vue'

// Maps this node's own status vocabulary onto the shared statusColors.ts
// bucket type; actual colors always come from the shared exports below.
function mockStatusToBucket(s: MockStatus | null): StatusBucket | null {
  switch (s) {
    case 'completed':      return 'done'
    case 'computing':      return 'running'
    case 'failed':         return 'failed'
    case 'awaiting_input': return 'awaiting'
    case 'pending':        return 'queued'
    case 'skipped':        return 'skipped'
    default:               return null
  }
}

interface Props {
  node: MockBodyNode
  focusedIdx: number | null
  iterLabel?: string | null
  // Max segments to show in the ribbon before bucketing.
  maxRibbonSegments?: number
}
const props = withDefaults(defineProps<Props>(), {
  iterLabel: null,
  maxRibbonSegments: 120,
})

const NODE_W = 240
const NODE_H = 120

// --- Dominant-status per ribbon bucket ---
const DOMINANCE: Record<MockStatus | 'null', number> = {
  failed: 6,
  awaiting_input: 5,
  computing: 4,
  pending: 3,
  completed: 2,
  skipped: 1,
  null: 0,
}

function segClass(s: MockStatus | null): string {
  const bucket = mockStatusToBucket(s)
  if (bucket === null) return 'bg-transparent'
  if (bucket === 'running') return `${dotClass(bucket)} pulse-soft`
  if (bucket === 'queued') return 'bg-zinc-500/40'
  if (bucket === 'skipped') return 'bg-zinc-600/50'
  return dotClass(bucket)
}

const ribbonSegments = computed(() => {
  const statuses = props.node.iterStatuses
  const n = statuses.length
  if (n === 0) return [] as Array<{ key: string; class: string; flex: number; opacity: number; title: string }>
  const maxSeg = props.maxRibbonSegments
  if (n <= maxSeg) {
    // 1 seg per iteration, index-preserving.
    return statuses.map((s, i) => ({
      key: `s-${i}`,
      class: segClass(s),
      flex: 1,
      opacity: s === null ? 0.25 : 1,
      title: `#${i} · ${s ?? 'n/a'}`,
    }))
  }
  // Bucket into maxSeg groups; dominant status wins per bucket.
  const bucketSize = Math.ceil(n / maxSeg)
  const segs: Array<{ key: string; class: string; flex: number; opacity: number; title: string }> = []
  for (let b = 0; b < maxSeg; b++) {
    const start = b * bucketSize
    const end = Math.min(n, start + bucketSize)
    if (start >= end) break
    let winner: MockStatus | null = null
    let winnerScore = -1
    let hadAny = false
    for (let i = start; i < end; i++) {
      const s = statuses[i]
      const score = DOMINANCE[s ?? 'null']
      if (s !== null && s !== undefined) hadAny = true
      if (score > winnerScore) {
        winnerScore = score
        winner = s ?? null
      }
    }
    segs.push({
      key: `b-${b}`,
      class: segClass(winner),
      flex: end - start,
      opacity: hadAny ? 1 : 0.2,
      title: `#${start}–${end - 1}`,
    })
  }
  return segs
})

// --- Aggregate footer ---
const counts = computed(() => aggregateCounts(props.node.iterStatuses))

const summaryLabel = computed(() => {
  const c = counts.value
  const parts: string[] = []
  if (c.failed > 0) parts.push(`${c.failed} err`)
  if (c.awaiting_input > 0) parts.push(`${c.awaiting_input} waiting`)
  if (c.computing > 0) parts.push(`${c.computing} running`)
  if (c.pending > 0) parts.push(`${c.pending} pending`)
  if (c.completed > 0) parts.push(`${c.completed} ok`)
  if (parts.length === 0) return props.node.optional ? '— not applied' : '—'
  return parts.join(' · ')
})

// Dominant bucket for the aggregate summary dot/label — routed through the
// shared statusColors.ts map (STANDARDS.md §1.9) instead of an inline
// status→color switch.
const summaryBucket = computed<StatusBucket | null>(() => {
  const c = counts.value
  if (c.failed > 0) return 'failed'
  if (c.awaiting_input > 0) return 'awaiting'
  if (c.computing > 0) return 'running'
  if (c.pending > 0) return 'queued'
  if (c.completed > 0) return 'done'
  return null
})

const summaryDotClass = computed(() => {
  const bucket = summaryBucket.value
  if (bucket === null) return 'bg-zinc-600/40'
  if (bucket === 'running') return `${dotClass(bucket)} pulse-soft`
  if (bucket === 'queued') return 'bg-zinc-500/60'
  return dotClass(bucket)
})

const summaryLabelClass = computed(() => {
  const bucket = summaryBucket.value
  if (bucket === null || bucket === 'queued') return 'text-content-muted'
  return textClass(bucket)
})

// --- Focused view ---
const focusedStatus = computed<MockStatus | null>(() => {
  if (props.focusedIdx === null) return null
  const s = props.node.iterStatuses[props.focusedIdx]
  return s ?? null
})

const focusedLabel = computed(() => {
  const idx = props.focusedIdx
  if (idx === null) return ''
  const base = props.iterLabel || `iter #${idx}`
  return base
})

const focusedDuration = computed<string | null>(() => {
  const idx = props.focusedIdx
  if (idx === null) return null
  const ms = props.node.iterDurations?.[idx]
  if (ms === null || ms === undefined) return null
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`
  const mins = Math.floor(ms / 60_000)
  const secs = Math.round((ms % 60_000) / 1000)
  return secs ? `${mins}m ${secs}s` : `${mins}m`
})

const focusedTileClass = computed(() => {
  const s = focusedStatus.value
  if (s === null) return 'border-dashed border-edge-subtle bg-transparent opacity-50'
  const bucket = mockStatusToBucket(s)
  if (bucket === null) return 'border-edge-subtle bg-overlay-faint'
  const opacity = bucket === 'skipped' ? ' opacity-60' : ''
  return `${cardFrameClass(bucket)} ${tileBgClass(bucket)}${opacity}`
})

const focusedStatusLabel = computed(() => {
  const s = focusedStatus.value
  switch (s) {
    case 'computing':      return 'working…'
    case 'completed':      return 'done'
    case 'failed':         return 'failed'
    case 'pending':        return 'waiting'
    case 'awaiting_input': return 'your turn'
    case 'skipped':        return 'skipped'
    case null:             return props.node.optional ? 'not in this iteration' : '—'
    default:               return String(s)
  }
})

const focusedLabelClass = computed(() => {
  const bucket = mockStatusToBucket(focusedStatus.value)
  return bucket ? textClass(bucket) : 'text-content-muted/70'
})

// --- Card style ---
// Borders keyed to the dominant status in aggregate, or focused iteration's status.
const cardClass = computed(() => {
  const c = counts.value
  if (props.focusedIdx !== null) {
    const bucket = mockStatusToBucket(focusedStatus.value)
    if (bucket === null) return 'border-dashed border-zinc-600/50 bg-base opacity-70'
    const opacity = bucket === 'skipped' ? ' opacity-70' : ''
    return `${cardFrameClass(bucket)} ${tileBgClass(bucket)}${opacity}`
  }
  const dominant: StatusBucket = c.failed > 0
    ? 'failed'
    : c.awaiting_input > 0
      ? 'awaiting'
      : c.computing > 0
        ? 'running'
        : c.pending > 0
          ? 'queued'
          : 'done'
  return `${cardFrameClass(dominant)} ${tileBgClass(dominant)}`
})

// --- Icon vocabulary (subset of EquationGraph for the mock) ---
const LLM_ICON_PATH = 'M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 00-2.456 2.456z'
const CODE_ICON_PATH = 'M17.25 6.75L22.5 12l-5.25 5.25M6.75 17.25L1.5 12l5.25-5.25M14.25 3.75L9.75 20.25'
const HITL_ICON_PATH = 'M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z'
const INFO_ICON_PATH = 'M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z'
const INPUT_ICON_PATH = 'M9 8.25H7.5a2.25 2.25 0 00-2.25 2.25v9a2.25 2.25 0 002.25 2.25h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25H15M9 12l3 3m0 0l3-3m-3 3V2.25'
const OUTPUT_ICON_PATH = 'M9 8.25H7.5a2.25 2.25 0 00-2.25 2.25v9a2.25 2.25 0 002.25 2.25h9a2.25 2.25 0 002.25-2.25v-9a2.25 2.25 0 00-2.25-2.25H15M12 2.25l3 3m0 0l-3 3m3-3h-9'
const LOOP_ICON_PATH = 'M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99'
const TOOL_ICON_PATH = 'M6 6.878V6a2.25 2.25 0 012.25-2.25h7.5A2.25 2.25 0 0118 6v.878m-12 0c.235-.083.487-.128.75-.128h10.5c.263 0 .515.045.75.128m-12 0A2.25 2.25 0 004.5 9v.878m13.5-3A2.25 2.25 0 0119.5 9v.878m0 0a2.246 2.246 0 00-.75-.128H5.25c-.263 0-.515.045-.75.128m15 0A2.25 2.25 0 0121 12v6a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 18v-6c0-.98.626-1.813 1.5-2.122'

const iconPath = computed(() => {
  switch (props.node.kind) {
    case 'llm_call': return LLM_ICON_PATH
    case 'code':     return CODE_ICON_PATH
    case 'hitl':     return HITL_ICON_PATH
    case 'info':     return INFO_ICON_PATH
    case 'flow_input':  return INPUT_ICON_PATH
    case 'flow_output': return OUTPUT_ICON_PATH
    case 'control':  return LOOP_ICON_PATH
    default:         return TOOL_ICON_PATH
  }
})

const iconBgClass = computed(() => {
  switch (props.node.kind) {
    case 'llm_call': return 'bg-gradient-to-br from-blue-500/80 to-blue-700/80'
    case 'code':     return 'bg-gradient-to-br from-emerald-500/80 to-emerald-700/80'
    case 'hitl':     return 'bg-gradient-to-br from-purple-500/80 to-purple-700/80'
    case 'info':     return 'bg-gradient-to-br from-teal-500/80 to-teal-700/80'
    case 'flow_input':  return 'bg-gradient-to-br from-zinc-500/80 to-zinc-700/80'
    case 'flow_output': return 'bg-gradient-to-br from-pink-500/80 to-pink-700/80'
    case 'control':  return 'bg-gradient-to-br from-amber-500/80 to-amber-700/80'
    case 'tool_call':
    default:         return 'bg-gradient-to-br from-sky-500/80 to-sky-700/80'
  }
})

defineExpose({ NODE_W, NODE_H })
</script>
