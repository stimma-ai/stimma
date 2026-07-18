<template>
  <div
    class="relative rounded-lg border-2 border-dashed border-emerald-600/40 bg-emerald-500/[0.03] p-4"
    :style="{ backgroundImage: DOTS_BG }"
    tabindex="0"
    @keydown="onKeydown"
  >
    <!-- Header -->
    <div class="flex items-center gap-2 mb-3 text-[11.5px] font-mono text-content-muted">
      <span>{{ group.header }}</span>
      <span class="opacity-60">·</span>
      <span class="tabular-nums">{{ group.count }}×</span>
      <span v-if="hasOptional" class="ml-2 text-[10.5px] italic opacity-70">
        (canonical body is the union of all iteration shapes)
      </span>
    </div>

    <!-- Body row: canonical nodes, connected by SVG edges colored by source kind -->
    <div class="flex items-stretch gap-0 mb-4 overflow-x-auto custom-scrollbar py-2">
      <template v-for="(node, i) in group.bodyNodes" :key="node.id">
        <ForeachBodyNode
          :node="node"
          :focused-idx="focusedIdx"
          :iter-label="focusedLabel"
        />
        <div
          v-if="i < group.bodyNodes.length - 1"
          class="flex-shrink-0 flex items-center"
          :style="{ width: EDGE_W + 'px' }"
        >
          <svg
            :width="EDGE_W"
            :height="28"
            :viewBox="`0 0 ${EDGE_W} 28`"
            class="overflow-visible"
          >
            <path
              :d="edgePath(node, group.bodyNodes[i + 1])"
              fill="none"
              :stroke="edgeStrokeFor(node, group.bodyNodes[i + 1])"
              :stroke-width="edgeWidthFor(node, group.bodyNodes[i + 1])"
              :stroke-dasharray="edgeDashFor(node, group.bodyNodes[i + 1])"
              stroke-linecap="round"
              :opacity="edgeOpacityFor(node, group.bodyNodes[i + 1])"
            />
          </svg>
        </div>
      </template>
    </div>

    <!-- Navigator -->
    <div class="rounded-lg border border-edge-subtle bg-surface/70 backdrop-blur px-3 py-2.5 space-y-2">
      <!-- Stacked bar + summary counts + filter chips -->
      <div class="flex items-center gap-3">
        <div class="flex-shrink-0 w-48 h-2 rounded-full overflow-hidden bg-overlay-subtle flex">
          <div
            v-for="seg in summaryBarSegments"
            :key="seg.key"
            class="h-full"
            :class="seg.class"
            :style="{ width: seg.pct + '%' }"
          />
        </div>
        <div class="flex-1 min-w-0 text-[11.5px] text-content-muted truncate tabular-nums">
          <span v-if="counts.completed > 0" :class="textClass('done')">{{ counts.completed }} ok</span>
          <span v-if="counts.computing > 0" class="ml-2" :class="textClass('running')">{{ counts.computing }} running</span>
          <span v-if="counts.awaiting_input > 0" class="ml-2" :class="textClass('awaiting')">{{ counts.awaiting_input }} your turn</span>
          <span v-if="counts.failed > 0" class="ml-2" :class="textClass('failed')">{{ counts.failed }} err</span>
          <span v-if="counts.pending > 0" class="ml-2 text-content-muted/70">{{ counts.pending }} pending</span>
        </div>
        <div class="flex-shrink-0 flex items-center gap-1">
          <button
            v-for="chip in filterChips"
            :key="chip.id"
            type="button"
            class="text-[11px] px-2 py-0.5 rounded-full border transition-colors"
            :class="chip.id === activeFilter
              ? 'bg-blue-500 border-blue-500 text-white'
              : 'border-edge-subtle text-content-muted hover:text-content hover:bg-overlay-subtle'"
            @click="activeFilter = chip.id"
          >{{ chip.label }}{{ chip.count !== null ? ` (${chip.count})` : '' }}</button>
        </div>
      </div>

      <!-- Block chart -->
      <div class="relative">
        <div
          class="flex flex-wrap gap-[2px] max-h-[120px] overflow-y-auto custom-scrollbar"
          :style="{ rowGap: '2px' }"
        >
          <button
            v-for="block in blocks"
            :key="block.key"
            type="button"
            class="rounded-sm border transition-all"
            :class="[
              block.class,
              block.isFocused ? 'ring-2 ring-blue-400 ring-offset-[1px] ring-offset-surface' : '',
              block.dimmed ? 'opacity-35' : '',
            ]"
            :style="{ width: blockSize + 'px', height: blockSize + 'px' }"
            :title="block.title"
            @click="onBlockClick(block)"
          />
        </div>
      </div>

      <!-- Caption + scrubber -->
      <div class="flex items-center gap-3">
        <div class="flex-1 min-w-0 text-[11px] text-content-muted tabular-nums">
          <template v-if="focusedIdx === null">
            <button
              type="button"
              class="text-blue-400/90 hover:text-blue-300"
              @click="focusedIdx = firstMatchIdx ?? 0"
            >pin an iteration →</button>
            <span class="ml-1 italic opacity-70">showing aggregate</span>
          </template>
          <template v-else>
            <span>showing </span>
            <span class="text-content">#{{ String(focusedIdx).padStart(3, '0') }}</span>
            <span class="opacity-60"> · </span>
            <span class="text-content">{{ focusedLabel }}</span>
            <button
              type="button"
              class="ml-2 text-[10.5px] text-content-muted/80 hover:text-content underline underline-offset-2"
              @click="focusedIdx = null"
            >back to aggregate</button>
          </template>
        </div>
        <button
          type="button"
          class="w-6 h-6 flex items-center justify-center rounded border border-edge-subtle text-content-muted hover:text-content hover:bg-overlay-subtle disabled:opacity-40"
          :disabled="filteredIndices.length === 0"
          title="Previous (←)"
          @click="step(-1)"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5 8.25 12l7.5-7.5" />
          </svg>
        </button>
        <input
          type="range"
          :min="0"
          :max="Math.max(0, group.count - 1)"
          :value="focusedIdx ?? 0"
          class="flex-shrink-0 w-32 accent-blue-500"
          :disabled="group.count <= 1"
          @input="onSlider"
        />
        <button
          type="button"
          class="w-6 h-6 flex items-center justify-center rounded border border-edge-subtle text-content-muted hover:text-content hover:bg-overlay-subtle disabled:opacity-40"
          :disabled="filteredIndices.length === 0"
          title="Next (→)"
          @click="step(1)"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="m8.25 4.5 7.5 7.5-7.5 7.5" />
          </svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import ForeachBodyNode from './ForeachBodyNode.vue'
import type { MockForeachGroup, MockStatus } from './foreachMockData'
import { aggregateCounts, rollupIteration } from './foreachMockData'
import { dotClass, textClass, type StatusBucket } from '../../../utils/statusColors'

// Maps this node's own status vocabulary onto the shared statusColors.ts
// bucket type (mirrors ForeachBodyNode.vue's mockStatusToBucket); actual
// colors always come from the shared exports below.
function mockStatusToBucket(s: MockStatus): StatusBucket {
  switch (s) {
    case 'completed':      return 'done'
    case 'computing':      return 'running'
    case 'awaiting_input': return 'awaiting'
    case 'failed':          return 'failed'
    case 'skipped':         return 'skipped'
    case 'pending':
    default:                return 'queued'
  }
}

interface Props {
  group: MockForeachGroup
}
const props = defineProps<Props>()

const DOTS_BG =
  'radial-gradient(circle at 1px 1px, rgba(148,163,184,0.22) 1px, transparent 0)'

const EDGE_W = 44

// Edge color = source-kind palette, mirroring EquationGraph's edgeStroke.
// Tool calls that produce media (image-y task_types) use the hot pink that
// marks media flow in the real graph.
function edgeStrokeFor(src: { kind: string; task_type?: string }, _tgt: unknown): string {
  if (src.kind === 'tool_call') {
    const t = (src.task_type || '').toLowerCase()
    if (t.includes('image') || t.includes('video') || t.includes('upscale')) {
      return 'rgba(244,114,182,0.95)' // pink-400 — media
    }
    return 'rgba(56,189,248,0.85)' // sky
  }
  switch (src.kind) {
    case 'llm_call':     return 'rgba(52,211,153,0.85)'
    case 'code':         return 'rgba(251,191,36,0.85)'
    case 'hitl':         return 'rgba(192,132,252,0.85)'
    case 'info':         return 'rgba(45,212,191,0.8)'
    case 'flow_input': return 'rgba(148,163,184,0.85)'
    case 'control':      return 'rgba(129,140,248,0.85)'
    default:             return 'rgba(148,163,184,0.65)'
  }
}

// Curved Bézier from right-center of source to left-center of target.
function edgePath(_src: unknown, _tgt: unknown): string {
  const x0 = 0
  const x1 = EDGE_W
  const y = 14
  const cx = EDGE_W / 2
  return `M ${x0} ${y} C ${cx} ${y}, ${cx} ${y}, ${x1} ${y}`
}

// Focused mode emphasizes the edge along this iteration's path. Edges feeding
// an optional target that's absent in the focused iteration render dashed.
function edgeWidthFor(src: { id: string }, tgt: { id: string }): number {
  const i = props.group.bodyNodes.findIndex((n) => n.id === src.id)
  const j = props.group.bodyNodes.findIndex((n) => n.id === tgt.id)
  const idx = focusedIdx.value
  if (idx === null) return 2
  const sStatus = props.group.bodyNodes[i]?.iterStatuses[idx]
  const tStatus = props.group.bodyNodes[j]?.iterStatuses[idx]
  // Bold edge where data flowed (source completed; target ran or ran/skipped).
  if (sStatus === 'completed' && tStatus !== null && tStatus !== undefined) return 2.8
  return 1.8
}

function edgeDashFor(src: { id: string }, tgt: { id: string; optional?: boolean }): string {
  const j = props.group.bodyNodes.findIndex((n) => n.id === tgt.id)
  const idx = focusedIdx.value
  if (idx === null) {
    return tgt.optional ? '3 3' : '0'
  }
  const tStatus = props.group.bodyNodes[j]?.iterStatuses[idx]
  if (tStatus === null || tStatus === undefined) return '3 3'
  return '0'
}

function edgeOpacityFor(src: { id: string }, tgt: { id: string; optional?: boolean }): number {
  const j = props.group.bodyNodes.findIndex((n) => n.id === tgt.id)
  const idx = focusedIdx.value
  if (idx === null) {
    return tgt.optional ? 0.5 : 0.8
  }
  const tStatus = props.group.bodyNodes[j]?.iterStatuses[idx]
  if (tStatus === null || tStatus === undefined) return 0.35
  return 0.9
}

// --- State ---
type FilterId = 'all' | 'errors' | 'running' | 'attention'
const activeFilter = ref<FilterId>('all')
const focusedIdx = ref<number | null>(null)

// --- Per-iteration rollup ---
const iterationStatuses = computed<MockStatus[]>(() =>
  Array.from({ length: props.group.count }, (_, i) =>
    rollupIteration(props.group.bodyNodes, i),
  ),
)

const counts = computed(() => aggregateCounts(iterationStatuses.value))

const hasOptional = computed(() => props.group.bodyNodes.some((n) => n.optional))

// --- Filtering ---
function matchesFilter(status: MockStatus, f: FilterId): boolean {
  switch (f) {
    case 'all':       return true
    case 'errors':    return status === 'failed'
    case 'running':   return status === 'computing'
    case 'attention': return status === 'failed' || status === 'awaiting_input'
  }
}

const filteredIndices = computed<number[]>(() => {
  const out: number[] = []
  const arr = iterationStatuses.value
  for (let i = 0; i < arr.length; i++) {
    if (matchesFilter(arr[i], activeFilter.value)) out.push(i)
  }
  return out
})

const firstMatchIdx = computed<number | null>(() => {
  return filteredIndices.value.length > 0 ? filteredIndices.value[0] : null
})

const filterChips = computed<Array<{ id: FilterId; label: string; count: number | null }>>(() => {
  const c = counts.value
  const chips: Array<{ id: FilterId; label: string; count: number | null }> = [
    { id: 'all', label: 'all', count: null },
  ]
  if (c.failed + c.awaiting_input > 0) {
    chips.push({ id: 'attention', label: 'needs attention', count: c.failed + c.awaiting_input })
  }
  if (c.failed > 0)    chips.push({ id: 'errors', label: 'errors', count: c.failed })
  if (c.computing > 0) chips.push({ id: 'running', label: 'running', count: c.computing })
  return chips
})

// --- Summary bar ---
const STATUS_ORDER: MockStatus[] = ['completed', 'computing', 'awaiting_input', 'failed', 'pending', 'skipped']

const summaryBarSegments = computed(() => {
  const total = props.group.count || 1
  return STATUS_ORDER
    .filter((s) => counts.value[s] > 0)
    .map((s) => ({
      key: s,
      class: dotClass(mockStatusToBucket(s)),
      pct: (counts.value[s] / total) * 100,
    }))
})

// --- Block chart layout ---
// Auto-shrink block size at high N. Below ~250 iterations we render 1 block
// per iteration; above, we still render per-iteration (the user wants 1:1
// scrubbing) but smaller.
const blockSize = computed(() => {
  const n = props.group.count
  if (n <= 64) return 14
  if (n <= 160) return 11
  if (n <= 320) return 9
  if (n <= 600) return 7
  return 6
})

interface Block {
  key: string
  idx: number
  class: string
  isFocused: boolean
  dimmed: boolean
  title: string
}

const blocks = computed<Block[]>(() => {
  const arr = iterationStatuses.value
  const filterActive = activeFilter.value !== 'all'
  return arr.map((s, i) => {
    const base = dotClass(mockStatusToBucket(s))
    const matches = matchesFilter(s, activeFilter.value)
    return {
      key: `bl-${i}`,
      idx: i,
      class: `${base} border-black/20`,
      isFocused: focusedIdx.value === i,
      dimmed: filterActive && !matches,
      title: `#${i} · ${props.group.iterLabels[i] ?? ''} · ${s}`,
    }
  })
})

// --- Focused label ---
const focusedLabel = computed<string>(() => {
  const idx = focusedIdx.value
  if (idx === null) return ''
  return props.group.iterLabels[idx] ?? `iter #${idx}`
})

// --- Interactions ---
function onBlockClick(b: Block) {
  focusedIdx.value = b.idx
}

function onSlider(e: Event) {
  const v = Number((e.target as HTMLInputElement).value)
  focusedIdx.value = Number.isFinite(v) ? v : 0
}

function step(delta: number) {
  const set = filteredIndices.value
  if (set.length === 0) return
  const cur = focusedIdx.value
  if (cur === null) {
    focusedIdx.value = delta > 0 ? set[0] : set[set.length - 1]
    return
  }
  const pos = set.indexOf(cur)
  if (pos !== -1) {
    const next = (pos + delta + set.length) % set.length
    focusedIdx.value = set[next]
    return
  }
  // Current focus isn't in the filtered set — jump to nearest in travel dir.
  if (delta > 0) {
    const p = set.findIndex((i) => i > cur)
    focusedIdx.value = set[p === -1 ? 0 : p]
  } else {
    let p = -1
    for (let i = set.length - 1; i >= 0; i--) {
      if (set[i] < cur) { p = i; break }
    }
    focusedIdx.value = set[p === -1 ? set.length - 1 : p]
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowRight') { e.preventDefault(); step(1) }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1) }
  else if (e.key === 'Escape') { focusedIdx.value = null }
}
</script>
