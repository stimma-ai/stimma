<template>
  <div class="w-full h-full overflow-hidden relative bg-base">
    <!-- Empty state -->
    <div v-if="layoutNodes.length === 0" class="absolute inset-0 flex items-center justify-center">
      <div class="text-center space-y-1.5">
        <div class="text-[14px] font-medium text-content">No steps yet.</div>
        <div class="text-[12px] text-content-muted">Start the flow to see how its steps connect.</div>
      </div>
    </div>

    <!-- Pan/zoom canvas -->
    <div
      v-else
      ref="canvasRef"
      class="w-full h-full overflow-hidden cursor-grab active:cursor-grabbing"
      @mousedown="onPanStart"
      @wheel.prevent="onWheel"
      @dblclick="fitToScreen"
    >
      <div
        class="origin-top-left absolute"
        :style="{
          transform: `translate(${panX}px, ${panY}px) scale(${zoom})`,
          width: canvasW + 'px',
          height: canvasH + 'px',
        }"
      >
        <!-- Edges (SVG layer) — z-0 to keep below nodes (z-10) -->
        <svg
          class="absolute inset-0 z-0 pointer-events-none"
          :width="canvasW"
          :height="canvasH"
          :viewBox="`0 0 ${canvasW} ${canvasH}`"
        >
          <path
            v-for="(edge, i) in layoutEdges"
            :key="i"
            :d="edge.path"
            fill="none"
            :stroke="edge.stroke"
            :stroke-width="2 / zoom"
            stroke-linecap="round"
            opacity="0.8"
          />
        </svg>

        <!-- Foreach super-nodes (one big DOM element per collapsed foreach) -->
        <div
          v-for="n in superLayoutNodes"
          :key="n.key"
          class="absolute z-10"
          :style="{ left: n.x + 'px', top: n.y + 'px', width: n.w + 'px', height: n.h + 'px' }"
          @click.stop="onSuperNodeClick(n.key)"
        >
          <ForeachSuperNode
            :data="superNodes.get(n.key)!"
            :width="n.w"
            :height="n.h"
            :selected="selectedKey === n.key"
            @select="onSuperNodeClick($event)"
            @focus-iteration="(idx) => selectNode(n.key, idx)"
            @invalidate="(k) => $emit('invalidate-equation', k)"
          />
        </div>

        <!-- Equation nodes -->
        <div
          v-for="n in normalLayoutNodes"
          :key="n.key"
          class="absolute group z-10"
          :style="{ left: n.x + 'px', top: n.y + 'px', width: n.w + 'px', height: n.h + 'px' }"
          @click.stop="selectNode(n.key)"
        >
          <!-- Opaque base layer so edges don't bleed through tinted cards -->
          <div class="absolute inset-0 rounded-lg bg-base" />
          <!-- Selected highlight ring -->
          <div
            v-if="selectedKey === n.key"
            class="absolute -inset-1 rounded-lg ring-2 ring-blue-400 pointer-events-none"
          />
          <!-- Echo ring: lights up when the user hovers this node's chip in
               the chat context tray. Suppressed when already selected so the
               two rings don't fight for the same pixels. -->
          <div
            v-else-if="isNodeEchoed(n)"
            class="absolute -inset-1 rounded-lg ring-1 ring-blue-500/40 pointer-events-none"
          />
          <EquationNodeCard
            :status="n.status"
            :chip-label="typeChipLabel(n)"
            :chip-class="typeChipClass(n)"
            :title="nodeTitle(n)"
            :subtitle="nodeRuntimeLabel(n) ? null : nodeSubtitle(n)"
            :status-label="statusLabel(n)"
            :actionable="hasTask(n.key)"
          >
            <template v-if="nodeRuntimeLabel(n)" #subtitle>
              <span v-if="nodeRuntimeModelLabel(n)">{{ nodeRuntimeModelLabel(n) }}</span>
              <span v-if="nodeRuntimeModelLabel(n) && nodeRuntimeProviderLabel(n)"> · </span>
              <span
                v-if="nodeRuntimeProviderLabel(n)"
                :class="isStimmaCloudNode(n) ? 'stimma-cloud-text font-medium' : ''"
              >{{ nodeRuntimeProviderLabel(n) }}</span>
            </template>
            <template #body>
              <!-- Info: rendered markdown + any upstream media -->
              <div
                v-if="n.equation_type === 'info' && infoText(n)"
                class="flex items-start gap-1.5 w-full min-w-0"
              >
                <div
                  v-if="n.result_media_ids.length > 0"
                  class="w-8 h-8 flex-shrink-0 rounded overflow-hidden border border-edge-subtle"
                >
                  <FlowMediaTile
                    :media-id="n.result_media_ids[0]"
                    :media-ids="n.result_media_ids"
                    :index="0"
                    :thumbnail="true"
                    :thumbnail-size="64"
                    :draggable="false"
                    container-class="w-full h-full"
                    img-class="w-full h-full object-cover"
                  />
                </div>
                <div
                  class="info-prose flex-1 min-w-0 text-[10px] text-content leading-tight line-clamp-3 break-words select-text"
                  v-html="renderInfoMarkdown(infoText(n))"
                />
              </div>
              <!-- Media thumbnails -->
              <div v-else-if="n.result_media_ids.length > 0" class="flex items-center gap-1">
                <div
                  v-for="(mid, midIdx) in n.result_media_ids.slice(0, 4)"
                  :key="mid"
                  class="w-8 h-8 flex-shrink-0 rounded overflow-hidden border border-edge-subtle"
                >
                  <FlowMediaTile
                    :media-id="mid"
                    :media-ids="n.result_media_ids"
                    :index="midIdx"
                    :thumbnail="true"
                    :thumbnail-size="64"
                    :draggable="false"
                    container-class="w-full h-full"
                    img-class="w-full h-full object-cover"
                  />
                </div>
                <span
                  v-if="n.result_media_ids.length > 4"
                  class="text-[10px] text-content-muted"
                >+{{ n.result_media_ids.length - 4 }}</span>
              </div>
              <!-- LLM body: render the prompt template so the user sees what
                   this step is being asked, instead of an empty card. -->
              <div
                v-else-if="isLlm(n) && n.description"
                class="text-[10.5px] leading-snug line-clamp-3 text-content-muted self-start whitespace-pre-wrap break-words"
                :title="n.description"
              >{{ n.description }}</div>
              <!-- Failed indicator — keep it short; the detail panel has the
                   full treatment (ask-assistant + devMode raw error). -->
              <div
                v-else-if="n.status === 'failed'"
                class="text-[10px] leading-tight line-clamp-2 self-start text-flow-fail-strong"
              >This step failed.</div>
            </template>
            <template #footer-actions>
              <FlowRefButton
                :ref-key="nodeRefKey(n)"
                kind="equation"
                :label="nodeTitle(n)"
                :breadcrumb="nodeBreadcrumb(n)"
              />
              <button
                v-if="n.status === 'completed' || n.status === 'failed' || n.status === 'invalidated'"
                class="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded border border-transparent text-content hover:bg-overlay-hover hover:border-edge-subtle transition-colors"
                title="Re-run this step"
                @click.stop="$emit('invalidate-equation', n.source_key ?? n.key)"
              >
                <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                </svg>
              </button>
            </template>
          </EquationNodeCard>
        </div>
      </div>
    </div>

    <!-- Inspect panel — always docked at the bottom. -->
    <GraphInspectPanel
      v-if="inspectPanelOpen"
      :equation="inspectEquation"
      :super-node="selectedSuperNode"
      :focused-iter-idx="focusedIterIdx"
      :tasks="props.tasks"
      :equations-by-key="props.equationsByKey"
      :flow-id="props.flowId"
      :input-schema="props.inputSchema"
      :input-values="props.inputValues"
      :submitting-inputs="props.submittingInputs"
      :height="inspectPanelHeight"
      :dev-mode="devMode"
      @close="closeInspectPanel"
      @invalidate-equation="(k) => $emit('invalidate-equation', k)"
      @fix-step-with-agent="(eq) => $emit('fix-step-with-agent', eq)"
      @resolve-task="(t, r) => $emit('resolve-task', t, r)"
      @resolve-error-task="(t, a, v) => $emit('resolve-error-task', t, a, v)"
      @edit-flow="(t) => $emit('edit-flow', t)"
      @update-inputs="(p) => $emit('update-inputs', p)"
      @focus-iteration="(_k, idx) => focusedIterIdx = idx"
      @resize-start="startInspectPanelResize"
    />

    <!-- Zoom / fit controls — pushed above the inspect panel when it's open
         so they don't disappear behind it. -->
    <div
      v-if="layoutNodes.length > 0"
      class="absolute left-1/2 -translate-x-1/2 z-10 flex items-center gap-1 px-2 py-1 rounded-full border border-edge-subtle backdrop-blur-md"
      :class="inspectPanelOpen ? '' : 'bottom-4'"
      :style="inspectPanelOpen
        ? { bottom: `${inspectPanelHeight + 16}px`, background: 'var(--color-lineage-controls-bg, rgba(20,20,20,0.85))' }
        : { background: 'var(--color-lineage-controls-bg, rgba(20,20,20,0.85))' }"
    >
      <button
        class="w-7 h-7 flex items-center justify-center rounded-full text-content-muted hover:text-content hover:bg-overlay-light transition-colors"
        title="Zoom out"
        @click="zoomBy(-0.2)"
      >
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 12h-15" />
        </svg>
      </button>
      <span class="text-content-muted text-[10px] w-8 text-center">{{ Math.round(zoom * 100) }}%</span>
      <button
        class="w-7 h-7 flex items-center justify-center rounded-full text-content-muted hover:text-content hover:bg-overlay-light transition-colors"
        title="Zoom in"
        @click="zoomBy(0.2)"
      >
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
      </button>
      <div class="w-px h-4 bg-edge-subtle mx-0.5" />
      <button
        class="w-7 h-7 flex items-center justify-center rounded-full text-content-muted hover:text-content hover:bg-overlay-light transition-colors"
        title="Fit to screen (double-click canvas)"
        @click="fitToScreen"
      >
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import * as dagre from '@dagrejs/dagre'
import FlowMediaTile from './FlowMediaTile.vue'
import type { FlowEquation, FlowTask } from '../../composables/useFlowsApi'
import { useProvidersApi } from '../../composables/useProvidersApi'
import { renderSafeMarkdown } from '../../utils/sanitizeHtml'
import {
  buildForeachSuperNodes,
  buildApproveSuperNodes,
  buildLlmBatchSuperNodes,
  type ForeachSuperNodeData,
} from '../../composables/useForeachSuperNodes'
import ForeachSuperNode from './ForeachSuperNode.vue'
import GraphInspectPanel from './GraphInspectPanel.vue'
import FlowRefButton from './FlowRefButton.vue'
import EquationNodeCard from './EquationNodeCard.vue'
import { TASK_TYPE_LABELS } from '../../utils/taskTypeIcons'
import { makeProfileKey } from '../../utils/storageKeys'
import { useFlowReferences, injectFlowChatIdRef } from '../../composables/useFlowReferences'
import { STIMMA_CLOUD_PROVIDER_ID } from '../../utils/stimmaCloud'

const props = withDefaults(defineProps<{
  equationsByKey: Map<string, FlowEquation>
  tasks: FlowTask[]
  executionState?: string
  devMode?: boolean
  // When true (default), foreach + its iterations collapse into a single
  // super-node. When false, every iteration's equations render as raw nodes
  // (the original expanded dagre layout).
  collapseForeach?: boolean
  // Forwarded into GraphInspectPanel so its trace-fetch endpoint resolves
  // against the correct flow. Null when the view hasn't loaded one yet.
  flowId?: number | string | null
  // Forwarded into GraphInspectPanel so selecting a flow_input node in
  // the graph offers the same edit affordance the steps-view input card
  // provides. The panel filters the schema down to the selected field.
  inputSchema?: Record<string, any> | null
  inputValues?: Record<string, any> | null
  submittingInputs?: boolean
}>(), {
  collapseForeach: true,
  flowId: null,
  inputSchema: null,
  inputValues: null,
  submittingInputs: false,
})

const emit = defineEmits<{
  (e: 'invalidate-equation', key: string): void
  (e: 'fix-step-with-agent', equation: { equation_key: string; display_name?: string | null }): void
  (e: 'resolve-task', task: FlowTask, resolution: any): void
  (e: 'resolve-error-task', task: FlowTask, action: string, value?: any): void
  (e: 'edit-flow', task: FlowTask): void
  (e: 'update-inputs', partial: Record<string, any>): void
}>()

const INSPECT_PANEL_HEIGHT_KEY = makeProfileKey('flow_graph', 'inspect_panel_height')
const INSPECT_PANEL_OPEN_KEY = makeProfileKey('flow_graph', 'inspect_panel_open')
const INSPECT_PANEL_DEFAULT_HEIGHT = 360
const INSPECT_PANEL_MIN_HEIGHT = 180
const INSPECT_PANEL_MAX_HEIGHT = 720

function clampInspectPanelHeight(height: number): number {
  return Math.min(INSPECT_PANEL_MAX_HEIGHT, Math.max(INSPECT_PANEL_MIN_HEIGHT, height))
}

const inspectPanelHeight = ref(clampInspectPanelHeight(Number(localStorage.getItem(INSPECT_PANEL_HEIGHT_KEY)) || INSPECT_PANEL_DEFAULT_HEIGHT))
watch(inspectPanelHeight, (height) => {
  try { localStorage.setItem(INSPECT_PANEL_HEIGHT_KEY, String(Math.round(height))) } catch {}
})
const inspectPanelOpen = ref(localStorage.getItem(INSPECT_PANEL_OPEN_KEY) === 'true')
watch(inspectPanelOpen, (open) => {
  try { localStorage.setItem(INSPECT_PANEL_OPEN_KEY, String(open)) } catch {}
})

let stopActiveInspectPanelResize: (() => void) | null = null
function startInspectPanelResize(e: MouseEvent) {
  e.preventDefault()
  e.stopPropagation()
  stopActiveInspectPanelResize?.()
  const startY = e.clientY
  const startHeight = inspectPanelHeight.value
  const previousUserSelect = document.body.style.userSelect
  const previousCursor = document.body.style.cursor
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'row-resize'
  window.getSelection()?.removeAllRanges()

  function onMove(ev: MouseEvent) {
    ev.preventDefault()
    const delta = startY - ev.clientY
    inspectPanelHeight.value = clampInspectPanelHeight(startHeight + delta)
  }
  function onUp() {
    document.body.style.userSelect = previousUserSelect
    document.body.style.cursor = previousCursor
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
    stopActiveInspectPanelResize = null
  }
  stopActiveInspectPanelResize = onUp
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

// Tool/provider display-name lookup mirrors EquationTraceRow so graph nodes
// read the same as trace rows ("Flux Klein 9b" / "ComfyUI") rather than raw
// slugs. The cache is shared across views; we just trigger a fetch on mount.
const { cachedTools, cachedProviders, fetchProvidersAndTools } = useProvidersApi()
onMounted(() => {
  fetchProvidersAndTools().catch(() => {})
})

// Currently-selected node key. Drives the inspect panel chrome. Cleared if
// the selected node disappears (e.g. flow re-parsed).
const selectedKey = ref<string | null>(null)
// Panel visibility is intentionally separate from selection. Once opened, the
// panel stays put until closed; selection may disappear during graph refreshes.
// When a super-node is selected and the user has drilled into one of its
// iterations, this is that iteration's index in the super-node's flat list.
// Null = super-node summary view; defined = single-equation view scoped to
// that iteration's primary equation.
const focusedIterIdx = ref<number | null>(null)
function selectNode(key: string | null, iterIdx: number | null = null) {
  selectedKey.value = key
  focusedIterIdx.value = iterIdx
  if (key) inspectPanelOpen.value = true
}
function clearInspectSelection() {
  selectedKey.value = null
  focusedIterIdx.value = null
}
function closeInspectPanel() {
  clearInspectSelection()
  inspectPanelOpen.value = false
}
// Persisted per-flow so flipping tabs / reloading keeps the user on the
// same node. Keys equation_key (or super-node key) plus iteration index;
// the existing post-equation-load watcher below clears the value if the
// stored key no longer exists in the current graph (e.g. a step was
// renamed by a flow re-parse).
const selectionKey = computed<string | null>(() => {
  if (props.flowId == null) return null
  return makeProfileKey('flow_graph', String(props.flowId), 'selection')
})
function loadSelection() {
  const k = selectionKey.value
  if (!k) {
    selectedKey.value = null
    focusedIterIdx.value = null
    return
  }
  try {
    const raw = localStorage.getItem(k)
    if (!raw) {
      selectedKey.value = null
      focusedIterIdx.value = null
      return
    }
    const parsed = JSON.parse(raw)
    selectedKey.value = typeof parsed?.key === 'string' ? parsed.key : null
    focusedIterIdx.value = typeof parsed?.iterIdx === 'number' ? parsed.iterIdx : null
  } catch {
    selectedKey.value = null
    focusedIterIdx.value = null
  }
}
function saveSelection() {
  const k = selectionKey.value
  if (!k) return
  try {
    if (selectedKey.value == null) {
      localStorage.removeItem(k)
      return
    }
    localStorage.setItem(k, JSON.stringify({
      key: selectedKey.value,
      iterIdx: focusedIterIdx.value,
    }))
  } catch {}
}
// Restore on flowId arrival/change so each flow gets its own spot.
watch(selectionKey, () => loadSelection(), { immediate: true })
watch([selectedKey, focusedIterIdx], () => saveSelection())
watch(
  () => [...props.equationsByKey.keys()].join('\n'),
  () => {
    if (selectedKey.value && !props.equationsByKey.has(selectedKey.value)) {
      clearInspectSelection()
    }
  }
)
const selectedNode = computed<LayoutNode | null>(() => {
  if (!selectedKey.value) return null
  return layoutNodes.value.find((n) => n.key === selectedKey.value) || null
})
const selectedSuperNode = computed<ForeachSuperNodeData | null>(() => {
  if (!selectedKey.value) return null
  return superNodes.value.get(selectedKey.value) || null
})
// Resolve focused-iteration drill-down to the equation we'd inspect: the
// iteration's primary (the body position with the producing tool/llm/code).
// Used by the panel trace fetcher.
const focusedIterationEquation = computed<FlowEquation | null>(() => {
  const sn = selectedSuperNode.value
  if (!sn || focusedIterIdx.value == null) return null
  const fit = sn.flatIterations[focusedIterIdx.value]
  return fit?.primary || null
})
// Equation passed to the inspect panel: focused iteration's primary if any,
// else the underlying equation for the selected key (ignored when the
// selection is a super-node header without iteration focus).
const inspectEquation = computed<FlowEquation | null>(() => {
  if (focusedIterationEquation.value) return focusedIterationEquation.value
  if (!selectedKey.value) return null
  if (selectedSuperNode.value && focusedIterIdx.value == null) return null
  return props.equationsByKey.get(resolveActionKey(selectedKey.value)) || null
})

// Synthetic output nodes don't have their own equation — actions fall through
// to the source equation (the node that produced the output).
function resolveActionKey(key: string): string {
  const n = layoutNodes.value.find((x) => x.key === key)
  return n?.source_key ?? key
}
// Super-node click handler. Selecting a *different* super-node resets to
// summary view; clicking the *same* super-node leaves iteration focus alone
// — otherwise mousedown-on-navigator (drag-scrub sets focusedIdx) followed
// by the trailing click event would immediately wipe the focus the user
// just chose. View All in the super-node header is the explicit way to
// clear iteration focus.
function onSuperNodeClick(key: string) {
  if (selectedKey.value !== key) selectNode(key)
}

// ---- Layout constants ----
const NODE_W = 240
const NODE_H = 116
const NODE_GAP_Y = 24

const PADDING = 48

// Super-node (foreach collapse) sizing. Keep body constants in sync with
// ForeachSuperNode / ForeachBodyPosition.
const SUPER_BODY_NODE_W = 240
const SUPER_BODY_NODE_H = 120
const SUPER_BODY_EDGE_W = 44
const SUPER_PAD = 16
const SUPER_HEADER_H = 26
const SUPER_BODY_GAP = 12
const SUPER_MIN_W = 480

// Rough constants matching ForeachSuperNode's block chart layout.
const BLOCK_GAP = 4
function estBlockSize(n: number): number {
  if (n <= 64) return 14
  if (n <= 160) return 11
  if (n <= 320) return 9
  if (n <= 600) return 7
  if (n <= 1500) return 5
  if (n <= 3000) return 4
  return 3
}

// Sanity ceiling so a runaway foreach doesn't render a 50000px-tall node.
// In normal use the supernode grows to fit; only past this does the nav
// clip and scroll. Anyone running >100 rows of iterations gets ridiculous UI.
const GRID_ROW_CAP = 100
// Chrome around the block chart inside the navigator: border-t (1) + pt-3
// (12) + a hair of slack. Parent's p-4 supplies the bottom inset.
const NAV_CHROME_H = 16
function navHeightFor(s: ForeachSuperNodeData, w: number): number {
  const b = estBlockSize(s.iterCount)
  const isGrid2D = s.iterDims.length === 2 && s.iterDims[1] > 1
  let rows: number
  if (isGrid2D) {
    rows = Math.min(s.iterDims[0], GRID_ROW_CAP)
  } else {
    // 1D: blocks are flex-wrap'd, so estimate rows from available width.
    const availW = Math.max(0, w - SUPER_PAD * 2)
    const perRow = Math.max(1, Math.floor((availW + BLOCK_GAP) / (b + BLOCK_GAP)))
    rows = Math.min(GRID_ROW_CAP, Math.ceil(s.iterCount / perRow))
  }
  const gridH = rows * b + Math.max(0, rows - 1) * BLOCK_GAP
  return gridH + NAV_CHROME_H
}

function computeSuperSize(s: ForeachSuperNodeData): { w: number; h: number } {
  const n = s.bodyPositions.length
  const bodyW = n * SUPER_BODY_NODE_W + Math.max(0, n - 1) * SUPER_BODY_EDGE_W
  // 2D grid may need a wider super-node if many inner cols.
  let minW = SUPER_MIN_W
  if (s.iterDims.length === 2 && s.iterDims[1] > 1) {
    const cols = s.iterDims[1]
    const b = estBlockSize(s.iterCount)
    const gridW = cols * b + Math.max(0, cols - 1) * BLOCK_GAP + 48 // padding
    minW = Math.max(minW, gridW + 280) // reserve nav chrome
  }
  const w = Math.max(bodyW + SUPER_PAD * 2, minW)
  // Two gaps inside the super-node: header→body and body→nav (flex-col gap-3).
  const h = SUPER_PAD * 2 + SUPER_HEADER_H + SUPER_BODY_GAP * 2 + SUPER_BODY_NODE_H + navHeightFor(s, w)
  return { w, h }
}

// Super-nodes derived from the live equation set. Keyed by the iteration
// primitive's equation_key (foreach or hitl.approve) so downstream deps
// resolve unchanged. Returns an empty map when the user toggles the view
// into expanded mode.
const superNodes = computed<Map<string, ForeachSuperNodeData>>(() => {
  if (!props.collapseForeach) return new Map()
  const m = new Map<string, ForeachSuperNodeData>()
  for (const s of buildForeachSuperNodes(props.equationsByKey)) m.set(s.foreachKey, s)
  for (const s of buildApproveSuperNodes(props.equationsByKey)) m.set(s.foreachKey, s)
  for (const s of buildLlmBatchSuperNodes(props.equationsByKey)) m.set(s.foreachKey, s)
  return m
})

// ---- Canvas pan/zoom state ----
const canvasRef = ref<HTMLElement | null>(null)
const panX = ref(0)
const panY = ref(0)
const zoom = ref(1)
let isPanning = false
let panStart = { x: 0, y: 0, px: 0, py: 0 }

// ---- Graph layout (positions only, computed by dagre) ----
interface LayoutNode {
  key: string
  x: number
  y: number
  w: number
  h: number
  is_super: boolean
  equation_type: string
  display_name: string | null
  phase_path: string[]
  status: string
  error: string | null
  result_media_ids: number[]
  result: unknown
  task_type: string | null
  tool_id: string | null
  hitl_kind: string | null
  description: string | null
  subtitle: string | null
  routing_kind: string | null
  // Synthetic "flow_output" nodes mirror a real equation's state. source_key
  // points at the equation that produced them; for real nodes this is null.
  source_key: string | null
}

interface SyntheticEdge {
  src: string
  tgt: string
}

const layout = ref<{
  nodes: LayoutNode[]
  syntheticEdges: SyntheticEdge[]
  width: number
  height: number
}>({
  nodes: [],
  syntheticEdges: [],
  width: 800,
  height: 600,
})

const OUTPUT_PREFIX = '__output__/'

function resolveColumnOverlaps(nodes: LayoutNode[]): LayoutNode[] {
  const columns: LayoutNode[][] = []

  for (const node of nodes) {
    const column = columns.find(group =>
      group.some(existing =>
        node.x < existing.x + existing.w && node.x + node.w > existing.x
      )
    )

    if (column) {
      column.push(node)
    } else {
      columns.push([node])
    }
  }

  const adjusted = new Map<string, LayoutNode>()

  for (const column of columns) {
    const sorted = [...column].sort((a, b) => (a.y - b.y) || a.key.localeCompare(b.key))
    let nextY = -Infinity

    for (const node of sorted) {
      const y = Math.max(node.y, nextY)
      adjusted.set(node.key, { ...node, y })
      nextY = y + node.h + NODE_GAP_Y
    }
  }

  return nodes.map(node => adjusted.get(node.key) ?? node)
}

// On the happy path, foreach_iteration wrappers are pure bookkeeping: they
// mirror a single child's result via _result_from and duplicate its thumbnail
// in the graph. Hide them from the viz unless they carry their own error.
function isHiddenIterationWrapper(eq: FlowEquation): boolean {
  if (eq.equation_type !== 'control') return false
  if (eq.control_kind !== 'foreach_iteration') return false
  return eq.status !== 'failed'
}

function buildLayout() {
  const allEqs = [...props.equationsByKey.values()]
  if (allEqs.length === 0) {
    layout.value = { nodes: [], syntheticEdges: [], width: 800, height: 600 }
    return
  }

  // Redirect table: hidden wrapper key → the inner NodeRef its consumers
  // should connect to instead. Prefer `result_from` (the NodeRef the wrapper
  // mirrors); fall back to the last dependency for rows persisted before we
  // started exposing it. Chase redirects transitively so stacked wrappers
  // collapse cleanly.
  const redirect = new Map<string, string>()
  for (const eq of allEqs) {
    if (!isHiddenIterationWrapper(eq)) continue
    const target = eq.result_from
      || (eq.dependencies && eq.dependencies.length > 0
            ? eq.dependencies[eq.dependencies.length - 1]
            : null)
    if (target) redirect.set(eq.equation_key, target)
  }
  // Every equation absorbed into a super-node (iteration wrappers + their
  // body equations) redirects to the foreach primitive so external deps and
  // edges resolve to the single super-node key.
  const absorbedNonForeach = new Set<string>()
  for (const s of superNodes.value.values()) {
    for (const k of s.absorbedKeys) {
      if (k === s.foreachKey) continue
      absorbedNonForeach.add(k)
      redirect.set(k, s.foreachKey)
    }
  }
  function resolveDep(key: string): string {
    let k = key
    const seen = new Set<string>()
    while (redirect.has(k) && !seen.has(k)) {
      seen.add(k)
      k = redirect.get(k)!
    }
    return k
  }

  const eqs = allEqs.filter(
    e => !isHiddenIterationWrapper(e) && !absorbedNonForeach.has(e.equation_key),
  )

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const d = dagre as any
  const GraphClass = d.Graph || d.graphlib?.Graph || d.default?.Graph
  const layoutFn = d.layout || d.default?.layout
  const g = new GraphClass()
  g.setGraph({ rankdir: 'LR', nodesep: 16, ranksep: 100, marginx: PADDING, marginy: PADDING })
  g.setDefaultEdgeLabel(() => ({}))

  const keySet = new Set(eqs.map((e) => e.equation_key))
  const inputKeys = new Set(eqs.filter(e => e.equation_type === 'flow_input').map(e => e.equation_key))
  function nodeSizeFor(eq: FlowEquation): { w: number; h: number } {
    const s = superNodes.value.get(eq.equation_key)
    if (s) return computeSuperSize(s)
    return { w: NODE_W, h: NODE_H }
  }
  for (const eq of eqs) {
    const { w, h } = nodeSizeFor(eq)
    g.setNode(eq.equation_key, { width: w, height: h })
  }
  const hasIncoming = new Set<string>()
  for (const eq of eqs) {
    const seenForThis = new Set<string>()
    for (const dep of eq.dependencies ?? []) {
      const resolved = resolveDep(dep)
      if (resolved === eq.equation_key) continue
      if (seenForThis.has(resolved)) continue
      seenForThis.add(resolved)
      if (keySet.has(resolved)) {
        g.setEdge(resolved, eq.equation_key)
        hasIncoming.add(eq.equation_key)
      }
    }
  }
  // Non-input nodes with no incoming edges (e.g. an LLM call whose prompt
  // references flow inputs via string interpolation rather than NodeRefs)
  // would otherwise be placed at rank 0, visually colliding with inputs.
  // Anchor them off an input so dagre ranks them at column ≥ 1.
  const anchorInput = eqs.find(e => inputKeys.has(e.equation_key))
  if (anchorInput) {
    for (const eq of eqs) {
      if (inputKeys.has(eq.equation_key)) continue
      if (hasIncoming.has(eq.equation_key)) continue
      g.setEdge(anchorInput.equation_key, eq.equation_key, { weight: 0 })
    }
  }

  // Synthetic flow_output nodes — the mirror image of flow_input. Drawn
  // for equations the flow's `return` actually surfaces (backend sets
  // `is_output` from graph.output_keys). This replaces the earlier "anything
  // without a downstream consumer is an output" heuristic, which flagged
  // dangling side-effect calls (e.g. `hitl.approve(x)` whose result isn't
  // consumed) as spurious Output boxes on the right margin.
  const outputSources = eqs.filter(eq => eq.is_output === true)
  const syntheticEdges: SyntheticEdge[] = []
  for (const src of outputSources) {
    const outKey = OUTPUT_PREFIX + src.equation_key
    g.setNode(outKey, { width: NODE_W, height: NODE_H })
    g.setEdge(src.equation_key, outKey)
    syntheticEdges.push({ src: src.equation_key, tgt: outKey })
  }

  layoutFn(g)

  // Pin flow_input nodes to the leftmost column — dagre's rank minimization
  // pushes them rightward to shorten edges, but users expect inputs on the left.
  const nonInputXs = eqs
    .filter(e => !inputKeys.has(e.equation_key))
    .map(e => g.node(e.equation_key).x - nodeSizeFor(e).w / 2)
  const leftmostNonInput = nonInputXs.length ? Math.min(...nonInputXs) : Infinity
  const inputXs = eqs
    .filter(e => inputKeys.has(e.equation_key))
    .map(e => g.node(e.equation_key).x - nodeSizeFor(e).w / 2)
  const leftmostInput = inputXs.length ? Math.min(...inputXs) : PADDING
  const inputX = leftmostInput < leftmostNonInput ? leftmostInput : PADDING

  // Mirror treatment for synthetic outputs — pin to the rightmost column so
  // they form a clean terminus even when dagre's rank assignment varies
  // across branches of different depths.
  const realRightEdges = eqs.map(e => g.node(e.equation_key).x + nodeSizeFor(e).w / 2)
  const rightmostReal = realRightEdges.length ? Math.max(...realRightEdges) : 0
  const outputX = rightmostReal + 100

  const realNodes: LayoutNode[] = eqs.map((eq) => {
    const pos = g.node(eq.equation_key)
    const { w, h } = nodeSizeFor(eq)
    const isSuper = superNodes.value.has(eq.equation_key)
    return {
      key: eq.equation_key,
      x: inputKeys.has(eq.equation_key) ? inputX : pos.x - w / 2,
      y: pos.y - h / 2,
      w,
      h,
      is_super: isSuper,
      equation_type: eq.equation_type,
      display_name: eq.display_name ?? null,
      phase_path: eq.phase_path ?? [],
      status: eq.status,
      error: eq.error ?? null,
      result_media_ids: eq.result_media_ids ?? [],
      result: eq.result ?? null,
      task_type: eq.task_type ?? null,
      tool_id: eq.tool_id ?? null,
      hitl_kind: eq.hitl_kind ?? null,
      description: eq.description ?? null,
      subtitle: eq.subtitle ?? null,
      routing_kind: eq.routing_kind ?? null,
      source_key: null,
    }
  })
  const outNodes: LayoutNode[] = outputSources.map((src) => {
    const outKey = OUTPUT_PREFIX + src.equation_key
    const pos = g.node(outKey)
    return {
      key: outKey,
      x: outputX,
      y: pos.y - NODE_H / 2,
      w: NODE_W,
      h: NODE_H,
      is_super: false,
      equation_type: 'flow_output',
      display_name: outputDisplayName(src),
      phase_path: src.phase_path ?? [],
      status: outputStatusForSource(src.status),
      error: null,
      result_media_ids: src.result_media_ids ?? [],
      result: src.result ?? null,
      task_type: null,
      tool_id: null,
      hitl_kind: null,
      description: null,
      subtitle: null,
      routing_kind: null,
      source_key: src.equation_key,
    }
  })
  const nodes = resolveColumnOverlaps([...realNodes, ...outNodes])

  const gi = g.graph()
  const maxX = Math.max(...nodes.map(n => n.x + n.w), 800)
  const maxY = Math.max(...nodes.map(n => n.y + n.h), 600)
  layout.value = {
    nodes,
    syntheticEdges,
    width: Math.max(gi.width ?? 800, maxX) + PADDING,
    height: Math.max(gi.height ?? 600, maxY) + PADDING,
  }
}

// Rebuild when anything the dagre layout consumes changes — not just the set
// of keys. Reparses and agent-driven graph edits frequently preserve the key
// set while reshaping edges (dependencies), synthetic output nodes (is_output),
// iteration-wrapper redirects (control_kind/result_from), or the input-column
// pinning (equation_type). Keying the watcher to keys alone left the layout
// stuck on the old topology until something added/removed a key.
const structuralSig = computed(() =>
  [...props.equationsByKey.values()]
    .map(e => [
      e.equation_key,
      e.equation_type,
      e.control_kind ?? '',
      e.is_output ? 1 : 0,
      e.output_name ?? '',
      e.display_name ?? '',
      e.result_from ?? '',
      (e.dependencies ?? []).join(','),
    ].join('|'))
    .sort()
    .join('\n')
)
watch(structuralSig, () => {
  buildLayout()
  nextTick(() => fitToScreen())
})
// Toggle between collapsed (super-nodes) and expanded (raw) — rebuild layout
// when the user flips the toolbar switch.
watch(() => props.collapseForeach, () => {
  buildLayout()
  nextTick(() => fitToScreen())
})
onMounted(() => {
  buildLayout()
  nextTick(() => fitToScreen())
})

// ---- Live node data: merge dagre positions with reactive status/media/error ----
const layoutNodes = computed<LayoutNode[]>(() =>
  layout.value.nodes.map((n) => {
    // Synthetic output nodes mirror their source equation's live state so
    // clicking an output shows the producer's status / error / media without
    // the user having to hop back to the source node.
    if (n.source_key) {
      const src = props.equationsByKey.get(n.source_key)
      if (!src) return n
      return {
        ...n,
        status: outputStatusForSource(src.status),
        error: src.error ?? null,
        result_media_ids: src.result_media_ids ?? [],
        result: src.result ?? null,
        display_name: outputDisplayName(src, n.display_name),
      }
    }
    const eq = props.equationsByKey.get(n.key)
    if (!eq) return n
    return {
      ...n,
      status: eq.status,
      error: eq.error ?? null,
      result_media_ids: eq.result_media_ids ?? [],
      result: eq.result ?? null,
      display_name: eq.display_name ?? n.display_name,
      task_type: eq.task_type ?? n.task_type,
      tool_id: eq.tool_id ?? n.tool_id,
      hitl_kind: eq.hitl_kind ?? n.hitl_kind,
      description: eq.description ?? n.description,
      subtitle: eq.subtitle ?? n.subtitle,
      routing_kind: eq.routing_kind ?? n.routing_kind,
    }
  })
)

const canvasW = computed(() => layout.value.width)
const canvasH = computed(() => layout.value.height)

const superLayoutNodes = computed<LayoutNode[]>(() =>
  layoutNodes.value.filter((n) => n.is_super),
)
const normalLayoutNodes = computed<LayoutNode[]>(() =>
  layoutNodes.value.filter((n) => !n.is_super),
)

// ---- Edges ----
interface LayoutEdge {
  path: string
  stroke: string
}

const layoutEdges = computed<LayoutEdge[]>(() => {
  const posMap = new Map<string, { x: number; y: number; w: number; h: number }>()
  for (const n of layout.value.nodes) posMap.set(n.key, { x: n.x, y: n.y, w: n.w, h: n.h })

  // Same redirect logic as buildLayout — hidden iteration wrappers must not
  // emit dangling edges. Recompute here (rather than share state) because
  // buildLayout runs off the structural watcher while layoutEdges is a
  // computed that can re-run on status updates without a rebuild.
  const redirect = new Map<string, string>()
  for (const eq of props.equationsByKey.values()) {
    if (!isHiddenIterationWrapper(eq)) continue
    const target = eq.result_from
      || (eq.dependencies && eq.dependencies.length > 0
            ? eq.dependencies[eq.dependencies.length - 1]
            : null)
    if (target) redirect.set(eq.equation_key, target)
  }
  // Super-node absorption: iteration wrappers + body equations redirect to
  // the foreach primitive so external deps land on the super-node boundary.
  for (const s of superNodes.value.values()) {
    for (const k of s.absorbedKeys) {
      if (k !== s.foreachKey) redirect.set(k, s.foreachKey)
    }
  }
  function resolveDep(key: string): string {
    let k = key
    const seen = new Set<string>()
    while (redirect.has(k) && !seen.has(k)) {
      seen.add(k)
      k = redirect.get(k)!
    }
    return k
  }

  const exitEdges = new Map<string, string[]>() // srcKey → [tgtKey]
  const enterEdges = new Map<string, string[]>() // tgtKey → [srcKey]

  for (const n of layout.value.nodes) {
    const eq = props.equationsByKey.get(n.key)
    if (!eq) continue
    const seenForThis = new Set<string>()
    for (const dep of eq.dependencies ?? []) {
      const resolved = resolveDep(dep)
      if (resolved === n.key) continue
      if (seenForThis.has(resolved)) continue
      seenForThis.add(resolved)
      if (!posMap.has(resolved)) continue
      if (!exitEdges.has(resolved)) exitEdges.set(resolved, [])
      exitEdges.get(resolved)!.push(n.key)
      if (!enterEdges.has(n.key)) enterEdges.set(n.key, [])
      enterEdges.get(n.key)!.push(resolved)
    }
  }

  // Synthetic edges (source equation → flow_output node) feed the same port
  // allocator so output edges share spacing/rendering with real ones.
  for (const { src, tgt } of layout.value.syntheticEdges) {
    if (!posMap.has(src) || !posMap.has(tgt)) continue
    if (!exitEdges.has(src)) exitEdges.set(src, [])
    exitEdges.get(src)!.push(tgt)
    if (!enterEdges.has(tgt)) enterEdges.set(tgt, [])
    enterEdges.get(tgt)!.push(src)
  }

  // Sort port groups by peer Y for consistent ordering (prevents port crossing)
  for (const [, group] of exitEdges)
    group.sort((a, b) => (posMap.get(a)?.y ?? 0) - (posMap.get(b)?.y ?? 0))
  for (const [, group] of enterEdges)
    group.sort((a, b) => (posMap.get(a)?.y ?? 0) - (posMap.get(b)?.y ?? 0))

  const edges: LayoutEdge[] = []
  const portSpacing = 8

  for (const [tgtKey, srcs] of enterEdges) {
    const tgt = posMap.get(tgtKey)
    if (!tgt) continue
    const enterGroup = srcs
    const tgtMaxSpread = tgt.h - 8
    const enterSpacing =
      enterGroup.length <= 1 ? 0 : Math.min(portSpacing, tgtMaxSpread / (enterGroup.length - 1))

    for (let ei = 0; ei < srcs.length; ei++) {
      const srcKey = srcs[ei]
      const src = posMap.get(srcKey)
      if (!src) continue

      const exitGroup = exitEdges.get(srcKey) ?? []
      const exitIdx = exitGroup.indexOf(tgtKey)
      const srcMaxSpread = src.h - 8
      const exitSpacing =
        exitGroup.length <= 1 ? 0 : Math.min(portSpacing, srcMaxSpread / (exitGroup.length - 1))

      const exitOffset = (exitIdx - (exitGroup.length - 1) / 2) * exitSpacing
      const enterOffset = (ei - (enterGroup.length - 1) / 2) * enterSpacing

      const sx = src.x + src.w
      const sy = src.y + src.h / 2 + exitOffset
      const tx = tgt.x
      const ty = tgt.y + tgt.h / 2 + enterOffset
      const cx = (tx - sx) * 0.5

      const path =
        Math.abs(ty - sy) < 4
          ? `M ${sx} ${sy} L ${tx} ${ty}`
          : `M ${sx} ${sy} C ${sx + cx} ${sy}, ${tx - cx} ${ty}, ${tx} ${ty}`

      const srcEq = props.equationsByKey.get(srcKey)
      edges.push({ path, stroke: edgeStroke(srcEq) })
    }
  }

  return edges
})

// ---- Task lookup ----
const pendingTaskKeys = computed(() => {
  const s = new Set<string>()
  for (const t of props.tasks) {
    if (t.status === 'pending') s.add(t.equation_key)
  }
  return s
})

function hasTask(key: string): boolean {
  return pendingTaskKeys.value.has(key)
}

// ---- Style helpers ----
// Type chip — small filled rounded rect in the title row. Encodes equation
// type via the tool color (was the icon block's job in the old design).
function typeChipClass(n: LayoutNode): string {
  switch (n.equation_type) {
    case 'tool_call':       return 'bg-flow-tool-tint text-flow-tool-strong'
    case 'llm_call':
    case 'llm_batch':
    case 'llm_slot':        return 'bg-flow-llm-tint text-flow-llm-strong'
    case 'code':            return 'bg-flow-code-tint text-flow-code-strong'
    case 'hitl':            return 'bg-flow-hitl-tint text-flow-hitl-strong'
    case 'info':            return 'bg-flow-info-tint text-flow-info-strong'
    case 'flow_input':    return 'bg-flow-input-tint text-flow-input-strong'
    case 'flow_output':   return 'bg-flow-output-tint text-flow-output-strong'
    case 'control':         return 'bg-flow-control-tint text-flow-control-strong'
    case 'create_set':
    case 'create_grid':
    case 'create_document': return 'bg-flow-create-tint text-flow-create-strong'
    case 'web_search':
    case 'fetch_media':     return 'bg-flow-tool-tint text-flow-tool-strong'
    default: return 'bg-overlay-subtle text-content-muted'
  }
}

function isLlm(n: LayoutNode): boolean {
  return n.equation_type === 'llm_call'
    || n.equation_type === 'llm_batch'
    || n.equation_type === 'llm_slot'
}

function typeChipLabel(n: LayoutNode): string {
  switch (n.equation_type) {
    case 'tool_call':     return 'TOOL'
    case 'llm_call':
    case 'llm_batch':
    case 'llm_slot':      return 'LLM'
    case 'code':          return 'CODE'
    case 'hitl':          return 'HUMAN'
    case 'info':          return 'NOTE'
    case 'flow_input':  return 'INPUT'
    case 'flow_output': return 'OUTPUT'
    case 'control': {
      const tail = n.key.split('/').pop() ?? n.key
      if (/foreach/.test(tail)) return 'LOOP'
      if (/zip/.test(tail))     return 'ZIP'
      return 'CTRL'
    }
    case 'create_set':      return 'SET'
    case 'create_grid':     return 'GRID'
    case 'create_document': return 'DOC'
    case 'web_search':      return 'SEARCH'
    case 'fetch_media':     return 'FETCH'
    default: return 'STEP'
  }
}

function infoText(n: LayoutNode): string {
  if (n.equation_type !== 'info') return ''
  const r = n.result
  return typeof r === 'string' ? r : ''
}

function renderInfoMarkdown(src: string): string {
  try {
    return renderSafeMarkdown(src)
  } catch {
    return src
  }
}

// Local fallbacks when the backend didn't supply a display_name. Must match
// the backend's _display_name_for_equation so "Your Turn: Pick one" reads the
// same everywhere.
function hitlKindLabel(kind: string | null | undefined): string {
  switch (kind) {
    case 'select':    return 'Pick one'
    case 'approve':   return 'Approve'
    default:          return 'Human step'
  }
}

function isHitlActionable(n: LayoutNode): boolean {
  return n.equation_type === 'hitl'
    && n.status === 'awaiting_input'
    && hasTask(n.key)
}

function resolveTool(toolId: string | null) {
  if (!toolId) return null
  return cachedTools.value.find((t) => t.full_tool_id === toolId) || null
}

function toolTitle(n: LayoutNode): string {
  const tool = resolveTool(n.tool_id)
  if (tool) return tool.name
  const tid = n.tool_id
  if (tid) {
    const parts = tid.split(':').filter(Boolean)
    if (parts.length >= 2) {
      return parts[1].split('-').map((w) => w ? w[0].toUpperCase() + w.slice(1) : w).join(' ')
    }
  }
  return n.display_name || 'Tool'
}

// What this tool *does* — preferred as the node title so a card reads "Generate
// Image" rather than "Flux.2 Klein 9B" (the model is one of many that could do
// this task; the action is what matters at a glance). Falls back to the tool
// name for utility tools and unknown task types.
function toolTaskTitle(n: LayoutNode): string {
  const tt = n.task_type
  if (tt && tt !== 'utility') {
    const known = TASK_TYPE_LABELS[tt]
    if (known) return known
    return tt.split('-').map((w) => w ? w[0].toUpperCase() + w.slice(1) : w).join(' ')
  }
  return toolTitle(n)
}

function toolProviderName(n: LayoutNode): string | null {
  const tool = resolveTool(n.tool_id)
  if (tool) return tool.provider_name
  const tid = n.tool_id
  if (!tid) return null
  const pid = tid.split(':')[0] || null
  if (!pid) return null
  const p = cachedProviders.value.find((pr) => pr.provider_id === pid)
  return p?.provider_name || pid
}

function providerIdFromToolId(toolId: string | null | undefined): string | null {
  if (!toolId) return null
  return toolId.split(':')[0] || null
}

function isStimmaCloudNode(n: LayoutNode): boolean {
  return providerIdFromToolId(n.tool_id) === STIMMA_CLOUD_PROVIDER_ID
}

function nodeRuntimeModelLabel(n: LayoutNode): string | null {
  if (n.equation_type !== 'tool_call') return null
  const name = toolTitle(n)
  if (!name || nodeTitle(n) === name) return null
  return name
}

function nodeRuntimeProviderLabel(n: LayoutNode): string | null {
  if (n.equation_type !== 'tool_call') return null
  return toolProviderName(n)
}

function nodeRuntimeLabel(n: LayoutNode): string | null {
  const model = nodeRuntimeModelLabel(n)
  const provider = nodeRuntimeProviderLabel(n)
  if (!model && !provider) return null
  return [model, provider].filter(Boolean).join(' · ')
}

// Titles prefer the user's display_name (set in DSL or derived backend-side).
// Fallbacks are deliberate English words in the same voice as the steps view —
// no "Using LLM" / "Logic" / raw type names. Actionable HITL nodes title as
// "Your turn" with the action label as subtitle.
function nodeTitle(n: LayoutNode): string {
  switch (n.equation_type) {
    case 'tool_call':    return toolTaskTitle(n)
    case 'llm_call':
    case 'llm_batch':
    case 'llm_slot':     return n.display_name || 'LLM'
    // Plain code() nodes title from the agent-authored description
    // ("Extract Vibe", "Build Prompt"). Routing helpers (filter/switch/...)
    // keep their type-level display_name ("Filter Items") so the action
    // verb stays in the title; their description still surfaces as subtitle.
    case 'code':
      if (n.routing_kind) return n.display_name || 'Code'
      return (n.description && n.description.trim())
        || n.display_name
        || 'Code'
    case 'hitl':
      if (isHitlActionable(n)) return 'Your turn'
      return n.display_name || hitlKindLabel(n.hitl_kind)
    case 'info':         return n.display_name || 'Note'
    case 'flow_input': return n.display_name || shortKey(n.key)
    // Synthetic output nodes carry the user-declared output_name in
    // display_name (set in buildLayout from src.output_name); fall back to
    // the producer's display_name and finally a literal "Output".
    case 'flow_output': return n.display_name || 'Output'
    case 'control': {
      // Single-node treatment kicks in only when the user expands foreach;
      // otherwise the super-node header owns the label. We can't compute
      // iter count from a single equation, so just render the kind word.
      if (n.display_name) return n.display_name
      const tail = n.key.split('/').pop() ?? n.key
      if (/foreach/.test(tail)) return 'Loop'
      if (/zip/.test(tail))     return 'Combine streams'
      return 'Control'
    }
    default: return n.display_name || shortKey(n.key)
  }
}

// Subtitle disambiguates the title with secondary context:
//   tool_call → provider name
//   code (plain)   → agent-authored subtitle (when set); description has been
//                    promoted into the title row so we don't echo it here
//   code (routing) → user-supplied description (e.g. "approved photos") under
//                    the routing-kind title ("Filter Items")
//   hitl/idle → hitl-kind label so the user sees what kind of decision
//   hitl/actionable → kind label (the title says "Your turn")
//   flow_input → none (the INPUT chip already says it)
//   flow_output → producing step's title
function nodeSubtitle(n: LayoutNode): string | null {
  if (n.equation_type === 'tool_call' && n.tool_id) {
    // Title carries the *action* (e.g. "Generate Image"); subtitle deemphasizes
    // the *implementation* (e.g. "Flux.2 Klein 9B · ComfyUI"). When the title
    // already shows the tool name (utility tools / unknown task type), drop it
    // from the subtitle so we don't echo it.
    const name = toolTitle(n)
    const provider = toolProviderName(n)
    const titleEchoesName = nodeTitle(n) === name
    if (titleEchoesName) return provider
    if (name && provider && name !== provider) return `${name} · ${provider}`
    return name || provider
  }
  if (n.equation_type === 'code') {
    if (n.routing_kind) {
      return n.description && n.description.trim() ? n.description : null
    }
    return n.subtitle && n.subtitle.trim() ? n.subtitle : null
  }
  if (n.equation_type === 'hitl') {
    // Title is "Your turn" only when actionable; idle HITL puts the kind in
    // the title already, so don't echo it as the subtitle.
    return isHitlActionable(n) ? hitlKindLabel(n.hitl_kind) : null
  }
  if (n.equation_type === 'flow_input') {
    return null
  }
  if (n.equation_type === 'flow_output') {
    // Source equation's display_name (we set source_key on synthetic outputs).
    // Falls back to nothing — better than echoing the title.
    return null
  }
  return null
}

function nodeRefKey(n: LayoutNode): string {
  return n.source_key ?? n.key
}

// Hover-echo: when the user hovers a flow-ref chip in the chat context
// tray, the matching node lights up — same affordance the steps-view rows
// already give. Match against the same key the footer FlowRefButton emits,
// so steps and workflow share one source of truth.
const flowRefs = useFlowReferences(injectFlowChatIdRef())
function isNodeEchoed(n: LayoutNode): boolean {
  return flowRefs.hoveredRefKey.value === nodeRefKey(n)
}

function nodeBreadcrumb(n: LayoutNode): string {
  return n.phase_path.length > 0 ? n.phase_path.join(' / ') : ''
}

function outputStatusForSource(status: string): string {
  switch (status) {
    case 'completed':
    case 'failed':
    case 'invalidated':
    case 'skipped':
      return status
    default:
      return 'pending'
  }
}

function statusLabel(n: LayoutNode): string {
  const actionable = hasTask(n.key)
  if (n.equation_type === 'flow_output' && n.status === 'pending') {
    return 'waiting'
  }
  const status = n.status
  switch (status) {
    case 'computing':      return 'running'
    case 'completed':      return 'done'
    case 'failed':         return 'failed'
    case 'pending':        return 'queued'
    case 'awaiting_input': return actionable ? 'your turn' : 'preparing…'
    case 'skipped':        return 'skipped'
    case 'invalidated':    return 'stale'
    default:               return status
  }
}

// Edge color is a loose, static signal of what flows along it. Media flows
// are detected directly from the source node's outputs — the most visually
// meaningful thing happening in the graph gets the loudest color regardless
// of which node type produced it. Everything else falls back to an
// equation-type palette that mirrors the icon-box gradients. Status is
// conveyed by the node borders.
function edgeStroke(srcEq: FlowEquation | undefined): string {
  if (srcEq && (srcEq.result_media_ids?.length ?? 0) > 0) {
    return 'var(--color-flow-edge-media)'
  }
  switch (srcEq?.equation_type) {
    case 'tool_call':    return 'var(--color-flow-edge-tool)'
    case 'llm_call':
    case 'llm_batch':
    case 'llm_slot':     return 'var(--color-flow-edge-llm)'
    case 'code':         return 'var(--color-flow-edge-code)'
    case 'hitl':         return 'var(--color-flow-edge-hitl)'
    case 'info':         return 'var(--color-flow-edge-info)'
    case 'flow_input': return 'var(--color-flow-edge-input)'
    case 'control':      return 'var(--color-flow-edge-control)'
    default:             return 'var(--color-lineage-edge)'
  }
}

function shortKey(key: string): string {
  const tail = key.split('/').pop() ?? key
  return tail.replace(/\$\d+$/, '').replace(/[_$]/g, ' ').trim() || key
}

function titleCaseOutputLabel(label: string): string {
  const words = label
    .trim()
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .split(' ')
    .filter(Boolean)

  if (words.length === 0) return 'Output'

  return words
    .map((word) => {
      const lower = word.toLowerCase()
      if (/^[a-z]$/.test(lower)) return lower
      if (/^\d+$/.test(lower)) return lower
      return lower[0].toUpperCase() + lower.slice(1)
    })
    .join(' ')
}

function outputDisplayName(eq: FlowEquation, fallback: string | null = null): string {
  if (eq.output_name) return titleCaseOutputLabel(eq.output_name)
  return fallback || eq.display_name || 'Output'
}

// ---- Pan/zoom ----
function onPanStart(e: MouseEvent) {
  if (e.button !== 0 && e.button !== 1) return
  if (e.button === 1) e.preventDefault()
  isPanning = true
  panStart = { x: e.clientX, y: e.clientY, px: panX.value, py: panY.value }
  window.addEventListener('mousemove', onPanMove)
  window.addEventListener('mouseup', onPanEnd)
}
function onPanMove(e: MouseEvent) {
  if (!isPanning) return
  panX.value = panStart.px + (e.clientX - panStart.x)
  panY.value = panStart.py + (e.clientY - panStart.y)
}
function onPanEnd() {
  isPanning = false
  window.removeEventListener('mousemove', onPanMove)
  window.removeEventListener('mouseup', onPanEnd)
}
function onWheel(e: WheelEvent) {
  const delta = e.deltaY > 0 ? -0.1 : 0.1
  const newZoom = Math.max(0.15, Math.min(3, zoom.value + delta))
  if (canvasRef.value) {
    const rect = canvasRef.value.getBoundingClientRect()
    const cx = e.clientX - rect.left
    const cy = e.clientY - rect.top
    const scale = newZoom / zoom.value
    panX.value = cx - scale * (cx - panX.value)
    panY.value = cy - scale * (cy - panY.value)
  }
  zoom.value = newZoom
}
function zoomBy(delta: number) {
  zoom.value = Math.max(0.15, Math.min(3, zoom.value + delta))
}
function fitToScreen() {
  if (!canvasRef.value || layout.value.nodes.length === 0) return
  const cw = canvasRef.value.clientWidth
  const ch = canvasRef.value.clientHeight
  if (!cw || !ch) return
  const newZoom = Math.min(cw / canvasW.value, ch / canvasH.value, 1.5) * 0.9
  zoom.value = newZoom
  panX.value = (cw - canvasW.value * newZoom) / 2
  panY.value = (ch - canvasH.value * newZoom) / 2
}

onBeforeUnmount(() => {
  stopActiveInspectPanelResize?.()
  window.removeEventListener('mousemove', onPanMove)
  window.removeEventListener('mouseup', onPanEnd)
})
</script>

<style scoped>
.info-prose :deep(p) { margin: 0; }
.info-prose :deep(p + p) { margin-top: 0.25em; }
.info-prose :deep(strong) { font-weight: 600; color: rgb(var(--color-content) / 1); }
.info-prose :deep(em) { font-style: italic; }
.info-prose :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.9em;
  padding: 0 0.25em;
  border-radius: 2px;
  background: var(--color-overlay-light);
}
.info-prose :deep(a) { color: rgb(96, 165, 250); text-decoration: underline; }
.info-prose :deep(ul), .info-prose :deep(ol) { margin: 0; padding-left: 1em; }
.info-prose :deep(h1), .info-prose :deep(h2), .info-prose :deep(h3) {
  font-weight: 600;
  font-size: 1em;
  margin: 0;
}
</style>
