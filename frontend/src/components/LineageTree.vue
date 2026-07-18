<template>
  <div class="w-full h-full flex flex-col overflow-hidden select-none bg-slideshow-matt">
    <!-- Tree canvas -->
    <div
      v-if="!loading && !error && nodes.length > 0"
      ref="canvasRef"
      class="flex-1 overflow-hidden cursor-grab active:cursor-grabbing"
      @mousedown="onPanStart"
      @wheel.prevent="onWheel"
      @dblclick="onCanvasDoubleClick"
      @click="selectedNodeId = null"
    >
      <div
        class="origin-top-left"
        :style="{
          transform: `translate(${panX}px, ${panY}px) scale(${zoom})`,
          width: `${canvasWidth}px`,
          height: `${normalizedCanvasHeight}px`,
          position: 'relative'
        }"
      >
        <!-- SVG edges layer -->
        <svg
          class="absolute inset-0 pointer-events-none"
          :width="canvasWidth"
          :height="normalizedCanvasHeight"
          :viewBox="`0 0 ${canvasWidth} ${normalizedCanvasHeight}`"
        >
          <path
            v-for="(edge, idx) in layoutEdges"
            :key="idx"
            :d="edge.path"
            fill="none"
            :stroke="edge.inspired ? 'var(--color-lineage-edge-inspired)' : 'var(--color-lineage-edge)'"
            stroke-width="1.5"
            :stroke-dasharray="edge.inspired ? '6 4' : 'none'"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>

        <!-- Nodes layer -->
        <div
          v-for="node in normalizedNodes"
          :key="node.id"
          class="absolute cursor-pointer group z-10"
          :style="{
            left: `${node.x}px`,
            top: `${node.y}px`,
            width: `${nodeWidth}px`
          }"
          @mousedown.stop
          @click.stop="!node.placeholder && (selectedNodeId = node.id)"
        >
          <div class="flex flex-col items-center transition-all">
            <!-- Placeholder node: trashed Asset or contextual intermediate on the provenance path -->
            <template v-if="node.placeholder">
              <div
                class="relative rounded-lg border-2 border-dashed border-edge-subtle bg-overlay-light flex items-center justify-center"
                :style="{ width: `${thumbSize}px`, height: `${thumbSize}px` }"
              >
                <svg v-if="node.kind === 'trashed' || node.kind === 'expired'" class="w-5 h-5 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
                </svg>
                <svg v-else class="w-5 h-5 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09Z" />
                </svg>
              </div>
              <div class="flex flex-col items-center gap-0 mt-1" :style="{ width: `${labelWidth}px` }">
                <span class="text-[10px] text-content-muted leading-tight text-center">
                  {{ placeholderLabel(node) }}
                </span>
              </div>
            </template>

            <template v-else>
              <!-- Thumbnail -->
              <div
                class="relative rounded-lg overflow-hidden border-2 transition-all"
                :class="node.id === focusedNodeId
                  ? 'border-blue-500/70'
                  : node.id === selectedNodeId
                    ? 'border-edge-strong'
                    : 'border-transparent group-hover:border-edge-subtle'"
                :style="{ width: `${thumbSize}px`, height: `${thumbSize}px` }"
              >
                <MediaImage
                  :media-id="node.id"
                  :file-hash="node.media.file_hash"
                  :thumbnail-size="128"
                  container-class="w-full h-full"
                  img-class="w-full h-full object-cover"
                />
                <div v-if="node.media.markers?.length" class="absolute bottom-1 right-1 flex gap-0.5">
                  <div
                    v-for="marker in node.media.markers"
                    :key="marker.id"
                    class="w-4 h-4 bg-black/60 backdrop-blur-md rounded flex items-center justify-center"
                    :title="marker.name"
                  >
                    <span class="w-3 h-3 flex items-center justify-center icon-container" :style="{ color: marker.color }" v-html="sanitizeSvg(marker.icon_svg)" />
                  </div>
                </div>
              </div>

              <!-- Info below thumbnail -->
              <div class="flex flex-col items-center gap-0 mt-1" :style="{ width: `${labelWidth}px` }">
                <span
                  v-if="nodeSubtitle(node)"
                  class="text-[10px] truncate leading-tight max-w-full text-center"
                  :class="node.id === focusedNodeId ? 'text-blue-500 font-semibold' : 'text-content-tertiary font-medium'"
                >
                  {{ nodeSubtitle(node) }}
                </span>
                <span
                  v-if="node.media.created_date"
                  class="text-[9px] text-content-muted leading-tight"
                >
                  {{ formatDateShort(node.media.created_date) }}
                </span>
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- Loading state -->
    <div v-else-if="loading" class="flex-1 flex items-center justify-center">
      <span class="text-content-tertiary text-sm animate-pulse">Loading lineage...</span>
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="flex-1 flex items-center justify-center">
      <span class="text-red-400 text-sm">{{ error }}</span>
    </div>

    <!-- Truncation notice -->
    <div
      v-if="!loading && !error && truncated"
      class="absolute top-4 left-1/2 -translate-x-1/2 z-20 px-3 py-1.5 rounded-full bg-overlay-strong backdrop-blur-md border border-edge-subtle text-content-tertiary text-xs"
    >
      Lineage is very large — showing the closest {{ nodes.length }} items
    </div>

    <!-- Detail modal -->
    <Modal
      :show="!!selectedNode"
      size="custom"
      custom-class="w-[1100px] max-w-[calc(100vw-3rem)] h-[75vh]"
      @close="selectedNodeId = null"
    >
      <div class="relative w-full h-full overflow-hidden flex">
        <!-- Close -->
        <button
          class="absolute top-3 right-3 z-10 w-8 h-8 flex items-center justify-center rounded-full bg-overlay-strong text-content-tertiary hover:text-content hover:bg-overlay-medium transition-colors"
          @click="selectedNodeId = null"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>

        <ImageDetailsCard
          :media="selectedNodeMedia"
          :source-inputs="selectedSourceInputs"
          :parent-nodes="selectedParentNodes"
          :child-nodes="selectedChildNodes"
          @navigate="selectedNodeId = $event"
          @open-flow="openFlow"
        />
      </div>
    </Modal>

    <!-- Minimap -->
    <div
      v-if="!loading && normalizedNodes.length > 1"
      ref="minimapRef"
      class="absolute bottom-4 left-4 z-20 backdrop-blur-md rounded-lg border border-edge-subtle overflow-hidden cursor-grab active:cursor-grabbing p-2"
      style="background: var(--color-lineage-minimap-bg)"
      :style="{ width: `${minimapWidth + 16}px`, height: `${minimapHeight + 16}px` }"
      @mousedown.stop="onMinimapMouseDown"
      @click.stop="onMinimapClick"
    >
      <svg :width="minimapWidth" :height="minimapHeight" :viewBox="`0 0 ${minimapWidth} ${minimapHeight}`">
        <!-- Edge paths (same routing as main view, scaled down) -->
        <path
          v-for="(edge, idx) in minimapEdges"
          :key="'mme-' + idx"
          :d="edge.path"
          fill="none"
          :stroke="edge.inspired ? 'var(--color-lineage-minimap-edge-inspired)' : 'var(--color-lineage-minimap-edge)'"
          stroke-width="1"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
        <!-- Node dots (positioned to match thumb area where edges connect) -->
        <rect
          v-for="node in normalizedNodes"
          :key="'mm-' + node.id"
          :x="((node.x + thumbInset) / canvasWidth) * minimapWidth"
          :y="(node.y / normalizedCanvasHeight) * minimapHeight"
          :width="Math.max((thumbSize / canvasWidth) * minimapWidth, 5)"
          :height="Math.max((thumbSize / normalizedCanvasHeight) * minimapHeight, 5)"
          :rx="Math.max((thumbSize / normalizedCanvasHeight) * minimapHeight * 0.25, 1.5)"
          :fill="node.id === focusedNodeId ? 'rgba(59,130,246,1)' : 'var(--color-lineage-minimap-node)'"
        />
        <!-- Viewport rectangle -->
        <rect
          :x="minimapViewport.x"
          :y="minimapViewport.y"
          :width="minimapViewport.w"
          :height="minimapViewport.h"
          :fill="'var(--color-lineage-minimap-viewport-fill)'"
          :stroke="'var(--color-lineage-minimap-viewport-stroke)'"
          stroke-width="1.5"
          rx="3"
        />
      </svg>
    </div>

    <!-- Floating zoom controls -->
    <div class="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 flex items-center gap-1 backdrop-blur-md rounded-full px-2 py-1" style="background: var(--color-lineage-controls-bg)">
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
      <div class="w-px h-4 bg-edge-subtle mx-0.5"></div>
      <button
        class="w-7 h-7 flex items-center justify-center rounded-full text-content-muted hover:text-content hover:bg-overlay-light transition-colors"
        title="Fit to screen"
        @click="fitToScreen"
      >
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import * as dagre from '@dagrejs/dagre'
import { MediaImage } from './media'
import Modal from './ui/Modal.vue'
import ImageDetailsCard from './media/ImageDetailsCard.vue'
import { useMarkers } from '../composables/useMarkers'
import { useProvidersApi } from '../composables/useProvidersApi'
import { sanitizeSvg } from '../utils/sanitizeHtml'
import { formatTaskTypeLabel } from '../utils/taskTypeIcons'

const router = useRouter()
const props = defineProps({
  mediaId: {
    type: Number,
    required: true
  }
})

const emit = defineEmits(['close', 'focus-changed'])

const { init: initMarkers, loadMarkersForMedia } = useMarkers()
const { cachedTools, fetchProvidersAndTools } = useProvidersApi()

// Resolve a tool_id (full "provider:tool" or bare) to its human display name.
function toolDisplayName(toolId) {
  if (!toolId) return ''
  const tool = cachedTools.value.find(t => t.full_tool_id === toolId || t.tool_id === toolId)
  if (tool?.name) return tool.name
  return formatToolId(toolId)
}

// Layout constants
const thumbSize = 56
const nodeWidth = 80
const nodeHeight = 86
const thumbInset = (nodeWidth - thumbSize) / 2
const layerSpacing = 180
const nodeSpacing = 20
const padding = 60
// Labels can be wider than the thumbnail; they stay centered over the node and
// only truncate when the tool name is genuinely long.
const labelWidth = 132

// State
const loading = ref(true)
const error = ref(null)
const nodes = ref([])
const edges = ref([])
const truncated = ref(false)
const selectedNodeId = ref(null)
const focusedNodeId = ref(props.mediaId)
// Left/right navigation history stacks (browser back/forward model)
const navBackStack = []
const navForwardStack = []
watch(selectedNodeId, (id) => {
  if (id) focusedNodeId.value = id
  // Modal.vue owns focus trap + Esc-to-close; we only need the d-pad
  // arrow-key navigation wired up while the detail modal is open.
  if (id) {
    window.addEventListener('keydown', onModalArrowKeydown)
  } else {
    window.removeEventListener('keydown', onModalArrowKeydown)
  }
})
watch(focusedNodeId, (id) => {
  if (id != null) emit('focus-changed', id)
})
let fetchedForMediaId = null

// Refs
const canvasRef = ref(null)
const panX = ref(0)
const panY = ref(0)
const zoom = ref(1)
let isPanning = false
let panStartX = 0
let panStartY = 0
let panStartPanX = 0
let panStartPanY = 0

// Selected node
const selectedNode = computed(() => {
  if (!selectedNodeId.value) return null
  return normalizedNodes.value.find(n => n.id === selectedNodeId.value) || null
})

// Media object for the detail card, guaranteed to carry its media id
const selectedNodeMedia = computed(() => {
  if (!selectedNode.value) return null
  return { ...selectedNode.value.media, id: selectedNode.value.id }
})

function openFlow(flowId) {
  router.push({ name: 'flow', params: { id: String(flowId) } })
}

function parseSourceInputs(media) {
  const raw = media?.generation_metadata
  if (!raw) return []
  try {
    const meta = typeof raw === 'string' ? JSON.parse(raw) : raw
    return Array.isArray(meta?.source_inputs) ? meta.source_inputs : []
  } catch { return [] }
}

// Source inputs from generation metadata, with flag for whether they're in the tree
const selectedSourceInputs = computed(() => {
  const inputs = parseSourceInputs(selectedNode.value?.media)
  if (!inputs.length) return []
  const nodeIds = new Set(nodes.value.map(n => n.id))
  return inputs
    .filter(s => s.media_id)
    .map(s => ({ ...s, inTree: nodeIds.has(s.media_id) }))
})

// Parent nodes from lineage edges (not already shown via source_inputs)
const selectedParentNodes = computed(() => {
  if (!selectedNodeId.value) return []
  const sourceInputIds = new Set(selectedSourceInputs.value.map(s => s.media_id))
  const parentEdges = edges.value.filter(e => e.target_id === selectedNodeId.value)
  const nodeMap = new Map(normalizedNodes.value.map(n => [n.id, n]))
  return parentEdges
    .filter(e => !sourceInputIds.has(e.source_id) && nodeMap.has(e.source_id) && !nodeMap.get(e.source_id).placeholder)
    .map(e => ({ ...nodeMap.get(e.source_id), inspired: e.relationship_type === 'inspired' }))
})

// Child nodes from lineage edges
const selectedChildNodes = computed(() => {
  if (!selectedNodeId.value) return []
  const childEdges = edges.value.filter(e => e.source_id === selectedNodeId.value)
  const nodeMap = new Map(normalizedNodes.value.map(n => [n.id, n]))
  return childEdges
    .filter(e => nodeMap.has(e.target_id) && !nodeMap.get(e.target_id).placeholder)
    .map(e => ({ ...nodeMap.get(e.target_id), inspired: e.relationship_type === 'inspired' }))
})

// Layout computation — dagre handles layering, crossing minimization, and coordinate assignment
const dagreLayout = computed(() => {
  if (nodes.value.length === 0) return { nodes: [], positions: new Map(), width: 800, height: 600 }

  const GraphClass = dagre.Graph || dagre.graphlib?.Graph || dagre.default?.Graph
  const layoutFn = dagre.layout || dagre.default?.layout
  const g = new GraphClass()
  g.setGraph({
    rankdir: 'LR',
    nodesep: nodeSpacing,
    ranksep: layerSpacing - nodeWidth,
    marginx: padding,
    marginy: padding
  })
  g.setDefaultEdgeLabel(() => ({}))

  const nodeTaskTypes = new Map()
  for (const edge of edges.value) {
    nodeTaskTypes.set(edge.target_id, edge.task_type)
  }

  for (const node of nodes.value) {
    g.setNode(String(node.id), { width: nodeWidth, height: nodeHeight })
  }
  for (const edge of edges.value) {
    g.setEdge(String(edge.source_id), String(edge.target_id))
  }

  layoutFn(g)

  // Extract dagre positions (center → top-left)
  const positions = new Map()
  for (const node of nodes.value) {
    const pos = g.node(String(node.id))
    positions.set(node.id, { x: pos.x - nodeWidth / 2, y: pos.y - nodeHeight / 2 })
  }

  // Post-layout: nudge nodes toward the average Y of their parents to reduce
  // unnecessary curvature on edges that could be nearly straight.
  // Process nodes left-to-right (by x) so parents are settled first.
  const nodesByX = [...positions.entries()].sort((a, b) => a[1].x - b[1].x)
  const parentMap = new Map() // nodeId → [parentIds]
  for (const edge of edges.value) {
    if (!parentMap.has(edge.target_id)) parentMap.set(edge.target_id, [])
    parentMap.get(edge.target_id).push(edge.source_id)
  }

  // Group nodes by rank (same x position = same rank)
  const ranks = new Map() // x → [nodeId]
  for (const [id, pos] of nodesByX) {
    const rx = Math.round(pos.x)
    if (!ranks.has(rx)) ranks.set(rx, [])
    ranks.get(rx).push(id)
  }

  for (const [, rankNodeIds] of ranks) {
    // Sort by current Y
    rankNodeIds.sort((a, b) => positions.get(a).y - positions.get(b).y)

    // Compute ideal Y for each node based on parent average
    const ideals = rankNodeIds.map(id => {
      const parents = parentMap.get(id)
      if (!parents || parents.length === 0) return null
      const avgY = parents.reduce((sum, pid) => sum + (positions.get(pid)?.y ?? 0), 0) / parents.length
      return avgY
    })

    // Apply nudge: move each node toward its ideal Y, but don't let nodes overlap
    for (let i = 0; i < rankNodeIds.length; i++) {
      if (ideals[i] === null) continue
      const id = rankNodeIds[i]
      const pos = positions.get(id)
      const ideal = ideals[i]
      const diff = ideal - pos.y

      // Only nudge if within a reasonable range (don't rearrange order)
      if (Math.abs(diff) > nodeHeight * 2) continue

      let newY = ideal
      // Enforce minimum spacing with neighbors
      if (i > 0) {
        const prevY = positions.get(rankNodeIds[i - 1]).y
        newY = Math.max(newY, prevY + nodeHeight + nodeSpacing)
      }
      if (i < rankNodeIds.length - 1) {
        const nextY = positions.get(rankNodeIds[i + 1]).y
        newY = Math.min(newY, nextY - nodeHeight - nodeSpacing)
      }
      pos.y = newY
    }
  }

  const result = []
  for (const node of nodes.value) {
    const pos = positions.get(node.id)
    result.push({
      id: node.id,
      media: node.media,
      depth: node.depth,
      kind: node.kind || 'asset',
      placeholder: !!node.placeholder,
      taskType: nodeTaskTypes.get(node.id) || null,
      x: pos.x,
      y: pos.y
    })
  }

  const graphInfo = g.graph()
  return {
    nodes: result,
    positions,
    width: (graphInfo.width || 800) + padding,
    height: (graphInfo.height || 600) + padding
  }
})

const normalizedNodes = computed(() => dagreLayout.value.nodes)

const normalizedPositions = computed(() => dagreLayout.value.positions)

const canvasWidth = computed(() => dagreLayout.value.width)

const normalizedCanvasHeight = computed(() => dagreLayout.value.height)

const layoutEdges = computed(() => {
  const thumbCenterY = thumbSize / 2
  const portSpacing = 8 // px between connection points when multiple edges share a side

  // Count edges per side of each node and sort by target/source Y for consistent ordering
  const exitEdges = new Map()  // source_id → [edge indices]
  const enterEdges = new Map() // target_id → [edge indices]
  edges.value.forEach((edge, i) => {
    if (!exitEdges.has(edge.source_id)) exitEdges.set(edge.source_id, [])
    exitEdges.get(edge.source_id).push(i)
    if (!enterEdges.has(edge.target_id)) enterEdges.set(edge.target_id, [])
    enterEdges.get(edge.target_id).push(i)
  })

  // Sort port groups by the Y position of the other end so ports don't cross
  const positions = normalizedPositions.value
  for (const [srcId, indices] of exitEdges) {
    indices.sort((a, b) => {
      const ay = positions.get(edges.value[a].target_id)?.y ?? 0
      const by = positions.get(edges.value[b].target_id)?.y ?? 0
      return ay - by
    })
  }
  for (const [tgtId, indices] of enterEdges) {
    indices.sort((a, b) => {
      const ay = positions.get(edges.value[a].source_id)?.y ?? 0
      const by = positions.get(edges.value[b].source_id)?.y ?? 0
      return ay - by
    })
  }

  return edges.value.map((edge, edgeIdx) => {
    const source = positions.get(edge.source_id)
    const target = positions.get(edge.target_id)
    if (!source || !target) return null

    // Compute port offsets — capped to fit within thumb height
    const maxSpread = thumbSize - 8 // leave 4px margin top and bottom
    const exitGroup = exitEdges.get(edge.source_id) || [edgeIdx]
    const enterGroup = enterEdges.get(edge.target_id) || [edgeIdx]
    const exitIdx = exitGroup.indexOf(edgeIdx)
    const enterIdx = enterGroup.indexOf(edgeIdx)
    const exitSpacing = exitGroup.length <= 1 ? 0 : Math.min(portSpacing, maxSpread / (exitGroup.length - 1))
    const enterSpacing = enterGroup.length <= 1 ? 0 : Math.min(portSpacing, maxSpread / (enterGroup.length - 1))
    const exitOffset = (exitIdx - (exitGroup.length - 1) / 2) * exitSpacing
    const enterOffset = (enterIdx - (enterGroup.length - 1) / 2) * enterSpacing

    const sx = source.x + thumbInset + thumbSize
    const sy = source.y + thumbCenterY + exitOffset
    const tx = target.x + thumbInset
    const ty = target.y + thumbCenterY + enterOffset
    const dx = tx - sx
    const dy = ty - sy
    const absDy = Math.abs(dy)

    // If nearly horizontal, draw a straight line
    let path
    if (absDy < 4) {
      const midY = (sy + ty) / 2
      path = `M ${sx} ${midY} L ${tx} ${midY}`
    } else {
      // Cubic bezier — leaves source horizontally, arrives at target horizontally
      const cx = dx * 0.5
      path = `M ${sx} ${sy} C ${sx + cx} ${sy}, ${tx - cx} ${ty}, ${tx} ${ty}`
    }

    return {
      path,
      inspired: edge.relationship_type === 'inspired'
    }
  }).filter(Boolean)
})


// Methods
function placeholderLabel(node) {
  const labels = {
    trashed: 'In Trash',
    expired: 'Expired',
    revision: 'Older version',
    unavailable: 'Unavailable',
    intermediate: 'Intermediate'
  }
  return labels[node.kind] || 'Hidden'
}

function nodeTitle(node) {
  if (node.id === props.mediaId && !node.taskType) return 'Current'
  if (node.taskType) return formatNodeLabel(node.taskType)
  if (node.media.tool_id) return toolDisplayName(node.media.tool_id)
  return 'Imported'
}

function nodeModel(node) {
  try {
    const meta = node.media?.generation_metadata
    if (!meta) return null
    const parsed = typeof meta === 'string' ? JSON.parse(meta) : meta
    return parsed?.model || null
  } catch { return null }
}

function nodeSubtitle(node) {
  const model = nodeModel(node)
  if (model) return model
  // Tool display name (skip generic "Edited"/"Generated" labels)
  const meta = node.media?.generation_metadata
  if (meta) {
    try {
      const parsed = typeof meta === 'string' ? JSON.parse(meta) : meta
      if (parsed?.tool_id) {
        return toolDisplayName(parsed.tool_id)
      }
    } catch {}
  }
  if (node.media.tool_id) {
    return toolDisplayName(node.media.tool_id)
  }
  if (!node.taskType) return 'Imported'
  return null
}

async function fetchTree() {
  if (fetchedForMediaId === props.mediaId && nodes.value.length > 0) return
  loading.value = true
  error.value = null
  try {
    await initMarkers()
    // Populate the tools cache so we can show tool display names (not slugs).
    fetchProvidersAndTools().catch(() => {})
    const { data } = await axios.get(`/api/media/${props.mediaId}/lineage/tree`)
    nodes.value = data.nodes
    edges.value = data.edges
    truncated.value = !!data.truncated
    fetchedForMediaId = props.mediaId
    // Load markers for all full nodes in the tree (placeholders carry no metadata)
    await loadMarkersForMedia(data.nodes.filter(n => !n.placeholder).map(n => n.id))
    focusedNodeId.value = props.mediaId
    selectedNodeId.value = null
    navBackStack.length = 0
    navForwardStack.length = 0
    await nextTick()
    // Wait for layout to settle before centering
    requestAnimationFrame(() => requestAnimationFrame(() => centerOnFocus()))
  } catch (err) {
    error.value = err.response?.status === 404 ? 'Media item not found' : 'Failed to load lineage tree'
  } finally {
    loading.value = false
  }
}

function formatEdgeLabel(edge) {
  if (!edge) return ''
  if (edge.relationship_type === 'inspired') return 'Remixed'
  const labels = { 'image-to-image': 'Edited', 'video-to-video': 'Video Edited', 'text-to-image': 'Generated', 'upscale': 'Upscaled', 'upscale-image': 'Upscaled', 'upscale-video': 'Upscaled', 'video-extend': 'Extended', 'video-stitch': 'Stitched', 'grid-creation': 'Grid', 'set-creation': 'Set', 'image-editor': 'Edited' }
  return labels[edge.task_type] || formatTaskTypeLabel(edge.task_type?.replace(/^.*:/, '') || '')
}

function formatNodeLabel(taskType) {
  if (!taskType) return ''
  const labels = { 'image-to-image': 'Edited', 'video-to-video': 'Video Edited', 'text-to-image': 'Generated', 'upscale': 'Upscaled', 'upscale-image': 'Upscaled', 'upscale-video': 'Upscaled', 'video-extend': 'Extended', 'video-stitch': 'Stitched', 'grid-creation': 'Grid', 'set-creation': 'Set', 'image-editor': 'Edited' }
  return labels[taskType] || formatTaskTypeLabel(taskType.replace(/^.*:/, ''))
}

function formatToolId(toolId) {
  if (!toolId) return ''
  const parts = toolId.split(':')
  if (parts.length >= 3) return parts[parts.length - 2]
  if (parts.length === 2) return parts[1]
  return toolId
}

function formatDateShort(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const now = new Date()
  const diffMs = now - d
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))
  if (diffDays < 0) return 'Just now'
  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays}d ago`
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

// Minimap
const minimapWidth = 180
const minimapHeight = computed(() => {
  if (canvasWidth.value === 0) return 100
  return Math.max(60, Math.round((normalizedCanvasHeight.value / canvasWidth.value) * minimapWidth))
})

const minimapScaleX = computed(() => minimapWidth / canvasWidth.value)
const minimapScaleY = computed(() => minimapHeight.value / normalizedCanvasHeight.value)

// Minimap edges: same paths as main view, scaled down
const minimapEdges = computed(() => {
  const sx = minimapScaleX.value
  const sy = minimapScaleY.value
  return layoutEdges.value.map(edge => ({
    // Transform the SVG path: scale all numbers appropriately
    path: scalePathToMinimap(edge.path, sx, sy),
    inspired: edge.inspired
  }))
})

const minimapViewport = computed(() => {
  if (!canvasRef.value) return { x: 0, y: 0, w: minimapWidth, h: minimapHeight.value }
  const cw = canvasRef.value.clientWidth || 1
  const ch = canvasRef.value.clientHeight || 1
  const sx = minimapScaleX.value
  const sy = minimapScaleY.value
  const rawX = (-panX.value / zoom.value) * sx
  const rawY = (-panY.value / zoom.value) * sy
  const rawW = (cw / zoom.value) * sx
  const rawH = (ch / zoom.value) * sy
  // Clamp to minimap bounds
  const x = Math.max(0, rawX)
  const y = Math.max(0, rawY)
  const w = Math.min(minimapWidth - x, rawW - (x - rawX))
  const h = Math.min(minimapHeight.value - y, rawH - (y - rawY))
  return { x, y, w: Math.max(0, w), h: Math.max(0, h) }
})

function scalePathToMinimap(pathStr, sx, sy) {
  // Parse SVG path commands and scale coordinates
  const commands = []
  const re = /([MLQC])\s*([\d\s.,-]+)/gi
  let match
  while ((match = re.exec(pathStr)) !== null) {
    const cmd = match[1]
    const nums = match[2].trim().split(/[\s,]+/).map(Number)
    const scaled = []
    for (let i = 0; i < nums.length; i += 2) {
      scaled.push(nums[i] * sx)
      if (i + 1 < nums.length) scaled.push(nums[i + 1] * sy)
    }
    commands.push(`${cmd} ${scaled.join(' ')}`)
  }
  return commands.join(' ')
}

const minimapRef = ref(null)
let isMinimapDragging = false

function minimapPointerToCanvas(e) {
  if (!minimapRef.value || !canvasRef.value) return
  const rect = minimapRef.value.getBoundingClientRect()
  const mx = e.clientX - rect.left - 8  // padding
  const my = e.clientY - rect.top - 8
  const canvasX = (mx / minimapWidth) * canvasWidth.value
  const canvasY = (my / minimapHeight.value) * normalizedCanvasHeight.value
  const cw = canvasRef.value.clientWidth
  const ch = canvasRef.value.clientHeight
  panX.value = cw / 2 - canvasX * zoom.value
  panY.value = ch / 2 - canvasY * zoom.value
}

function onMinimapMouseDown(e) {
  if (e.button !== 0) return
  isMinimapDragging = true
  minimapPointerToCanvas(e)
  window.addEventListener('mousemove', onMinimapMouseMove)
  window.addEventListener('mouseup', onMinimapMouseUp)
}

function onMinimapMouseMove(e) {
  if (!isMinimapDragging) return
  minimapPointerToCanvas(e)
}

function onMinimapMouseUp() {
  isMinimapDragging = false
  window.removeEventListener('mousemove', onMinimapMouseMove)
  window.removeEventListener('mouseup', onMinimapMouseUp)
}

function zoomBy(delta) {
  zoom.value = Math.max(0.15, Math.min(3, zoom.value + delta))
}

function centerOnFocus() {
  if (!canvasRef.value || normalizedNodes.value.length === 0) return
  const focusNode = normalizedNodes.value.find(n => n.id === props.mediaId)
  if (!focusNode) return fitToScreen()

  const cw = canvasRef.value.clientWidth
  const ch = canvasRef.value.clientHeight
  const comfortZoom = 1.5

  // Check if the whole graph fits at a comfortable zoom level
  const fitZoom = Math.min(cw / canvasWidth.value, ch / normalizedCanvasHeight.value) * 0.9
  if (fitZoom >= comfortZoom) {
    // Small graph — center the whole thing at comfortable zoom
    zoom.value = comfortZoom
    panX.value = (cw - canvasWidth.value * comfortZoom) / 2
    panY.value = (ch - normalizedCanvasHeight.value * comfortZoom) / 2
  } else {
    // Large graph — use comfortable zoom and center on focus node
    zoom.value = comfortZoom
    panX.value = cw / 2 - (focusNode.x + nodeWidth / 2) * comfortZoom
    panY.value = ch / 2 - (focusNode.y + nodeHeight / 2) * comfortZoom
  }
}

function fitToScreen() {
  if (!canvasRef.value || normalizedNodes.value.length === 0) return
  const cw = canvasRef.value.clientWidth
  const ch = canvasRef.value.clientHeight
  const newZoom = Math.min(cw / canvasWidth.value, ch / normalizedCanvasHeight.value, 1.5) * 0.9
  zoom.value = newZoom
  panX.value = (cw - canvasWidth.value * newZoom) / 2
  panY.value = (ch - normalizedCanvasHeight.value * newZoom) / 2
}

function onPanStart(e) {
  if (e.button !== 0) return
  isPanning = true
  panStartX = e.clientX
  panStartY = e.clientY
  panStartPanX = panX.value
  panStartPanY = panY.value
  window.addEventListener('mousemove', onPanMove)
  window.addEventListener('mouseup', onPanEnd)
}
function onPanMove(e) {
  if (!isPanning) return
  panX.value = panStartPanX + (e.clientX - panStartX)
  panY.value = panStartPanY + (e.clientY - panStartY)
}
function onPanEnd() {
  isPanning = false
  window.removeEventListener('mousemove', onPanMove)
  window.removeEventListener('mouseup', onPanEnd)
}
function onWheel(e) {
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
function onCanvasDoubleClick() { fitToScreen() }

// Spatial navigation: find nearest node in a directional cone
function navigateSpatial(direction, currentId, current) {
  const cx = current.x + nodeWidth / 2
  const cy = current.y + nodeHeight / 2
  let best = null
  let bestScore = Infinity

  for (const node of normalizedNodes.value) {
    if (node.id === currentId || node.placeholder) continue
    const nx = node.x + nodeWidth / 2
    const ny = node.y + nodeHeight / 2
    const dx = nx - cx
    const dy = ny - cy

    let inDir = false, primary = 0, cross = 0
    switch (direction) {
      case 'right': inDir = dx > 10 && Math.abs(dy) < dx * 2; primary = dx; cross = Math.abs(dy); break
      case 'left':  inDir = dx < -10 && Math.abs(dy) < -dx * 2; primary = -dx; cross = Math.abs(dy); break
      case 'down':  inDir = dy > 10 && Math.abs(dx) < dy * 2; primary = dy; cross = Math.abs(dx); break
      case 'up':    inDir = dy < -10 && Math.abs(dx) < -dy * 2; primary = -dy; cross = Math.abs(dx); break
    }
    if (!inDir) continue
    const score = Math.sqrt(primary * primary + cross * cross)
    if (score < bestScore) { bestScore = score; best = node }
  }
  return best
}

// Edge-based navigation: follow parent/child edges, picking the spatially nearest
function navigateEdge(direction, currentId, current) {
  const isLeft = direction === 'left'
  // Left = go to parents (current is target), Right = go to children (current is source)
  const connectedIds = edges.value
    .filter(e => isLeft ? e.target_id === currentId : e.source_id === currentId)
    .map(e => isLeft ? e.source_id : e.target_id)

  if (connectedIds.length === 0) return null
  if (connectedIds.length === 1) {
    const node = normalizedNodes.value.find(n => n.id === connectedIds[0])
    return node && !node.placeholder ? node : null
  }

  // Multiple edges: pick the one closest spatially (by Y distance)
  const cy = current.y + nodeHeight / 2
  let best = null
  let bestDist = Infinity
  for (const id of connectedIds) {
    const node = normalizedNodes.value.find(n => n.id === id)
    if (!node || node.placeholder) continue
    const dist = Math.abs((node.y + nodeHeight / 2) - cy)
    if (dist < bestDist) { bestDist = dist; best = node }
  }
  return best
}

// D-pad navigation: left/right use history stacks (browser back/forward) then edges, up/down are spatial
function navigateDpad(direction) {
  const currentId = focusedNodeId.value || selectedNodeId.value
  if (!currentId) return
  const current = normalizedNodes.value.find(n => n.id === currentId)
  if (!current) return

  let best = null

  if (direction === 'left' || direction === 'right') {
    const goingBack = direction === 'left'
    const replayStack = goingBack ? navBackStack : navForwardStack
    const pushStack = goingBack ? navForwardStack : navBackStack

    if (replayStack.length > 0) {
      // Replay history: pop from the direction's stack, push current onto opposite
      const replayId = replayStack.pop()
      best = normalizedNodes.value.find(n => n.id === replayId)
      if (best) pushStack.push(currentId)
    }
    if (!best) {
      // New navigation: edge-based then spatial fallback
      best = navigateEdge(direction, currentId, current) || navigateSpatial(direction, currentId, current)
      if (best) {
        pushStack.push(currentId)
        replayStack.length = 0 // clear forward history on new navigation
      }
    }
  } else {
    // Up/down: pure spatial, resets left/right history
    best = navigateSpatial(direction, currentId, current)
    if (best) {
      navBackStack.length = 0
      navForwardStack.length = 0
    }
  }

  if (best) {
    focusedNodeId.value = best.id
    if (selectedNodeId.value) selectedNodeId.value = best.id
  }
}

function onModalArrowKeydown(e) {
  const dirMap = { ArrowRight: 'right', ArrowLeft: 'left', ArrowDown: 'down', ArrowUp: 'up' }
  const dir = dirMap[e.key]
  if (dir) {
    e.preventDefault()
    navigateDpad(dir)
  }
  // Escape is handled by Modal.vue's own closeOnEsc.
}

defineExpose({
  hasDetailOpen: () => selectedNodeId.value != null,
  closeDetail: () => { selectedNodeId.value = null },
  openDetail: () => {
    if (!focusedNodeId.value) return
    const node = normalizedNodes.value.find(n => n.id === focusedNodeId.value)
    if (node && !node.placeholder) selectedNodeId.value = focusedNodeId.value
  },
  navigateDpad,
  nodeCount: computed(() => nodes.value.length),
  edgeCount: computed(() => edges.value.length),
  loading
})

onMounted(() => fetchTree())
onBeforeUnmount(() => {
  window.removeEventListener('mousemove', onPanMove)
  window.removeEventListener('mouseup', onPanEnd)
  window.removeEventListener('mousemove', onMinimapMouseMove)
  window.removeEventListener('mouseup', onMinimapMouseUp)
  window.removeEventListener('keydown', onModalArrowKeydown)
})
</script>
