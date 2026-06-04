<template>
  <div
    ref="rootRef"
    class="relative group rounded-xl border border-slate-400/55 bg-overlay-light overflow-hidden outline-none transition-shadow hover:border-slate-400/75 hover:shadow-md"
    :class="[
      (selected && focusedIdx === null) ? 'ring-2 ring-blue-400' : '',
      (!(selected && focusedIdx === null) && groupIsEchoed) ? 'ring-1 ring-blue-500/40' : '',
    ]"
    :style="{ backgroundImage: DOTS_BG, width: width + 'px', height: height + 'px' }"
    tabindex="0"
    @keydown="onKeydown"
    @click="onRootClick"
    @mousedown="onRootMouseDown"
  >
    <!-- SVG overlay draws only intra-body edges. Ingress/egress edges from
         outside the foreach land on the dashed boundary (the graph draws
         those); we don't draw stubs into the first/last body node because
         they wouldn't line up with the external edge positions. -->
    <svg
      class="absolute inset-0 pointer-events-none overflow-visible"
      :width="width"
      :height="height"
    >
      <path
        v-for="edge in bodyEdgePaths"
        :key="edge.key"
        :d="edge.d"
        fill="none"
        :stroke="edge.stroke"
        :stroke-width="edge.width"
        :stroke-dasharray="edge.dash"
        :opacity="edge.opacity"
        stroke-linecap="round"
      />
    </svg>

    <div class="absolute inset-0 p-4 flex flex-col gap-3 min-h-0">
      <!-- Header: type chip (LOOP / BATCH / PICK), title + body composition
           subtitle, iteration count on the right, View All when focused. -->
      <div class="flex items-center gap-2 flex-shrink-0 min-w-0">
        <span
          class="flex-shrink-0 inline-flex items-center px-[6px] py-[1px] rounded text-[9.5px] font-semibold tracking-wider leading-[14px]"
          :class="headerChipClass"
        >{{ headerChipLabel }}</span>
        <div class="flex-1 min-w-0">
          <div class="truncate text-[13px] font-medium text-content leading-tight">{{ headerTitle }}</div>
        </div>
        <RecipeRefButton
          :ref-key="groupRefKey"
          kind="iteration-group"
          :label="headerTitle"
          :breadcrumb="groupBreadcrumb"
        />
        <button
          type="button"
          class="flex-shrink-0 flex items-center gap-1 text-[11px] text-content tabular-nums px-1.5 py-0.5 rounded border border-transparent hover:border-edge-subtle hover:bg-overlay-hover transition-colors"
          :title="`Re-run all ${data.iterCount} iterations`"
          @click.stop="emit('invalidate', data.foreachKey)"
        >
          <svg class="w-3 h-3 opacity-70" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" :d="LOOP_GLYPH" />
          </svg>
          <span>{{ data.iterCount }}</span>
        </button>
        <button
          v-if="focusedIdx !== null"
          type="button"
          class="flex-shrink-0 text-[11px] px-2.5 py-0.5 rounded-full border transition-colors bg-blue-500 border-blue-500 text-white hover:bg-blue-600"
          title="Back to aggregate (Esc)"
          @click.stop="viewAll"
        >View All</button>
      </div>

      <!-- Body row — centered horizontally in the container. -->
      <div class="relative flex-shrink-0" :style="{ height: NODE_H + 'px' }">
        <div class="absolute inset-0 flex items-start justify-center">
          <template v-for="(pos, i) in data.bodyPositions" :key="pos.id">
            <ForeachBodyPosition
              :position="pos"
              :focused-idx="focusedIdx"
              :iter-label="focusedLabel"
              :selected="selectedPositionId === pos.id"
              @invalidate-iteration="(k) => emit('invalidate', k)"
              @select="onPositionClick(pos)"
            />
            <div
              v-if="i < data.bodyPositions.length - 1"
              :style="{ width: EDGE_W + 'px' }"
              class="flex-shrink-0"
            />
          </template>
        </div>
      </div>

      <!-- Navigator: block grid (centered). The grid itself acts as the
           scrubber — mousedown-drag picks the block under the cursor. -->
      <div class="flex-1 min-h-0 border-t border-edge-subtle pt-3 flex flex-col">
        <div
          class="flex-1 min-h-0 overflow-y-auto overflow-x-auto custom-scrollbar flex justify-center items-center select-none"
          @mousedown="onGridMouseDown"
          @click="onGridClick"
        >
          <div
            :class="isGrid ? 'grid' : 'flex flex-wrap justify-center'"
            :style="gridContainerStyle"
          >
            <div
              v-for="block in blocks"
              :key="block.key"
              :data-block-idx="block.idx"
              class="rounded-[2px] border transition-all cursor-pointer"
              :class="[
                block.class,
                block.isFocused ? 'ring-2 ring-blue-500' : '',
              ]"
              :style="{ width: blockSize + 'px', height: blockSize + 'px' }"
              :title="block.title"
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import ForeachBodyPosition from './ForeachBodyPosition.vue'
import RecipeRefButton from './RecipeRefButton.vue'
import type { BodyPosition, ForeachSuperNodeData } from '../../composables/useForeachSuperNodes'
import { useRecipeReferences, injectRecipeChatIdRef } from '../../composables/useRecipeReferences'

interface Props {
  data: ForeachSuperNodeData
  width: number
  height: number
  selected: boolean
}
const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'select', key: string): void
  (e: 'invalidate', key: string): void
  // Fired when the user drills into a specific iteration (drag-scrub on the
  // navigator, click on a body tile, or keyboard arrow nav). The parent
  // EquationGraph syncs its inspect-panel selection model so the panel shows
  // that iteration's primary equation.
  (e: 'focus-iteration', iterIdx: number | null): void
}>()

const NODE_W = 240
const NODE_H = 120
const EDGE_W = 44
const SUPER_PAD = 16
const SUPER_HEADER_H = 26
const SUPER_BODY_GAP = 12

const DOTS_BG =
  'radial-gradient(circle at 1px 1px, rgba(148,163,184,0.22) 1px, transparent 0)'

const focusedIdx = ref<number | null>(null)
// Mirror local focus changes up to the parent so the inspect panel can drill
// into the same iteration. Parent's selection model owns the iteration index;
// we keep the local ref because the navigator + keyboard nav read it directly.
watch(focusedIdx, (v) => emit('focus-iteration', v))

// Which body position card the user explicitly clicked, if any. Cleared when
// the super-node itself is deselected so stale state doesn't linger when the
// user comes back later.
const clickedPositionId = ref<string | null>(null)
watch(() => props.selected, (sel) => {
  if (!sel) clickedPositionId.value = null
})

// Which body position card should show the blue ring. Click wins; otherwise
// fall back to the body position whose equation is the focused iteration's
// primary, so navigator-drag / keyboard nav rings the position whose contents
// the inspect panel is showing. Null = super-node summary view, super-node
// rings instead.
const selectedPositionId = computed<string | null>(() => {
  if (clickedPositionId.value) return clickedPositionId.value
  const idx = focusedIdx.value
  if (idx === null) return null
  const iter = props.data.flatIterations[idx]
  const primaryKey = iter?.primary?.equation_key ?? null
  if (!primaryKey) return null
  for (const pos of props.data.bodyPositions) {
    if (pos.iterEquationKeys[idx] === primaryKey) return pos.id
  }
  return null
})

const groupRefKey = computed<string>(() => `group:${props.data.foreachKey}`)

// Hover-echo: lights the super-node when the user hovers the matching
// iteration-group chip in the chat context tray, same affordance the steps
// view's IterationGroup already provides. Suppressed when already selected
// so the two rings don't fight for the same pixels.
const recipeRefs = useRecipeReferences(injectRecipeChatIdRef())
const groupIsEchoed = computed<boolean>(() =>
  recipeRefs.hoveredRefKey.value === groupRefKey.value,
)
const groupBreadcrumb = computed<string>(() => {
  const phasePath = props.data.foreach.phase_path || []
  const parts: string[] = []
  if (phasePath.length) parts.push(phasePath[phasePath.length - 1])
  parts.push(`${props.data.iterCount} iterations`)
  return parts.join(' · ')
})

// --- Header ---
// Title rule: the super-node describes the *loop*, not the body. If the user
// gave the iteration primitive an explicit display_name, that wins. Otherwise
// fall back to a deliberate count-suffixed label keyed to the rollup kind
// ("Loop · 8 items", "Pick · 4 slots", "LLM · 5 variants").

// What kind of rollup is this? Drives the count-suffix word and (later) the
// llm-batch detection that needs no super-node-specific control_kind check.
type RollupKind = 'loop' | 'slots' | 'variants'
const rollupKind = computed<RollupKind>(() => {
  const eq = props.data.foreach
  if (eq.equation_type === 'llm_batch') return 'variants'
  if (eq.equation_type === 'control' && eq.control_kind === 'approve') return 'slots'
  return 'loop'
})

const defaultLoopLabel = computed<string>(() => {
  const n = props.data.iterCount
  switch (rollupKind.value) {
    case 'slots':    return `Pick · ${n} slots`
    case 'variants': return `LLM · ${n} variants`
    default:         return `Loop · ${n} items`
  }
})

// Backend produces type-level fallbacks like "Loop", "Pick", "LLM", and
// historically "Gather Results". Treat those as "no name set" so we upgrade
// to the count-suffixed label; pass any other display_name through verbatim.
const GENERIC_DISPLAY_NAMES = new Set([
  'Loop', 'Pick', 'LLM', 'Gather Results', 'Iterations',
])

const headerTitle = computed<string>(() => {
  const dn = props.data.foreach.display_name
  if (dn && !GENERIC_DISPLAY_NAMES.has(dn)) return dn
  return defaultLoopLabel.value
})

// Type chip — encodes whether this is a generic loop, an llm-batch
// rollup, or a HITL "approve" multi-slot. Color matches the rollup kind
// (control palette for loops, llm palette for batches, hitl for slots).
const headerChipClass = computed<string>(() => {
  switch (rollupKind.value) {
    case 'variants': return 'bg-recipe-llm-tint text-recipe-llm-strong'
    case 'slots':    return 'bg-recipe-hitl-tint text-recipe-hitl-strong'
    default:         return 'bg-recipe-control-tint text-recipe-control-strong'
  }
})

const headerChipLabel = computed<string>(() => {
  switch (rollupKind.value) {
    case 'variants': return 'BATCH'
    case 'slots':    return 'PICK'
    default:         return 'LOOP'
  }
})

// LOOP_GLYPH is still used by the iteration count pill on the right.
const LOOP_GLYPH = 'M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99'

// Nesting depth: 1 = simple, 2 = grid of rows × cols, 3+ = fall back to flat.
const nestDepth = computed(() => props.data.iterDims.length)
const isGrid = computed(() => nestDepth.value === 2 && props.data.iterDims[1] > 1)
// For the 2D case, the number of columns per row drives the block chart's
// CSS grid. Outer dim is rows, inner dim is cols (matches DFS row-major).
const gridCols = computed(() => (isGrid.value ? props.data.iterDims[1] : 0))

const gridContainerStyle = computed(() => {
  if (isGrid.value) {
    return {
      gridTemplateColumns: `repeat(${gridCols.value}, ${blockSize.value}px)`,
      gap: '4px',
      width: 'max-content',
    }
  }
  return { gap: '4px' }
})

// --- Per-iteration rollup ---
function rollupAt(i: number): string {
  let sawComputing = false
  let sawAwaiting = false
  let sawPending = false
  let allDoneOrSkipped = true
  let anyPresent = false
  for (const pos of props.data.bodyPositions) {
    const s = pos.iterStatuses[i]
    if (s === null || s === undefined) continue
    anyPresent = true
    if (s === 'failed') return 'failed'
    if (s === 'awaiting_input') sawAwaiting = true
    else if (s === 'computing') sawComputing = true
    else if (s === 'pending') sawPending = true
    if (s !== 'completed' && s !== 'skipped') allDoneOrSkipped = false
  }
  if (!anyPresent) return 'pending'
  if (sawAwaiting) return 'awaiting_input'
  if (sawComputing) return 'computing'
  if (sawPending) return 'pending'
  return allDoneOrSkipped ? 'completed' : 'pending'
}

const iterationStatuses = computed<string[]>(() =>
  Array.from({ length: props.data.iterCount }, (_, i) => rollupAt(i)),
)

// "View All" is the way out of focused mode — also clears the user's
// body-position click so the super-node ring returns.
function viewAll() {
  focusedIdx.value = null
  clickedPositionId.value = null
}

const STATUS_CLASS: Record<string, string> = {
  completed: 'bg-recipe-done-strong',
  computing: 'bg-recipe-run-strong',
  awaiting_input: 'bg-recipe-await-strong',
  failed: 'bg-recipe-fail-strong',
  pending: 'bg-content-muted/40',
  skipped: 'bg-content-muted/25',
}

// --- Block chart ---
// Block size shrinks as N grows. The grid doubles as the scrubber so even
// small blocks are fine — drag works down to a few px per cell.
const blockSize = computed(() => {
  const n = props.data.iterCount
  if (n <= 64) return 14
  if (n <= 160) return 11
  if (n <= 320) return 9
  if (n <= 600) return 7
  if (n <= 1500) return 5
  if (n <= 3000) return 4
  return 3
})

interface Block { key: string; idx: number; class: string; isFocused: boolean; title: string }

const blocks = computed<Block[]>(() => {
  const arr = iterationStatuses.value
  return arr.map((s, i) => {
    const base = STATUS_CLASS[s] ?? 'bg-zinc-500/50'
    return {
      key: `bl-${i}`,
      idx: i,
      class: `${base} border-black/20`,
      isFocused: focusedIdx.value === i,
      title: `#${i} · ${props.data.iterLabels[i] ?? ''} · ${s}`,
    }
  })
})

// --- Focused label ---
const focusedLabel = computed<string>(() => {
  const idx = focusedIdx.value
  if (idx === null) return ''
  return props.data.iterLabels[idx] ?? `iter #${idx}`
})

// --- Body row geometry + edges ---
const bodyRowWidth = computed(() =>
  props.data.bodyPositions.length * NODE_W
    + Math.max(0, props.data.bodyPositions.length - 1) * EDGE_W,
)

interface EdgePath { key: string; d: string; stroke: string; width: number; dash: string; opacity: number }

function slotLeft(i: number): number { return i * (NODE_W + EDGE_W) }

function edgeStrokeForPos(src: BodyPosition): string {
  if (src.equation_type === 'tool_call') {
    const t = (src.task_type || '').toLowerCase()
    if (t.includes('image') || t.includes('video') || t.includes('upscale')) {
      return 'rgba(244,114,182,0.95)'
    }
    return 'rgba(56,189,248,0.85)'
  }
  switch (src.equation_type) {
    case 'llm_call':     return 'rgba(52,211,153,0.85)'
    case 'code':         return 'rgba(251,191,36,0.85)'
    case 'hitl':         return 'rgba(192,132,252,0.85)'
    case 'info':         return 'rgba(45,212,191,0.8)'
    case 'recipe_input': return 'rgba(148,163,184,0.85)'
    case 'control':      return 'rgba(129,140,248,0.85)'
    default:             return 'rgba(148,163,184,0.65)'
  }
}

// Body row's vertical center, relative to super-node origin. Used by the
// full-span SVG overlay so body edges share a coord system with the body
// nodes (which are positioned via flex).
const bodyCenterY = computed(() =>
  SUPER_PAD + SUPER_HEADER_H + SUPER_BODY_GAP + NODE_H / 2,
)
// Body row width + left offset when centered in the super-node.
const bodyRowContentW = computed(() => {
  const n = props.data.bodyPositions.length
  if (n === 0) return 0
  return n * NODE_W + Math.max(0, n - 1) * EDGE_W
})
const bodyLeftX = computed(() => Math.max(SUPER_PAD, (props.width - bodyRowContentW.value) / 2))

const bodyEdgePaths = computed<EdgePath[]>(() => {
  const positions = props.data.bodyPositions
  const idxById = new Map(positions.map((p, i) => [p.id, i]))
  const paths: EdgePath[] = []
  const y = bodyCenterY.value
  const originX = bodyLeftX.value
  for (const edge of props.data.bodyEdges) {
    const si = idxById.get(edge.fromId)
    const ti = idxById.get(edge.toId)
    if (si === undefined || ti === undefined) continue
    const src = positions[si]
    const tgt = positions[ti]
    const sx = originX + slotLeft(si) + NODE_W
    const tx = originX + slotLeft(ti)
    let d: string
    if (Math.abs(ti - si) === 1 && ti > si) {
      const cx = (tx - sx) * 0.5
      d = `M ${sx} ${y} C ${sx + cx} ${y}, ${tx - cx} ${y}, ${tx} ${y}`
    } else {
      const midX = (sx + tx) / 2
      const drop = NODE_H * 0.55
      d = `M ${sx} ${y} C ${midX} ${y + drop}, ${midX} ${y + drop}, ${tx} ${y}`
    }
    const idx = focusedIdx.value
    let dash = '0'
    let opacity = 0.8
    let width = 2
    if (idx === null) {
      if (tgt.optional) { dash = '3 3'; opacity = 0.5 }
    } else {
      const tStatus = tgt.iterStatuses[idx]
      const sStatus = src.iterStatuses[idx]
      if (tStatus === null || tStatus === undefined) { dash = '3 3'; opacity = 0.35 }
      else if (sStatus === 'completed' && tStatus) { opacity = 0.9; width = 2.6 }
      else { opacity = 0.6; width = 1.8 }
    }
    paths.push({ key: `e-${edge.fromId}→${edge.toId}`, d, stroke: edgeStrokeForPos(src), width, dash, opacity })
  }
  return paths
})


// --- Interactions ---
const rootRef = ref<HTMLDivElement | null>(null)
function onRootClick() {
  // Give the super-node focus so keyboard nav (arrows / WASD) works.
  rootRef.value?.focus({ preventScroll: true })
  // Background click = "select the whole thing": clear interior state so the
  // super-node ring shows and the inspect panel reverts to summary view.
  clickedPositionId.value = null
  focusedIdx.value = null
  emit('select', props.data.foreachKey)
}
// Stop left-button mousedowns from bubbling so the parent canvas's pan handler
// doesn't fight the super-node's own interactions (drag-scrub, button clicks).
// Middle-click must bubble — that's the canvas pan affordance.
function onRootMouseDown(e: MouseEvent) {
  if (e.button === 1) return
  e.stopPropagation()
}

// Body-position click — drill into the iteration that needs the user most.
// Priority: failed > awaiting_input > computing > last completed > first
// non-null. This lands the inspect panel on the actionable iteration so a
// click on the purple "Approve" tile doesn't dump the user back on the
// aggregate-loop view.
function onPositionClick(pos: BodyPosition) {
  const statuses = pos.iterStatuses
  let best: number | null = null
  for (let i = 0; i < statuses.length; i++) {
    if (statuses[i] === 'failed') { best = i; break }
  }
  if (best === null) {
    for (let i = 0; i < statuses.length; i++) {
      if (statuses[i] === 'awaiting_input') { best = i; break }
    }
  }
  if (best === null) {
    for (let i = 0; i < statuses.length; i++) {
      if (statuses[i] === 'computing') { best = i; break }
    }
  }
  if (best === null) {
    for (let i = statuses.length - 1; i >= 0; i--) {
      if (statuses[i] === 'completed') { best = i; break }
    }
  }
  if (best === null) {
    for (let i = 0; i < statuses.length; i++) {
      if (statuses[i] != null) { best = i; break }
    }
  }
  // Always notify parent we're selected; clicks anywhere inside the super
  // (including body positions) bypassed the root @click via .stop, so the
  // parent's selectedKey wouldn't update otherwise.
  clickedPositionId.value = pos.id
  emit('select', props.data.foreachKey)
  if (best !== null) focusedIdx.value = best
  rootRef.value?.focus({ preventScroll: true })
}

// --- Drag-scrub on the block grid ---
// Mousedown anywhere in the grid starts a drag; mousemove picks the block
// under the cursor. The grid effectively IS the scrubber.
function blockIdxAtPoint(x: number, y: number): number | null {
  const el = document.elementFromPoint(x, y) as Element | null
  let cur: Element | null = el
  while (cur) {
    const attr = cur.getAttribute?.('data-block-idx')
    if (attr !== null && attr !== undefined) return Number(attr)
    cur = cur.parentElement
  }
  return null
}
function onGridDrag(e: MouseEvent) {
  const idx = blockIdxAtPoint(e.clientX, e.clientY)
  if (idx !== null) focusedIdx.value = idx
}
function onGridUp() {
  window.removeEventListener('mousemove', onGridDrag)
  window.removeEventListener('mouseup', onGridUp)
}
function onGridMouseDown(e: MouseEvent) {
  // Middle-click belongs to the canvas pan handler — let it bubble.
  if (e.button === 1) return
  e.preventDefault()
  const idx = blockIdxAtPoint(e.clientX, e.clientY)
  if (idx !== null) focusedIdx.value = idx
  rootRef.value?.focus({ preventScroll: true })
  window.addEventListener('mousemove', onGridDrag)
  window.addEventListener('mouseup', onGridUp)
}
// Stop the trailing click from bubbling only when a block was actually hit —
// otherwise onRootClick would clear the iter focus mousedown just set. Clicks
// in the empty area around the blocks bubble through so the user can select
// the super-node as a whole from there.
function onGridClick(e: MouseEvent) {
  if (blockIdxAtPoint(e.clientX, e.clientY) !== null) e.stopPropagation()
}

// Linear 1D step (kept for 1D arrow-key nav).
function step(delta: number) {
  const n = props.data.iterCount
  if (n <= 0) return
  const cur = focusedIdx.value
  if (cur === null) {
    focusedIdx.value = delta > 0 ? 0 : n - 1
    return
  }
  focusedIdx.value = (cur + delta + n) % n
}
// Grid-aware step. In 2D mode, horizontal moves within a row and vertical
// moves between rows (both wrap). In 1D, any direction key steps the flat
// index through the filtered set.
function stepGrid(dx: number, dy: number) {
  const dims = props.data.iterDims
  const rows = dims[0] ?? 0
  const cols = dims[1] ?? 0
  if (rows <= 0 || cols <= 0) return
  const total = props.data.iterCount
  const cur = focusedIdx.value
  if (cur === null) {
    focusedIdx.value = dx >= 0 && dy >= 0 ? 0 : total - 1
    return
  }
  const r = Math.floor(cur / cols)
  const c = cur % cols
  const nr = (r + dy + rows) % rows
  const nc = (c + dx + cols) % cols
  focusedIdx.value = nr * cols + nc
}

function onKeydown(e: KeyboardEvent) {
  const k = e.key.toLowerCase()
  if (e.key === 'Escape') { viewAll(); e.preventDefault(); return }
  let dx = 0
  let dy = 0
  if (k === 'arrowright' || k === 'd') dx = 1
  else if (k === 'arrowleft' || k === 'a') dx = -1
  else if (k === 'arrowdown' || k === 's') dy = 1
  else if (k === 'arrowup' || k === 'w') dy = -1
  if (dx === 0 && dy === 0) return
  e.preventDefault()
  if (isGrid.value) stepGrid(dx, dy)
  else step(dx + dy)
}

defineExpose({ NODE_W, NODE_H, EDGE_W })
</script>
