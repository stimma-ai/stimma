<template>
  <div
    ref="gridContainerRef"
    class="w-full h-full bg-slideshow-matt flex flex-col overflow-hidden"
    tabindex="0"
    @keydown="handleKeydown"
  >
    <!-- Main content area with explicit scroll -->
    <div
      ref="scrollContainerRef"
      class="flex-1 overflow-x-auto overflow-y-auto p-4 pt-20 min-h-0 custom-scrollbar"
    >
      <div v-if="loading" class="flex items-center justify-center h-full text-content-tertiary">
        Loading grid...
      </div>

      <div v-else-if="error" class="flex items-center justify-center h-full text-red-500">
        {{ error }}
      </div>

      <div v-else>
        <!-- Grid display -->
        <div class="inline-block">
          <table class="border-collapse border-spacing-0">
            <!-- Column headers -->
            <thead v-if="colHeaders.length > 0">
              <tr>
                <th class="sticky left-0 z-10 bg-slideshow-matt" :style="{ width: rowHeaderWidth + 'px', minWidth: rowHeaderWidth + 'px' }"></th>
                <th
                  v-for="(header, idx) in colHeaders"
                  :key="'col-' + idx"
                  class="font-medium text-content-secondary p-3 text-center align-bottom cursor-pointer hover:text-content transition-colors"
                  :class="colHeaderFontClass"
                  :style="colHeadersExpanded
                    ? { width: 'auto', minWidth: colHeaderWidth + 'px' }
                    : { width: colHeaderWidth + 'px', minWidth: colHeaderWidth + 'px' }"
                  @click="toggleColHeaders"
                >
                  <div
                    :class="[
                      'text-left',
                      colHeadersExpanded ? 'whitespace-pre-wrap' : colHeaderClampClass
                    ]"
                  >
                    {{ header }}
                  </div>
                </th>
              </tr>
            </thead>

            <tbody>
              <tr v-for="rowIdx in rows" :key="'row-' + rowIdx">
                <!-- Row header -->
                <td
                  v-if="rowHeaders.length > 0"
                  class="sticky left-0 z-10 bg-slideshow-matt font-medium text-content-secondary p-3 pr-4 align-top cursor-pointer hover:text-content transition-colors text-right overflow-hidden"
                  :class="rowHeaderFontClass"
                  :style="rowHeadersExpanded
                    ? { width: 'auto', maxWidth: '576px' }
                    : { width: rowHeaderWidth + 'px', minWidth: rowHeaderWidth + 'px', maxWidth: rowHeaderWidth + 'px' }"
                  @click="toggleRowHeaders"
                >
                  <div
                    :class="[
                      rowHeadersExpanded ? 'whitespace-pre-wrap' : rowHeaderClampClass
                    ]"
                  >
                    {{ rowHeaders[rowIdx - 1] || '' }}
                  </div>
                </td>
                <td v-else class="w-0"></td>

                <!-- Cells -->
                <td
                  v-for="colIdx in cols"
                  :key="'cell-' + rowIdx + '-' + colIdx"
                  class="p-1.5 align-top"
                >
                  <div
                    :class="[
                      'group w-48 h-48 bg-base rounded overflow-hidden cursor-pointer transition-all relative',
                      isCellSelected(rowIdx - 1, colIdx - 1)
                        ? 'ring-2 ring-selection ring-inset'
                        : isSelectedCell(rowIdx - 1, colIdx - 1)
                          ? 'ring-2 ring-selection ring-inset'
                          : 'hover:ring-2 hover:ring-selection/60'
                    ]"
                    @click="selectCell(rowIdx - 1, colIdx - 1)"
                  >
                    <MediaImage
                      v-if="getCellContent(rowIdx - 1, colIdx - 1)?.resolved"
                      :media-id="mediaIdOf(getCellContent(rowIdx - 1, colIdx - 1).resolved)"
                      :file-hash="getCellContent(rowIdx - 1, colIdx - 1).resolved.file_hash"
                      :file-path="getCellContent(rowIdx - 1, colIdx - 1).resolved.file_path"
                      :file-format="getCellContent(rowIdx - 1, colIdx - 1).resolved.file_format"
                      thumbnail
                      :thumbnail-size="256"
                      :draggable="false"
                      container-class="w-full h-full"
                      img-class="w-full h-full object-cover"
                    />
                    <div v-else class="w-full h-full flex items-center justify-center text-content-muted">
                      <svg class="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke-width="1" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
                      </svg>
                    </div>

                    <button
                      v-if="isEmbeddedCell(getCellContent(rowIdx - 1, colIdx - 1))"
                      class="absolute right-2 top-2 z-10 flex h-7 w-7 items-center justify-center rounded-md bg-zinc-950/80 text-content-muted opacity-0 transition-all hover:text-content group-hover:opacity-100 disabled:opacity-100"
                      :disabled="savingMediaIds.has(mediaIdOf(getCellContent(rowIdx - 1, colIdx - 1).resolved))"
                      title="Keep in All Assets"
                      @click.stop="keepCell(getCellContent(rowIdx - 1, colIdx - 1))"
                    >
                      <svg viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4">
                        <path fill-rule="evenodd" d="M4.25 3A2.25 2.25 0 002 5.25v11.69c0 .839.968 1.306 1.624.782L10 12.62l6.376 5.102A1 1 0 0018 16.94V5.25A2.25 2.25 0 0015.75 3H4.25z" clip-rule="evenodd" />
                      </svg>
                    </button>

                    <!-- Selection checkbox - always visible in multi-select mode -->
                    <div
                      v-if="multiSelectMode && getCellContent(rowIdx - 1, colIdx - 1)?.resolved"
                      class="absolute top-2 left-2 z-10 pointer-events-none"
                    >
                      <div :class="[
                        'w-6 h-6 bg-black/60 backdrop-blur-md border-2 rounded-md flex items-center justify-center transition-all',
                        isCellSelected(rowIdx - 1, colIdx - 1) ? 'bg-selection border-selection' : 'border-edge-strong'
                      ]">
                        <svg v-if="isCellSelected(rowIdx - 1, colIdx - 1)" class="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                        </svg>
                      </div>
                    </div>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { MediaImage } from '../media'
import axios from 'axios'
import { useAssetApi } from '../../composables/useAssetApi'
import { addToast } from '../../composables/useToasts'

const props = defineProps({
  mediaId: {
    type: Number,
    required: true
  },
  // When viewing a cell (grid view mode), highlight the selected cell
  selectedRow: {
    type: Number,
    default: null
  },
  selectedCol: {
    type: Number,
    default: null
  },
  // Multi-select mode for compare feature
  multiSelectMode: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['back', 'select-cell', 'selection-change', 'loaded'])

const gridContainerRef = ref(null)
const scrollContainerRef = ref(null)
const loading = ref(true)
const error = ref(null)
const title = ref('')
const description = ref('')
const rows = ref(0)
const cols = ref(0)
const rowHeaders = ref([])
const colHeaders = ref([])
const cells = ref([])
const savingMediaIds = ref(new Set())
const { promoteContextualMedia } = useAssetApi()

// Track expanded headers (all rows or all cols together)
const rowHeadersExpanded = ref(false)
const colHeadersExpanded = ref(false)

// Multi-select state for compare feature
const selectedCells = ref(new Set()) // Set of "row-col" keys

// Build a lookup map for cells
const cellMap = ref(new Map())

// Adaptive sizing tiers: 'compact' | 'medium' | 'expanded'
// Based on max header length across all headers in that dimension
function getHeaderTier(headers) {
  if (!headers || headers.length === 0) return 'compact'
  const maxLen = Math.max(...headers.map(h => (h || '').length))
  if (maxLen <= 25) return 'compact'    // Short labels: "LoRA A", "Step 1"
  if (maxLen <= 80) return 'medium'     // Medium: "Flux Dev with LoRA weights"
  return 'expanded'                      // Long: paragraphs, prompts
}

const rowHeaderTier = computed(() => getHeaderTier(rowHeaders.value))
const colHeaderTier = computed(() => getHeaderTier(colHeaders.value))

// Row header width in pixels based on tier
const rowHeaderWidth = computed(() => {
  switch (rowHeaderTier.value) {
    case 'compact': return 128    // short labels
    case 'medium': return 160     // medium phrases
    case 'expanded': return 192   // matches image width
  }
})

const rowHeaderFontClass = computed(() => {
  switch (rowHeaderTier.value) {
    case 'compact': return 'text-base'  // 16px
    case 'medium': return 'text-sm'     // 14px
    case 'expanded': return 'text-xs'   // 12px
  }
})

const rowHeaderClampClass = computed(() => {
  switch (rowHeaderTier.value) {
    case 'compact': return 'line-clamp-2'
    case 'medium': return 'line-clamp-4'
    case 'expanded': return 'line-clamp-6'
  }
})

// Column header styling based on tier
const colHeaderWidth = computed(() => {
  switch (colHeaderTier.value) {
    case 'compact': return 195    // Match image width roughly
    case 'medium': return 200
    case 'expanded': return 220
  }
})

const colHeaderFontClass = computed(() => {
  switch (colHeaderTier.value) {
    case 'compact': return 'text-base'
    case 'medium': return 'text-sm'
    case 'expanded': return 'text-xs'
  }
})

const colHeaderClampClass = computed(() => {
  switch (colHeaderTier.value) {
    case 'compact': return 'line-clamp-2'
    case 'medium': return 'line-clamp-4'
    case 'expanded': return 'line-clamp-6'
  }
})

function toggleRowHeaders() {
  rowHeadersExpanded.value = !rowHeadersExpanded.value
}

function toggleColHeaders() {
  colHeadersExpanded.value = !colHeadersExpanded.value
}

function handleWheelNative(e) {
  // Shift+wheel scrolls horizontally
  if (e.shiftKey) {
    const delta = e.deltaY !== 0 ? e.deltaY : e.deltaX
    if (delta !== 0 && scrollContainerRef.value) {
      e.preventDefault()
      scrollContainerRef.value.scrollLeft += delta
    }
  }
}

async function loadContent() {
  loading.value = true
  error.value = null
  // Reset expanded state when loading new content
  rowHeadersExpanded.value = false
  colHeadersExpanded.value = false

  try {
    const response = await axios.get(`/api/media/${props.mediaId}/content`)
    const data = response.data

    title.value = data.title || ''
    description.value = data.description || ''
    rows.value = data.rows || 0
    cols.value = data.cols || 0
    rowHeaders.value = data.row_headers || []
    colHeaders.value = data.col_headers || []
    cells.value = data.cells || []

    // Build cell lookup map
    cellMap.value.clear()
    for (const cell of cells.value) {
      const key = `${cell.row}-${cell.col}`
      cellMap.value.set(key, cell)
    }

    emit('loaded', { title: title.value, description: description.value })
  } catch (e) {
    console.error('Failed to load grid content:', e)
    error.value = 'Failed to load grid content'
  } finally {
    loading.value = false
  }
}

function getCellContent(row, col) {
  const key = `${row}-${col}`
  return cellMap.value.get(key) || null
}

function mediaIdOf(media) {
  return media?.id ?? media?.media_id ?? undefined
}

function isEmbeddedCell(cell) {
  return !!cell?.resolved && !cell.resolved.asset_id && !cell.resolved.saved_asset_id
}

async function keepCell(cell) {
  const mediaId = mediaIdOf(cell?.resolved)
  if (!mediaId || savingMediaIds.value.has(mediaId)) return
  savingMediaIds.value = new Set([...savingMediaIds.value, mediaId])
  try {
    const result = await promoteContextualMedia(mediaId)
    cell.resolved.saved_asset_id = result.asset.asset_id
    addToast('Kept in All Assets', 'success')
  } catch (error) {
    addToast(error?.response?.data?.detail || 'Could not keep cell', 'error')
  } finally {
    const next = new Set(savingMediaIds.value)
    next.delete(mediaId)
    savingMediaIds.value = next
  }
}

function isSelectedCell(row, col) {
  return props.selectedRow === row && props.selectedCol === col
}

// Check if a cell is selected for multi-select/compare
function isCellSelected(row, col) {
  return selectedCells.value.has(`${row}-${col}`)
}

// Toggle cell selection in multi-select mode
function toggleCellSelection(row, col) {
  const key = `${row}-${col}`
  const cell = getCellContent(row, col)
  if (!cell?.resolved) return

  const newSet = new Set(selectedCells.value)
  if (newSet.has(key)) {
    newSet.delete(key)
  } else {
    newSet.add(key)
  }
  selectedCells.value = newSet
  emitSelectionChange()
}

// Emit selection change event with cell details
function emitSelectionChange() {
  const selectedList = []
  for (const key of selectedCells.value) {
    const [row, col] = key.split('-').map(Number)
    const cell = getCellContent(row, col)
    if (cell?.resolved) {
      selectedList.push({
        row,
        col,
        mediaId: mediaIdOf(cell.resolved),
        fileHash: cell.resolved.file_hash
      })
    }
  }
  emit('selection-change', selectedList)
}

// Clear all selections
function clearSelection() {
  selectedCells.value = new Set()
  emitSelectionChange()
}

function selectCell(row, col) {
  const cell = getCellContent(row, col)
  if (!cell?.resolved) return

  // In multi-select mode, toggle selection instead of navigating
  if (props.multiSelectMode) {
    toggleCellSelection(row, col)
    return
  }

  // Normal mode: emit event with cell info and grid data for the parent to handle
  emit('select-cell', {
    row,
    col,
    cell,
    gridData: {
      rows: rows.value,
      cols: cols.value,
      title: title.value,
      cells: cells.value,
      cellMap: cellMap.value,
      rowHeaders: rowHeaders.value,
      colHeaders: colHeaders.value
    }
  })
}

// Handle keyboard navigation within the grid
function handleKeydown(event) {
  // These are handled by SlideshowMode when in grid view mode
  // This is just for focus management
}

// Expose methods for parent to get cell data
function getGridData() {
  return {
    rows: rows.value,
    cols: cols.value,
    title: title.value,
    cells: cells.value,
    cellMap: cellMap.value
  }
}

defineExpose({ getCellContent, getGridData, clearSelection })

onMounted(async () => {
  loadContent()

  await nextTick()
  if (scrollContainerRef.value) {
    scrollContainerRef.value.addEventListener('wheel', handleWheelNative, { passive: false })
  }
  // Focus the grid container for keyboard navigation
  if (gridContainerRef.value) {
    gridContainerRef.value.focus()
  }
})

onUnmounted(() => {
  if (scrollContainerRef.value) {
    scrollContainerRef.value.removeEventListener('wheel', handleWheelNative)
  }
})

watch(() => props.mediaId, () => {
  // Clear selections when switching to a different grid
  selectedCells.value = new Set()
  loadContent()
})

// Clear selections when exiting multi-select mode
watch(() => props.multiSelectMode, (newValue) => {
  if (!newValue) {
    selectedCells.value = new Set()
  }
})
</script>
