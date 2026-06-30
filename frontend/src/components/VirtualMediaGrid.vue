<template>
  <div class="flex-1 flex flex-col overflow-hidden w-full min-w-0">
    <!-- Loading state -->
    <div v-if="initialLoading" class="flex-1 p-2 overflow-hidden">
      <div class="grid grid-cols-6 gap-2 loading-grid">
        <div v-for="i in 18" :key="i" class="loading-skeleton aspect-square rounded-lg w-full h-auto"></div>
      </div>
    </div>

    <!-- Empty state -->
    <EmptyState
      v-else-if="effectiveTotal === 0"
      :icon="emptyStateIcon || 'funnel'"
      :title="emptyStateMessage || 'No assets found'"
      :subtitle="emptyStateSubtext || 'Try adjusting your filters'"
    />

    <!-- Virtual grid using RecycleScroller -->
    <RecycleScroller
      v-else
      ref="scroller"
      :items="allItems"
      :item-size="itemHeight"
      :buffer="bufferSize"
      class="flex-1 min-w-0 overflow-y-scroll overflow-x-hidden media-grid-container custom-scrollbar pt-2"
      @scroll="handleScroll"
      @contextmenu.prevent="handleContainerContextMenu"
      key-field="id"
    >
      <template v-slot="{ item, index }">
        <!-- Placeholder for loading items -->
        <div v-if="item.isPlaceholder" class="overflow-visible box-border w-full min-w-0" :style="rowStyle">
          <div class="grid min-w-0" :style="gridStyle">
            <div v-for="i in itemsPerRow" :key="`placeholder-${item.startIndex}-${i}`" class="grid-cell-placeholder relative aspect-square bg-surface-raised rounded-lg overflow-hidden cursor-pointer flex items-center justify-center">
              <div class="loading-skeleton w-6 h-6 border-2 border-edge border-t-zinc-600 rounded-full"></div>
            </div>
          </div>
        </div>

        <!-- Actual media item -->
        <div v-else class="overflow-visible box-border w-full min-w-0" :style="rowStyle">
          <div class="grid min-w-0" :style="gridStyle">
            <div
              v-for="rowItem in item.items"
              :key="rowItem.id"
              :data-testid="`media-grid-item-${rowItem.id}`"
              :class="[
                'group grid-cell relative aspect-square bg-surface-raised rounded-lg cursor-pointer border border-edge',
                { 'multi-select-mode': multiSelectMode, 'selected ring-[3px] ring-blue-500 ring-inset': isSelected(rowItem.id) },
                { 'context-target ring-2 ring-blue-500/40': contextTargetId === rowItem.id && !isSelected(rowItem.id) }
              ]"
              draggable="true"
              @click.stop="handleItemClick(rowItem.id, rowItem._gridIndex, $event)"
              @contextmenu.stop.prevent="handleRightClick(rowItem, $event)"
              @mousedown="handleMouseDown(rowItem.id, rowItem._gridIndex)"
              @mouseup="handleMouseUp"
              @touchstart="handleTouchStart(rowItem.id, rowItem._gridIndex)"
              @touchend="handleTouchEnd"
              @mouseenter="handleMouseEnter($event, rowItem)"
              @mouseleave="handleMouseLeave($event, rowItem)"
              @dragstart="handleDragStart($event, rowItem)"
              @dragend="handleGridDragEnd"
            >
              <div class="w-full h-full overflow-hidden rounded-lg">
                <AppImage
                  :src="getThumbnailUrl(rowItem.file_hash, GRID_THUMBNAIL_SIZE)"
                  :alt="rowItem.vlm_caption || 'Media item'"
                  :contain="rowItem.file_format === 'stimmalayout'"
                  loading="eager"
                  container-class="w-full h-full"
                />
                <video
                  v-if="isVideo(rowItem)"
                  :ref="el => setVideoRef(rowItem.id, el)"
                  class="absolute inset-0 w-full h-full object-cover hidden"
                  muted
                  loop
                  playsinline
                  preload="none"
                >
                </video>
              </div>

              <!-- Selection checkbox - visible on hover or when selected -->
              <div
                :class="[
                  'absolute top-2 left-2 z-10 transition-opacity',
                  isSelected(rowItem.id) ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
                ]"
                @click.stop="handleCheckboxClick(rowItem.id, rowItem._gridIndex, $event)"
              >
                <div :class="[
                  'w-6 h-6 bg-black/60 backdrop-blur-md border-2 rounded-md flex items-center justify-center transition-all cursor-pointer',
                  isSelected(rowItem.id) ? 'bg-blue-500 border-blue-500' : 'border-edge-strong hover:border-edge-strong'
                ]">
                  <svg v-if="isSelected(rowItem.id)" class="w-4 h-4 text-content" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                  </svg>
                </div>
              </div>

              <!-- Marker badges (only show standalone when no title bar) -->
              <MarkerBadges
                v-if="rowItem.markers && rowItem.markers.length > 0"
                :markers="rowItem.markers"
                class="absolute bottom-2 right-2 z-[6]"
              />

              <!-- Auto-delete time remaining badge (upper left) -->
              <div v-if="rowItem.auto_delete_at && formatRemainingTime(rowItem.auto_delete_at) && formatRemainingTime(rowItem.auto_delete_at) !== '0m'" class="absolute left-2 top-2 z-[5]">
                <div class="bg-black/60 backdrop-blur-md rounded-md px-1.5 py-1 flex items-center justify-center gap-1">
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="currentColor" class="w-3 h-3 text-amber-500">
                    <path fill-rule="evenodd" d="M5 3.25V4H2.75a.75.75 0 0 0 0 1.5h.3l.815 8.15A1.5 1.5 0 0 0 5.357 15h5.285a1.5 1.5 0 0 0 1.493-1.35l.815-8.15h.3a.75.75 0 0 0 0-1.5H11v-.75A2.25 2.25 0 0 0 8.75 1h-1.5A2.25 2.25 0 0 0 5 3.25Zm2.25-.75a.75.75 0 0 0-.75.75V4h3v-.75a.75.75 0 0 0-.75-.75h-1.5ZM6.05 6a.75.75 0 0 1 .787.713l.275 5.5a.75.75 0 0 1-1.498.075l-.275-5.5A.75.75 0 0 1 6.05 6Zm3.9 0a.75.75 0 0 1 .712.787l-.275 5.5a.75.75 0 0 1-1.498-.075l.275-5.5a.75.75 0 0 1 .786-.711Z" clip-rule="evenodd" />
                  </svg>
                  <span class="text-xs font-semibold text-amber-500 leading-none whitespace-nowrap">
                    {{ formatRemainingTime(rowItem.auto_delete_at) }}
                  </span>
                </div>
              </div>


              <!-- Document dog ear (upper right corner fold) -->
              <div v-if="getMediaType(rowItem) === 'text'" class="absolute top-0 right-0 z-[5] pointer-events-none">
                <div class="document-dog-ear"></div>
              </div>

              <!-- Media type badge (upper right) - only for types that need it and not hidden -->
              <div v-if="getMediaType(rowItem) !== 'image' && getMediaType(rowItem) !== 'text'" class="absolute top-2 right-2 z-[5]">
                <div class="bg-black/60 backdrop-blur-md rounded-md px-1.5 py-1 flex items-center gap-1">
                  <!-- Video icon -->
                  <svg v-if="getMediaType(rowItem) === 'video'" class="w-4 h-4 flex-shrink-0 text-green-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.348a1.125 1.125 0 010 1.971l-11.54 6.347a1.125 1.125 0 01-1.667-.985V5.653z" />
                  </svg>
                  <!-- Audio icon (music note) -->
                  <svg v-else-if="getMediaType(rowItem) === 'audio'" class="w-4 h-4 flex-shrink-0 text-purple-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2z" />
                  </svg>
                  <!-- Set icon (layers) -->
                  <svg v-else-if="getMediaType(rowItem) === 'set'" class="w-4 h-4 flex-shrink-0 text-amber-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M6.429 9.75L2.25 12l4.179 2.25m0-4.5l5.571 3 5.571-3m-11.142 0L2.25 7.5 12 2.25l9.75 5.25-4.179 2.25m0 0L21.75 12l-4.179 2.25m0 0l4.179 2.25L12 21.75 2.25 16.5l4.179-2.25m11.142 0l-5.571 3-5.571-3" />
                  </svg>
                  <!-- Grid icon -->
                  <svg v-else-if="getMediaType(rowItem) === 'grid'" class="w-4 h-4 flex-shrink-0 text-cyan-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
                  </svg>
                  <!-- Layout icon (newspaper) -->
                  <svg v-else-if="getMediaType(rowItem) === 'layout'" class="w-4 h-4 flex-shrink-0 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 0 1-2.25 2.25M16.5 7.5V18a2.25 2.25 0 0 0 2.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 0 0 2.25 2.25h13.5M6 7.5h3v3H6v-3Z" />
                  </svg>
                  <!-- Count for set/grid -->
                  <span v-if="(getMediaType(rowItem) === 'set' || getMediaType(rowItem) === 'grid') && rowItem.member_count" class="text-xs font-semibold text-white leading-none whitespace-nowrap">
                    {{ rowItem.member_count }}
                  </span>
                  <!-- Duration for video/audio -->
                  <span v-if="(getMediaType(rowItem) === 'video' || getMediaType(rowItem) === 'audio') && rowItem.duration" class="text-xs font-semibold text-white leading-none whitespace-nowrap">
                    {{ formatDuration(rowItem.duration) }}
                  </span>
                </div>
              </div>

              <!-- Similarity score badge -->
              <div v-if="rowItem.similarity_score !== null && rowItem.similarity_score !== undefined" class="absolute bottom-2 left-2 z-[5] bg-black/60 backdrop-blur-md rounded-md px-1.5 py-1 text-xs font-semibold text-white">
                {{ formatSimilarity(rowItem.similarity_score) }}
              </div>

              <!-- Set/Grid name pill (hover only) -->
              <div
                v-if="(getMediaType(rowItem) === 'set' || getMediaType(rowItem) === 'grid') && rowItem.title"
                class="absolute inset-0 z-[7] flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none"
              >
                <span class="bg-black/80 backdrop-blur-md rounded-lg px-3 py-1.5 text-xs font-medium text-white text-center line-clamp-2 max-w-[80%]">
                  {{ rowItem.title }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </template>
    </RecycleScroller>

    <!-- Item context menu -->
    <MediaContextMenu
      @refresh="$emit('context-menu-action', { action: 'refresh' })"
      @permanent-delete="(mediaId) => $emit('context-menu-action', { action: 'permanent-delete', targetIds: [mediaId] })"
    />

    <!-- Empty space context menu -->
    <ActionMenu
      v-if="showEmptySpaceMenu"
      :x="contextMenuX"
      :y="contextMenuY"
      :actions="emptySpaceMenuActions"
      @select="handleEmptySpaceMenuAction"
      @close="closeEmptySpaceMenu"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, onActivated, onDeactivated, nextTick } from 'vue'
import { RecycleScroller } from 'vue-virtual-scroller'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'
import { useMediaApi } from '../composables/useMediaApi'
import { useWebSocket } from '../composables/useWebSocket'
import { AppImage, MediaContextMenu } from './media'
import MarkerBadges from './MarkerBadges.vue'
import ActionMenu from './ActionMenu.vue'
import EmptyState from './EmptyState.vue'
import { useMediaContextMenu } from '../composables/useMediaContextMenu'
import { formatRemainingTime } from '../utils/timeFormat'
import { createDragPreview, preloadDragPreview, handleDragEnd as dragPreviewHandleDragEnd } from '../composables/useDragPreview'
import { getMediaType, isVideo as isVideoType, isAudio, getBadgeConfig, formatDuration as formatMediaDuration } from '../utils/mediaTypes'
import { makeProfileKey } from '../utils/storageKeys'

const props = defineProps({
  /**
   * Shared media list (optional). When provided, the grid uses this shared cache
   * instead of maintaining its own. This ensures the slideshow sees the same items.
   */
  mediaList: {
    type: Object,
    default: null
  },
  totalCount: {
    type: Number,
    required: true
  },
  /**
   * Page provider function. Required if mediaList is not provided.
   */
  pageProvider: {
    type: Function,
    default: null
  },
  loading: {
    type: Boolean,
    default: false
  },
  multiSelectMode: {
    type: Boolean,
    default: false
  },
  selectedItemIds: {
    type: Array,
    default: () => []
  },
  isTrashView: {
    type: Boolean,
    default: false
  },
  emptyStateMessage: {
    type: String,
    default: null
  },
  emptyStateSubtext: {
    type: String,
    default: null
  },
  emptyStateIcon: {
    type: String,
    default: null
  },
  /**
   * Whether this grid is inside a board view
   */
  inBoard: {
    type: Boolean,
    default: false
  },
  /**
   * The board section ID if viewing a board section
   */
  boardSectionId: {
    type: Number,
    default: null
  },
  /**
   * Whether viewing a project
   */
  inProject: {
    type: Boolean,
    default: false
  },
  /**
   * The project ID if viewing a project
   */
  projectId: {
    type: Number,
    default: null
  },
  /**
   * Storage key for persisting scroll position across navigation.
   * If provided, scroll position is saved to sessionStorage.
   * Use a unique key per view (e.g., 'browse', 'trash', 'board-123').
   */
  storageKey: {
    type: String,
    default: null
  }
})

// WebSocket for live marker/tag updates
const ws = useWebSocket()
let unsubscribeMediaUpdated = null
let unsubscribeMediaDeleted = null
let unsubscribeBulkDeleted = null
let unsubscribeAutoDelete = null
let autoMarkersSyncedHandler = null

const emit = defineEmits(['item-click', 'item-find-similar', 'toggle-selection', 'shift-click-range', 'context-menu-action', 'empty-space-action', 'items-removed'])

const { getThumbnailUrl, getMediaFileUrl } = useMediaApi()
const mediaContextMenu = useMediaContextMenu()

// Refs
const scroller = ref(null)
const videoRefs = ref(new Map())
const initialLoading = ref(true)
const savedScrollPosition = ref(0)

/**
 * Get the sessionStorage key for scroll position
 */
function getScrollStorageKey() {
  return props.storageKey ? `${makeProfileKey('grid_scroll')}_${props.storageKey}` : null
}

/**
 * Save scroll position to sessionStorage
 */
function saveScrollToStorage(scrollTop) {
  const key = getScrollStorageKey()
  if (!key) return
  try {
    sessionStorage.setItem(key, JSON.stringify({
      scrollTop,
      savedAt: Date.now()
    }))
  } catch (e) {
    // Ignore storage errors
  }
}

/**
 * Load scroll position from sessionStorage
 * @returns {number|null} Saved scroll position, or null when missing/expired
 */
function loadScrollFromStorage() {
  const key = getScrollStorageKey()
  if (!key) return null
  try {
    const stored = sessionStorage.getItem(key)
    if (!stored) return null
    const data = JSON.parse(stored)
    // Expire after 30 minutes (user probably moved on)
    const THIRTY_MINUTES = 30 * 60 * 1000
    if (Date.now() - data.savedAt > THIRTY_MINUTES) {
      sessionStorage.removeItem(key)
      return null
    }
    return Number.isFinite(data.scrollTop) ? data.scrollTop : 0
  } catch (e) {
    return null
  }
}

// Debounce timer for scroll position saving
let scrollSaveTimer = null

/**
 * Debounced scroll position save (500ms delay)
 */
function debouncedSaveScroll(scrollTop) {
  if (!props.storageKey) return
  if (scrollSaveTimer) clearTimeout(scrollSaveTimer)
  scrollSaveTimer = setTimeout(() => {
    saveScrollToStorage(scrollTop)
  }, 500)
}

// Context menu state
const contextMenuX = ref(0)
const contextMenuY = ref(0)
const contextTargetId = ref(null)  // ID of item being targeted by context menu

// Empty space context menu state
const showEmptySpaceMenu = ref(false)

// Long-press detection
const longPressTimer = ref(null)
const longPressTriggered = ref(false)

// Range selection state
const lastClickedIndex = ref(null)
const lastClickedAction = ref('select') // 'select' or 'deselect'

// Empty space context menu actions
const emptySpaceMenuActions = computed(() => {
  // Don't show in trash view
  if (props.isTrashView) {
    return [
      {
        id: 'select-all',
        label: 'Select All',
        icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 11l3 3L22 4"/></svg>'
      }
    ]
  }

  return [
    {
      id: 'select-all',
      label: 'Select All',
      icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 11l3 3L22 4"/></svg>'
    },
    { id: 'divider' },
    {
      id: 'import',
      label: 'Import Images...',
      icon: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><path d="M7 10l5 5 5-5"/><path d="M12 15V3"/></svg>'
    }
  ]
})

// Grid configuration
const GRID_SIDE_PADDING_PX = 16 // px-2 -> 8px left + 8px right
// CSS grid rounds fractional square tile widths to physical pixels. The virtual
// row stride needs a small compensation so the measured row gap matches the
// 8px column gap on 2x displays.
const ROW_VERTICAL_GUTTER_PX = 10.5
const GRID_GAP_PX = 8 // gap-2
const GRID_THUMBNAIL_SIZE = 512
const itemsPerRow = ref(6) // Will be calculated based on window width
const itemHeight = ref(220) // Height of each virtual row (item width + vertical gutter)
const bufferSize = ref(1200) // Render buffer
const selectedItemIdSet = computed(() => new Set(props.selectedItemIds))

const rowStyle = {
  paddingLeft: `${GRID_SIDE_PADDING_PX / 2}px`,
  paddingRight: `${GRID_SIDE_PADDING_PX / 2}px`,
  paddingBottom: `${ROW_VERTICAL_GUTTER_PX}px`
}

const gridStyle = computed(() => ({
  gridTemplateColumns: `repeat(${itemsPerRow.value}, minmax(0, 1fr))`,
  gap: `${GRID_GAP_PX}px`
}))

// Data management - use shared mediaList if provided, otherwise local state
const localLoadedPages = ref(new Set())
const localItemsCache = ref(new Map()) // Cache items by index
const allItems = ref([])
const skipNextTotalCountWatch = ref(false) // Flag to skip watcher after soft update
const localRemovedIds = ref(new Set()) // Track IDs that have been removed locally

// Use shared state from mediaList if available, otherwise local state
const loadedPages = computed(() => props.mediaList ? props.mediaList.loadedPages.value : localLoadedPages.value)
const itemsCache = computed(() => props.mediaList ? props.mediaList.itemsCache.value : localItemsCache.value)
const removedIds = computed(() => props.mediaList ? props.mediaList.removedIds.value : localRemovedIds.value)

// Effective total count (uses mediaList's effectiveTotal if available, otherwise props.totalCount minus locally removed items)
const effectiveTotal = computed(() => {
  if (props.mediaList) {
    return props.mediaList.effectiveTotal.value
  }
  // For local mode, subtract locally removed items that haven't been reflected in totalCount yet
  return Math.max(0, props.totalCount - localRemovedIds.value.size)
})

// Calculate items per row based on window width
function calculateItemsPerRow() {
  // Get actual container width from the scroller element
  const scrollerEl = scroller.value?.$el

  // clientWidth excludes scrollbar, then we remove row horizontal padding (px-2)
  const scrollerWidth = scrollerEl ? scrollerEl.clientWidth : window.innerWidth
  const gridWidth = scrollerWidth - GRID_SIDE_PADDING_PX

  const minItemWidth = 200
  const gap = GRID_GAP_PX

  // Calculate how many items fit: floor((width + gap) / (minWidth + gap))
  const newItemsPerRow = Math.max(1, Math.floor((gridWidth + gap) / (minItemWidth + gap)))

  // Calculate actual item width: (gridWidth - total gaps) / itemsPerRow
  const totalGaps = gap * (newItemsPerRow - 1)
  const actualItemWidth = (gridWidth - totalGaps) / newItemsPerRow

  // Row height = square item height + row vertical gutter (py-2 top+bottom)
  const newItemHeight = actualItemWidth + ROW_VERTICAL_GUTTER_PX

  console.log('Grid calc:', {
    scrollerWidth,
    gridWidth,
    itemsPerRow: newItemsPerRow,
    actualItemWidth,
    itemHeight: newItemHeight
  })

  // Check if items per row changed - if so, we need to rebuild everything
  const itemsPerRowChanged = newItemsPerRow !== itemsPerRow.value

  itemsPerRow.value = newItemsPerRow
  itemHeight.value = newItemHeight

  return itemsPerRowChanged
}

// Convert flat items into rows for the grid
// Core implementation - called directly or via RAF batching
let buildRowsRafId = null

function buildRowsImmediate() {
  const rows = []
  const perRow = itemsPerRow.value
  const total = effectiveTotal.value
  const totalRows = Math.ceil(total / perRow)
  const cache = itemsCache.value

  // Determine the range of indices that have cached data to skip
  // cache lookups for rows that are guaranteed to be placeholders
  let minCachedIndex = Infinity
  let maxCachedIndex = -1
  if (cache.size > 0) {
    for (const key of cache.keys()) {
      if (key < minCachedIndex) minCachedIndex = key
      if (key > maxCachedIndex) maxCachedIndex = key
    }
  }

  const minCachedRow = minCachedIndex === Infinity ? -1 : Math.floor(minCachedIndex / perRow)
  const maxCachedRow = maxCachedIndex === -1 ? -1 : Math.floor(maxCachedIndex / perRow)

  for (let rowIndex = 0; rowIndex < totalRows; rowIndex++) {
    const startIndex = rowIndex * perRow

    // Skip cache lookups for rows outside the loaded range
    if (rowIndex < minCachedRow || rowIndex > maxCachedRow) {
      rows.push({
        id: `row-${rowIndex}`,
        isPlaceholder: true,
        startIndex: startIndex
      })
      continue
    }

    const rowItems = []
    for (let i = 0; i < perRow; i++) {
      const itemIndex = startIndex + i
      if (itemIndex >= total) break

      const item = cache.get(itemIndex)
      if (item) {
        if (item._gridIndex !== itemIndex) item._gridIndex = itemIndex
        rowItems.push(item)
      }
    }

    if (rowItems.length > 0) {
      rows.push({
        id: `row-${rowIndex}`,
        isPlaceholder: false,
        items: rowItems,
        startIndex: startIndex
      })
    } else {
      rows.push({
        id: `row-${rowIndex}`,
        isPlaceholder: true,
        startIndex: startIndex
      })
    }
  }

  allItems.value = rows
}

// Debounced version - batches multiple triggers within the same frame
function buildRows() {
  if (buildRowsRafId !== null) {
    cancelAnimationFrame(buildRowsRafId)
  }
  buildRowsRafId = requestAnimationFrame(() => {
    buildRowsRafId = null
    buildRowsImmediate()
  })
}

// Load a page of items
async function loadPage(pageNumber) {
  // Guard against NaN or invalid page numbers
  if (!Number.isFinite(pageNumber) || pageNumber < 0) {
    console.warn(`Invalid page number: ${pageNumber}`)
    return
  }

  // If using shared mediaList, delegate to it
  if (props.mediaList) {
    const pageKey = `${pageNumber}:200`
    if (loadedPages.value.has(pageKey)) {
      return // Already loaded
    }
    const startTime = performance.now()
    console.log(`[loadPage] START page ${pageNumber} (via mediaList)`)
    try {
      await props.mediaList.loadPage(pageNumber, 200)
      console.log(`[loadPage] DONE page ${pageNumber} in ${(performance.now() - startTime).toFixed(0)}ms`)
      // Rebuild rows after loading
      buildRows()
    } catch (error) {
      console.error(`[loadPage] FAILED page ${pageNumber}:`, error)
    }
    return
  }

  // Local loading logic (when no shared mediaList)
  const localPageKey = `${pageNumber}:200`
  if (localLoadedPages.value.has(localPageKey)) {
    return // Already loaded
  }

  localLoadedPages.value.add(localPageKey)

  const startTime = performance.now()
  console.log(`[loadPage] START page ${pageNumber} (local)`)
  try {
    const pageSize = 200
    const items = await props.pageProvider(pageNumber, pageSize)
    console.log(`[loadPage] DONE page ${pageNumber} in ${(performance.now() - startTime).toFixed(0)}ms, got ${items.length} items`)

    // Cache items by their index
    const startIndex = pageNumber * pageSize
    items.forEach((item, i) => {
      localItemsCache.value.set(startIndex + i, item)
    })

    // Rebuild rows
    buildRows()
  } catch (error) {
    console.error(`[loadPage] FAILED page ${pageNumber}:`, error)
    localLoadedPages.value.delete(localPageKey)
  }
}

// Handle scroll to load pages as needed
// Split into immediate (save scroll position) and frame-coalesced page loading.
let scrollPageLoadRafId = null

function handleScroll() {
  if (!scroller.value) return

  const { scrollTop } = scroller.value.$el

  // Track latest known scroll position immediately, even if debounced storage
  // write hasn't executed yet.
  savedScrollPosition.value = scrollTop

  // Save scroll position for persistence (debounced) - immediate path
  debouncedSaveScroll(scrollTop)

  // Coalesce page loading to the next frame so fast scrollbar scrubs do not
  // pay an extra fixed delay before the visible page request can start.
  if (scrollPageLoadRafId !== null) {
    return
  }
  scrollPageLoadRafId = requestAnimationFrame(() => {
    scrollPageLoadRafId = null
    loadVisiblePages()
  })
}

async function loadVisiblePages() {
  if (!scroller.value) return

  const { scrollTop, clientHeight } = scroller.value.$el
  const scrollBottom = scrollTop + clientHeight

  // Calculate which rows are visible
  const startRow = Math.floor(scrollTop / itemHeight.value)
  const endRow = Math.ceil(scrollBottom / itemHeight.value)

  // Add buffer rows
  const bufferRows = 3
  const startRowWithBuffer = Math.max(0, startRow - bufferRows)
  const endRowWithBuffer = Math.min(Math.ceil(props.totalCount / itemsPerRow.value), endRow + bufferRows)

  // Calculate which pages we need
  const pageSize = 200
  const startIndex = startRowWithBuffer * itemsPerRow.value
  const endIndex = endRowWithBuffer * itemsPerRow.value

  const startPage = Math.floor(startIndex / pageSize)
  const endPage = Math.floor(endIndex / pageSize)

  // Load pages in parallel (not sequentially)
  const pagesToLoad = []
  const pagesNeeded = []
  for (let page = startPage; page <= endPage; page++) {
    if (!loadedPages.value.has(`${page}:${pageSize}`)) {
      pagesNeeded.push(page)
      pagesToLoad.push(loadPage(page))
    }
  }
  if (pagesNeeded.length > 0) {
    console.log(`[scroll] scrollTop=${scrollTop} rows=${startRow}-${endRow} need pages: ${pagesNeeded.join(',')} (already loaded: ${[...loadedPages.value].join(',')})`)
  }
  await Promise.all(pagesToLoad)
}

function getActualIndex(rowIndex) {
  const row = allItems.value[rowIndex]
  return row.startIndex
}

function isVideo(item) {
  if (!item) return false
  return isVideoType(item)
}

function formatSimilarity(score) {
  return `${(score * 100).toFixed(1)}%`
}

function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return '0:00'

  const hrs = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  const secs = Math.floor(seconds % 60)

  if (hrs > 0) {
    return `${hrs}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
  }
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function setVideoRef(itemId, el) {
  if (el) {
    videoRefs.value.set(itemId, el)
  } else {
    videoRefs.value.delete(itemId)
  }
}

// Pending video hover timers keyed by item ID
const videoHoverTimers = new Map()

function handleMouseEnter(event, item) {
  // Preload drag preview thumbnail on hover
  if (item?.file_hash) {
    preloadDragPreview(getThumbnailUrl(item.file_hash, 128))
  }

  // Only play video on hover for actual video files (not audio or structured types)
  if (isVideo(item) && getMediaType(item) === 'video') {
    // Delay video loading to avoid firing on rapid mouse movement
    const timerId = setTimeout(() => {
      videoHoverTimers.delete(item.id)
      const video = videoRefs.value.get(item.id)
      if (video) {
        if (!video.src) {
          video.src = getMediaFileUrl(item.file_hash)
        }
        video.classList.remove('hidden')
        video.currentTime = 0
        video.play().catch(err => {
          console.warn('Video autoplay failed:', err)
        })
      }
    }, 250)
    videoHoverTimers.set(item.id, timerId)
  }
}

function handleDragStart(event, item) {
  // Cancel any long-press timer
  if (longPressTimer.value) {
    clearTimeout(longPressTimer.value)
    longPressTimer.value = null
  }

  // Create drag preview with media info for sidebar tool compatibility
  if (item?.id && item?.file_hash) {
    const thumbnailUrl = getThumbnailUrl(item.file_hash, 128)
    const fileFormat = item.file_format || ''
    const itemIsVideo = isVideo(item)
    // If the dragged item is part of a multi-selection, include all selected IDs
    const allIds = props.selectedItemIds.includes(item.id) && props.selectedItemIds.length > 1
      ? [...props.selectedItemIds]
      : undefined
    createDragPreview(event, thumbnailUrl, item.id, fileFormat, itemIsVideo, allIds)
  }
}

function handleGridDragEnd() {
  dragPreviewHandleDragEnd()
}

function handleMouseLeave(event, item) {
  if (isVideo(item)) {
    // Cancel pending hover timer if mouse leaves before delay
    const timerId = videoHoverTimers.get(item.id)
    if (timerId) {
      clearTimeout(timerId)
      videoHoverTimers.delete(item.id)
    }
    const video = videoRefs.value.get(item.id)
    if (video) {
      video.pause()
      video.currentTime = 0
      video.classList.add('hidden')
    }
  }
}

// Multi-select helpers
function isSelected(itemId) {
  return selectedItemIdSet.value.has(itemId)
}

function handleItemClick(itemId, index, event) {
  // Shift-click for range selection - works when there's an anchor point (lastClickedIndex)
  if (event.shiftKey && lastClickedIndex.value !== null) {
    handleRangeSelection(index)
    return
  }

  // Cmd/Ctrl-click to toggle selection (like checkbox click)
  if (event.metaKey || event.ctrlKey) {
    emit('toggle-selection', itemId, index)
    lastClickedIndex.value = index
    return
  }

  if (props.multiSelectMode) {
    emit('toggle-selection', itemId, index)
    lastClickedIndex.value = index
  } else {
    // Emit both item ID and index
    // ID is used for stable lookups when DB changes
    // Index is used as fallback for similarity search (which can't use find-index API)
    emit('item-click', { itemId, index })
    // Track last clicked index even in non-multiselect mode for shift-click anchor
    lastClickedIndex.value = index
  }
}

function handleCheckboxClick(itemId, index, event) {
  // Shift-click for range selection
  if (event && event.shiftKey && lastClickedIndex.value !== null) {
    handleRangeSelection(index)
    return
  }

  // Track whether this click is selecting or deselecting (before the toggle)
  const wasSelected = isSelected(itemId)
  lastClickedAction.value = wasSelected ? 'deselect' : 'select'

  // Regular click toggles selection
  emit('toggle-selection', itemId, index)
  lastClickedIndex.value = index
}

function handleRightClick(item, event) {
  // Show context menu only - right-click should never change selection
  if (item) {
    contextTargetId.value = item.id  // Track which item is being targeted

    // Check if clicked item is in the current selection
    const inSelection = props.selectedItemIds.includes(item.id)

    if (inSelection && props.selectedItemIds.length > 1) {
      // Operating on multiple selected items
      const targetIds = [...props.selectedItemIds]
      const selectedItems = getItemsByIds(targetIds)
      mediaContextMenu.show({
        event,
        mediaId: item.id,  // Primary item for display
        mediaIds: targetIds,
        selectedItems,
        inBoard: props.inBoard,
        boardSectionId: props.boardSectionId,
        inProject: props.inProject,
        projectId: props.projectId
      })
    } else {
      // Operating on single item (clicked item, regardless of selection)
      mediaContextMenu.show({
        event,
        mediaId: item.id,
        mediaIds: [item.id],
        selectedItems: [item],
        inBoard: props.inBoard,
        boardSectionId: props.boardSectionId,
        inProject: props.inProject,
        projectId: props.projectId
      })
    }
  }
}


function handleContainerContextMenu(event) {
  // Check if right-click is on empty space (not on a grid item)
  // Grid items have the .grid-cell class
  const target = event.target
  const isOnItem = target.closest('.grid-cell') || target.closest('.grid-cell-placeholder')

  if (!isOnItem) {
    // Show empty space context menu
    contextMenuX.value = event.clientX
    contextMenuY.value = event.clientY
    showEmptySpaceMenu.value = true
  }
}

function handleEmptySpaceMenuAction(action) {
  showEmptySpaceMenu.value = false
  emit('empty-space-action', { action })
}

function closeEmptySpaceMenu() {
  showEmptySpaceMenu.value = false
}

function handleRangeSelection(endIndex) {
  if (lastClickedIndex.value === null) {
    return
  }

  // Get the range of indices
  const start = Math.min(lastClickedIndex.value, endIndex)
  const end = Math.max(lastClickedIndex.value, endIndex)

  // Collect all item IDs in the range
  const idsToSelect = []
  for (let i = start; i <= end; i++) {
    const item = itemsCache.value.get(i)
    if (item && item.id) {
      idsToSelect.push(item.id)
    }
  }

  // Emit the range of IDs to select/deselect
  if (idsToSelect.length > 0) {
    emit('shift-click-range', { ids: idsToSelect, endIndex, action: lastClickedAction.value })
  }

  lastClickedIndex.value = endIndex
}

function handleMouseDown(itemId, index) {
  longPressTriggered.value = false
  longPressTimer.value = setTimeout(() => {
    longPressTriggered.value = true
    // Long press opens context menu (similar to right-click)
    // Selection is not changed
  }, 500) // 500ms for long press
}

function handleMouseUp() {
  if (longPressTimer.value) {
    clearTimeout(longPressTimer.value)
    longPressTimer.value = null
  }
}

function handleTouchStart(itemId, index) {
  longPressTriggered.value = false
  longPressTimer.value = setTimeout(() => {
    longPressTriggered.value = true
    // Long press opens context menu (similar to right-click)
    // Selection is not changed
  }, 500) // 500ms for long press
}

function handleTouchEnd() {
  if (longPressTimer.value) {
    clearTimeout(longPressTimer.value)
    longPressTimer.value = null
  }
}

// Get all visible (loaded) item IDs
function getAllVisibleIds() {
  const ids = []
  for (const [index, item] of itemsCache.value.entries()) {
    if (item && item.id) {
      ids.push(item.id)
    }
  }
  return ids
}

// Get items by IDs (for checking marker state, etc.)
function getItemsByIds(ids) {
  // Access cacheVersion to trigger reactivity when items are updated
  if (props.mediaList?.cacheVersion) {
    void props.mediaList.cacheVersion.value
  }
  const idSet = new Set(ids)
  const items = []
  for (const [index, item] of itemsCache.value.entries()) {
    if (item && idSet.has(item.id)) {
      items.push(item)
    }
  }
  return items
}

// Prepend new items to the grid without resetting scroll position
// This is used for live updates when new media is added
async function prependItems(newItems, newTotalCount) {
  if (!newItems || newItems.length === 0) return

  // Set flag to skip the totalCount watcher since we're handling the update ourselves
  skipNextTotalCountWatch.value = true

  // If using shared mediaList, delegate to it
  if (props.mediaList) {
    // Get current scroll position
    const scrollerEl = scroller.value?.$el
    const currentScrollTop = scrollerEl ? scrollerEl.scrollTop : 0

    // Deduplicate: only add items that aren't already in the cache
    const existingIds = new Set()
    for (const item of itemsCache.value.values()) {
      if (item?.id) existingIds.add(item.id)
    }
    const uniqueNewItems = newItems.filter(item => item?.id && !existingIds.has(item.id))

    if (uniqueNewItems.length === 0) return

    props.mediaList.prependItems(uniqueNewItems)
    buildRows()

    // Calculate scroll adjustment
    const rowsAdded = Math.ceil(uniqueNewItems.length / itemsPerRow.value)
    const pixelsToAdd = rowsAdded * itemHeight.value

    await nextTick()
    if (scrollerEl && currentScrollTop > 0) {
      scrollerEl.scrollTop = currentScrollTop + pixelsToAdd
    }
    handleScroll()
    return
  }

  // Local logic (when no shared mediaList)
  // Deduplicate: only add items that aren't already in the cache
  const existingIds = new Set()
  for (const item of localItemsCache.value.values()) {
    if (item?.id) existingIds.add(item.id)
  }
  const uniqueNewItems = newItems.filter(item => item?.id && !existingIds.has(item.id))

  if (uniqueNewItems.length === 0) {
    // All items were duplicates, nothing to prepend
    return
  }

  const countToAdd = uniqueNewItems.length

  // Get current scroll position
  const scrollerEl = scroller.value?.$el
  const currentScrollTop = scrollerEl ? scrollerEl.scrollTop : 0

  // Create new cache with shifted indices
  const newCache = new Map()

  // First, add new unique items at the beginning
  uniqueNewItems.forEach((item, i) => {
    newCache.set(i, item)
  })

  // Then shift existing cached items by the count of new items
  for (const [index, item] of localItemsCache.value.entries()) {
    newCache.set(index + countToAdd, item)
  }

  // Update the cache
  localItemsCache.value = newCache

  // Update loaded pages - shift page numbers
  // Since we're prepending, all existing pages are now at higher indices
  // Clear and let the scroll handler reload as needed
  localLoadedPages.value.clear()
  // Mark page 0 as loaded since we just populated it
  localLoadedPages.value.add('0:200')

  // Rebuild rows with new total count
  // Note: props.totalCount should be updated by parent before or after this call
  buildRows()

  // Calculate how many rows worth of pixels to shift
  const rowsAdded = Math.ceil(countToAdd / itemsPerRow.value)
  const pixelsToAdd = rowsAdded * itemHeight.value

  // Adjust scroll position to keep current items in view
  await nextTick()
  if (scrollerEl && currentScrollTop > 0) {
    scrollerEl.scrollTop = currentScrollTop + pixelsToAdd
  }

  // Trigger scroll handler to load any needed pages around current position
  handleScroll()
}

// Expose methods to parent
// Show context menu for a specific item programmatically (for keyboard shortcuts)
function showContextMenuForItem(itemId) {
  // Find the item in cache by ID
  let itemElement = null
  let foundItem = false

  // Search through the cache for the item
  for (const [index, cachedItem] of itemsCache.value.entries()) {
    if (cachedItem && cachedItem.id === itemId) {
      foundItem = true
      // Try to find the DOM element for this item
      const gridCells = document.querySelectorAll('.grid-cell')
      for (const cell of gridCells) {
        // Match by finding the cell that contains this item's data
        if (cell.querySelector(`[data-media-id="${itemId}"]`) || cell.closest(`[data-media-id="${itemId}"]`)) {
          itemElement = cell
          break
        }
      }
      // If we can't find by data attribute, try to find by index
      if (!itemElement && gridCells[index]) {
        itemElement = gridCells[index]
      }
      break
    }
  }

  if (foundItem) {
    contextTargetId.value = itemId

    // Position menu at item's location if we found the element, otherwise center of viewport
    let x, y
    if (itemElement) {
      const rect = itemElement.getBoundingClientRect()
      x = rect.left + rect.width / 2
      y = rect.top + rect.height / 2
    } else {
      // Fallback: center of viewport
      x = window.innerWidth / 2
      y = window.innerHeight / 2
    }

    // Create a synthetic event for the composable
    const syntheticEvent = {
      clientX: x,
      clientY: y,
      preventDefault: () => {},
      stopPropagation: () => {}
    }

    // Check if item is in the current selection
    const inSelection = props.selectedItemIds.includes(itemId)

    if (inSelection && props.selectedItemIds.length > 1) {
      // Operating on multiple selected items
      const targetIds = [...props.selectedItemIds]
      const selectedItems = getItemsByIds(targetIds)
      mediaContextMenu.show({
        event: syntheticEvent,
        mediaId: itemId,
        mediaIds: targetIds,
        selectedItems,
        inBoard: props.inBoard,
        boardSectionId: props.boardSectionId,
        inProject: props.inProject,
        projectId: props.projectId
      })
    } else {
      // Operating on single item
      const item = getItemsByIds([itemId])[0]
      mediaContextMenu.show({
        event: syntheticEvent,
        mediaId: itemId,
        mediaIds: [itemId],
        selectedItems: item ? [item] : [],
        inBoard: props.inBoard,
        boardSectionId: props.boardSectionId,
        inProject: props.inProject,
        projectId: props.projectId
      })
    }
  }
}

// Restore saved scroll position (used when grid becomes visible after being hidden)
async function restoreScrollPosition() {
  await nextTick()
  // Prefer sessionStorage (updated on every scroll via debouncedSaveScroll)
  // over in-memory savedScrollPosition (only updated on deactivate/activate).
  // This ensures we get the most recent scroll position when the grid was
  // scrolled after a previous restoration.
  const storedScroll = loadScrollFromStorage()
  const scrollToRestore = storedScroll ?? savedScrollPosition.value
  if (scroller.value?.$el && scrollToRestore > 0) {
    scroller.value.$el.scrollTop = scrollToRestore
    savedScrollPosition.value = scrollToRestore
    await nextTick()
    handleScroll()
  }
}

function scrollToTop() {
  const scrollerEl = scroller.value?.$el
  if (!scrollerEl) return
  scrollerEl.scrollTop = 0
  savedScrollPosition.value = 0
  saveScrollToStorage(0)
  handleScroll()
}

// Force the grid back into a consistent state after the item count shrank
// (e.g. a bulk delete). RecycleScroller does not recompute its total height or
// clamp an out-of-range scrollTop until it sees a scroll event, so after a large
// removal the scrollbar stays too long and loadVisiblePages reads a stale,
// out-of-range scrollTop (computing an empty page range -> permanent spinners /
// gap-toothed rows). Rebuild rows now, nudge the scroller to recompute + clamp,
// then load whatever is actually visible.
async function refreshAfterRemoval() {
  // We own the post-removal rebuild — suppress the totalCount watcher so it
  // doesn't also kick off a reload and fight us over the scroll position.
  skipNextTotalCountWatch.value = true
  previousTotalCount = props.totalCount

  buildRowsImmediate()
  await nextTick()
  const el = scroller.value?.$el
  if (!el) return
  // RecycleScroller keeps a stale total height and an out-of-range scrollTop
  // after the item count shrinks, and won't recompute until it sees a scroll
  // within the new range. Its scrollHeight is still stale here, so compute the
  // new content height from the row count and clamp scrollTop into range before
  // dispatching the scroll that triggers the recompute + visible-page load.
  const contentHeight = allItems.value.length * itemHeight.value
  const maxScroll = Math.max(0, contentHeight - el.clientHeight)
  if (el.scrollTop > maxScroll) el.scrollTop = maxScroll
  el.dispatchEvent(new Event('scroll'))
  await nextTick()
  savedScrollPosition.value = el.scrollTop
  await loadVisiblePages()
}

defineExpose({
  getAllVisibleIds,
  getItemsByIds,
  prependItems,
  removeItems,
  refreshAfterRemoval,
  showContextMenuForItem,
  restoreScrollPosition,
  scrollToTop
})

// Clear context target when media context menu closes
watch(
  () => mediaContextMenu.state.value.visible,
  (visible) => {
    if (!visible) {
      contextTargetId.value = null
    }
  }
)

// Watch for mediaList cache changes (when slideshow loads items, grid should reflect them)
// Also trigger handleScroll to reload visible items when cache is invalidated (e.g., after silentReload)
watch(
  () => props.mediaList?.cacheVersion?.value,
  () => {
    if (props.mediaList) {
      buildRows()
      // Re-check if visible pages need loading (important after silentReload clears loadedPages)
      handleScroll()
    }
  }
)

// Watch for totalCount changes (filter updates)
// Track previous totalCount to detect small vs large changes
let previousTotalCount = props.totalCount

watch(() => props.totalCount, async (newCount) => {
  // Skip if this was triggered by a soft update (prependItems)
  if (skipNextTotalCountWatch.value) {
    skipNextTotalCountWatch.value = false
    previousTotalCount = newCount
    return
  }

  // Calculate the difference in count
  const countDiff = previousTotalCount - newCount
  previousTotalCount = newCount

  // No change - shouldn't happen but guard against it
  if (countDiff === 0) {
    return
  }

  // If count decreased by a small amount (1-10 items), this is likely auto-delete or user deletion
  // Just rebuild rows without clearing cache - items will show as missing until refreshed
  // This prevents the "blink" when auto-delete removes a few items
  if (countDiff > 0 && countDiff <= 10) {
    // Clear locally removed IDs since server count now reflects the deletion
    if (!props.mediaList) {
      localRemovedIds.value.clear()
    }
    buildRows()
    return
  }

  // For larger changes (filter updates, etc.), do a full refresh
  // Save current scroll position before resetting
  let currentScrollTop = 0
  if (scroller.value?.$el) {
    currentScrollTop = scroller.value.$el.scrollTop
  }

  // Clear page tracking and removed IDs (full refresh)
  // When using shared mediaList, the parent view manages the reset
  if (!props.mediaList) {
    localLoadedPages.value.clear()
    localRemovedIds.value.clear()
  }

  // Rebuild rows with new count
  buildRows()

  // Load new data - this will populate itemsCache with new items
  // which buildRows() will then reference, swapping content in one frame
  await loadPage(0)

  // Restore scroll position after rebuilding (items may have shifted)
  await nextTick()
  if (scroller.value?.$el && currentScrollTop > 0) {
    scroller.value.$el.scrollTop = currentScrollTop
    // Trigger scroll handler to load pages around restored position
    handleScroll()
  }
})

// Handle bulk auto-marker sync (from folder settings change)
async function handleAutoMarkersSynced() {
  // Get all loaded media IDs
  const mediaIds = []
  for (const [_, item] of itemsCache.value.entries()) {
    if (item && item.id) {
      mediaIds.push(item.id)
    }
  }

  if (mediaIds.length === 0) return

  try {
    // Batch-fetch markers for all loaded items
    const response = await fetch('/api/media/markers/batch-get', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(mediaIds)
    })

    if (response.ok) {
      const markersByMedia = await response.json()

      // Update each item's markers
      for (const item of itemsCache.value) {
        if (item && item.id && markersByMedia[item.id] !== undefined) {
          item.markers = markersByMedia[item.id]
        }
      }

      // Rebuild rows to trigger re-render
      buildRows()
    }
  } catch (err) {
    console.error('Failed to refresh markers after auto-sync:', err)
  }
}

// Handle media updates from WebSocket (unified handler for markers, tags, metadata changes)
function handleMediaUpdated(data) {
  const { media_id, fields, media } = data
  if (!media_id || !media) return

  // If item became superseded (owned by a set/grid), remove it from grid
  if (fields.includes('superseded_by') && media.superseded_by != null) {
    removeItems([media_id])
    return
  }

  // Build the updates object
  const updates = {}
  if (fields.includes('markers')) {
    updates.markers = media.markers || []
  }
  if (fields.includes('tags')) {
    updates.tags = media.tags || []
  }
  if (fields.includes('superseded_by')) {
    updates.superseded_by = media.superseded_by
  }
  if (fields.includes('caption') || fields.includes('prompt') || fields.includes('metadata')) {
    Object.assign(updates, media)
  }
  if (fields.includes('title')) {
    updates.title = media.title
  }
  if ('auto_delete_at' in media) {
    updates.auto_delete_at = media.auto_delete_at
  }

  // Use the shared mediaList's updateItem if available (triggers proper reactivity)
  if (props.mediaList) {
    props.mediaList.updateItem(media_id, updates)
  } else {
    // For local cache, find and update the item, then trigger reactivity
    for (const [index, item] of localItemsCache.value.entries()) {
      if (item && item.id === media_id) {
        const newCache = new Map(localItemsCache.value)
        newCache.set(index, { ...item, ...updates })
        localItemsCache.value = newCache
        break
      }
    }
  }

  // Rebuild rows to trigger re-render
  buildRows()
}

// Handle media deletion from WebSocket
function handleMediaDeleted(data) {
  const { media_id } = data
  if (!media_id) return

  // Use removeItems to properly handle the deletion
  removeItems([media_id])
}

// Handle bulk media deletion from WebSocket (e.g., from auto-delete cleanup)
function handleBulkDeleted(data) {
  const { media_ids } = data
  if (!media_ids || media_ids.length === 0) return

  // Use removeItems to properly handle the deletions
  removeItems(media_ids)
}

// Remove items and shift subsequent items to maintain contiguous indexing
// This is the main method for smooth deletions without full page reload
function removeItems(mediaIds) {
  if (!mediaIds || mediaIds.length === 0) return

  // Notify parent that items are being removed (for selection cleanup)
  emit('items-removed', mediaIds.map(id => parseInt(id)))

  // If using shared mediaList, delegate to it
  if (props.mediaList) {
    props.mediaList.removeItems(mediaIds.map(id => parseInt(id)))
    // Skip the totalCount watcher since we've already handled the removal
    // (parent will sync totalCount after this call)
    skipNextTotalCountWatch.value = true
    previousTotalCount = props.mediaList.totalCount.value
    buildRows()
    return
  }

  // Local logic (when no shared mediaList) - shift indices to maintain contiguity
  const idsToRemove = new Set(mediaIds.map(id => parseInt(id)))

  // Track removed IDs for effectiveTotal calculation
  idsToRemove.forEach(id => localRemovedIds.value.add(id))

  // Single pass: iterate in index order, compact into new cache
  const oldCache = localItemsCache.value
  const newCache = new Map()
  let newIndex = 0
  const maxIndex = oldCache.size > 0 ? Math.max(...oldCache.keys()) : -1
  for (let i = 0; i <= maxIndex; i++) {
    const item = oldCache.get(i)
    if (!item) continue
    if (!idsToRemove.has(item.id)) {
      newCache.set(newIndex++, item)
    }
  }
  localItemsCache.value = newCache

  // Rebuild rows to update display
  buildRows()
}

// Handle auto-delete removal from WebSocket
function handleAutoDeleteRemoved(data) {
  const { media_id } = data
  if (!media_id) return

  // Use updateItem for proper reactivity (shallowRef requires new references)
  if (props.mediaList) {
    props.mediaList.updateItem(media_id, { auto_delete_at: null })
  } else {
    // Local cache: create new Map entry to trigger reactivity
    const newCache = new Map(itemsCache.value)
    for (const [index, item] of newCache.entries()) {
      if (item && item.id === media_id) {
        newCache.set(index, { ...item, auto_delete_at: null })
        break
      }
    }
    localItemsCache.value = newCache
  }

  // Rebuild rows to trigger re-render
  buildRows()
}

// Resize handling
let resizeTimeout
let handleResize
let resizeObserver
let lastObservedWidth = 0
let resizeObserverProcessing = false

// Initialize
onMounted(async () => {
  handleResize = () => {
    // Update immediately for smooth visual feedback
    const changed = calculateItemsPerRow()
    buildRows()

    // Debounce the expensive rebuild operation
    clearTimeout(resizeTimeout)
    if (changed) {
      resizeTimeout = setTimeout(async () => {
        console.log('Items per row changed, rebuilding grid data')
        // Keep old items visible while reloading to prevent flicker
        loadedPages.value.clear()
        buildRows()
        await loadPage(0)
      }, 100)
    }
  }

  window.addEventListener('resize', handleResize)

  // Subscribe to media updates via WebSocket (unified event for markers, tags, metadata)
  unsubscribeMediaUpdated = ws.on('media_updated', handleMediaUpdated)
  unsubscribeMediaDeleted = ws.on('media_deleted', handleMediaDeleted)
  unsubscribeBulkDeleted = ws.on('media_bulk_deleted', handleBulkDeleted)
  unsubscribeAutoDelete = ws.on('auto_delete_removed', handleAutoDeleteRemoved)

  // Listen for bulk auto-marker sync (from folder settings change)
  autoMarkersSyncedHandler = handleAutoMarkersSynced
  window.addEventListener('auto-markers-synced', autoMarkersSyncedHandler)

  // Load initial page
  buildRows()
  await loadPage(0)
  initialLoading.value = false

  // Wait for DOM to be fully rendered before calculating dimensions
  await nextTick()

  // Use ResizeObserver to detect when scroller gets its dimensions
  // This handles initial render AND any subsequent layout changes
  const scrollerEl = scroller.value?.$el
  if (scrollerEl) {
    // Initialize lastObservedWidth to current width to prevent initial duplicate processing
    lastObservedWidth = scrollerEl.clientWidth

    resizeObserver = new ResizeObserver((entries) => {
      // Prevent re-entrant calls (layout changes from buildRows can re-trigger observer)
      if (resizeObserverProcessing) return

      for (const entry of entries) {
        const newWidth = entry.contentRect.width
        // Only process if width actually changed by more than 1px
        if (newWidth > 0 && Math.abs(newWidth - lastObservedWidth) > 1) {
          resizeObserverProcessing = true
          lastObservedWidth = newWidth

          // Scroller now has actual dimensions, calculate grid
          const changed = calculateItemsPerRow()
          buildRows()

          if (changed) {
            // If items per row changed, reload data (keep old items to prevent flicker)
            loadedPages.value.clear()
            buildRows()
            loadPage(0)
          }

          // Reset flag after a short delay to allow layout to settle
          setTimeout(() => {
            resizeObserverProcessing = false
          }, 100)
        }
      }
    })
    resizeObserver.observe(scrollerEl)
  }

  // Fallback: calculate after a short delay if ResizeObserver hasn't fired
  await new Promise(resolve => setTimeout(resolve, 50))
  if (scroller.value?.$el && scroller.value.$el.clientWidth > 0) {
    calculateItemsPerRow()
    buildRows()
  }

  // Trigger scroll handler to load visible pages
  await nextTick()
  handleScroll()

  // After first render, verify our calculations match reality (debugging)
  await nextTick()
  await new Promise(resolve => setTimeout(resolve, 100)) // Wait for render

  if (scrollerEl) {
    const firstRow = scrollerEl.querySelector('.mb-6')

    if (firstRow) {
      const gridContainer = firstRow.querySelector('.grid')
      const firstItem = gridContainer?.querySelector('.grid-cell')

      if (gridContainer && firstItem) {
        console.log('Verification:', {
          'Grid width (actual)': gridContainer.offsetWidth,
          'Grid width (calculated)': scrollerEl.clientWidth - GRID_SIDE_PADDING_PX,
          'Item dimensions (actual)': `${firstItem.offsetWidth}x${firstItem.offsetHeight}`,
          'Item width (calculated)': Math.round((scrollerEl.clientWidth - GRID_SIDE_PADDING_PX - GRID_GAP_PX * (itemsPerRow.value - 1)) / itemsPerRow.value),
          'Row height (actual)': firstRow.offsetHeight,
          'Row height (calculated)': itemHeight.value
        })
      }
    }
  }
})

// Cleanup
onUnmounted(() => {
  if (handleResize) {
    window.removeEventListener('resize', handleResize)
  }
  if (resizeTimeout) {
    clearTimeout(resizeTimeout)
  }
  if (resizeObserver) {
    resizeObserver.disconnect()
  }
  if (unsubscribeMediaUpdated) {
    unsubscribeMediaUpdated()
  }
  if (unsubscribeMediaDeleted) {
    unsubscribeMediaDeleted()
  }
  if (unsubscribeBulkDeleted) {
    unsubscribeBulkDeleted()
  }
  if (unsubscribeAutoDelete) {
    unsubscribeAutoDelete()
  }
  if (autoMarkersSyncedHandler) {
    window.removeEventListener('auto-markers-synced', autoMarkersSyncedHandler)
  }
  // Clean up video refs - pause any playing videos and clear the map
  for (const video of videoRefs.value.values()) {
    if (video) {
      video.pause()
      video.src = ''
    }
  }
  videoRefs.value.clear()
  // Cancel any pending video hover timers
  for (const timerId of videoHoverTimers.values()) {
    clearTimeout(timerId)
  }
  videoHoverTimers.clear()
  // Clear long press timer
  if (longPressTimer.value) {
    clearTimeout(longPressTimer.value)
    longPressTimer.value = null
  }
  // Cancel any pending buildRows RAF
  if (buildRowsRafId !== null) {
    cancelAnimationFrame(buildRowsRafId)
    buildRowsRafId = null
  }
  // Cancel any pending scroll page load RAF
  if (scrollPageLoadRafId !== null) {
    cancelAnimationFrame(scrollPageLoadRafId)
    scrollPageLoadRafId = null
  }
})

// Save scroll position when component is deactivated (navigating away)
onDeactivated(() => {
  if (scroller.value?.$el) {
    const scrollerEl = scroller.value.$el
    const isHidden = scrollerEl.offsetParent === null
    const liveScrollTop = scrollerEl.scrollTop
    // When hidden via v-show, live scroll can read as 0; use last known value.
    const scrollTop = isHidden ? savedScrollPosition.value : liveScrollTop

    // Only save if the element is visible - when hidden via v-show (display:none),
    // scrollTop reads as 0, which would overwrite the real saved position.
    // This happens when slideshow is active and user navigates away.
    if (scrollTop > 0 || !isHidden) {
      savedScrollPosition.value = scrollTop
      saveScrollToStorage(scrollTop)
    }
  }
  // Clear debounce timer
  if (scrollSaveTimer) {
    clearTimeout(scrollSaveTimer)
    scrollSaveTimer = null
  }
})

// Restore scroll position when component is reactivated (navigating back)
onActivated(async () => {
  await nextTick()
  // Prefer sessionStorage (most recently updated) over in-memory value
  const storedScroll = loadScrollFromStorage()
  const scrollToRestore = storedScroll ?? savedScrollPosition.value
  if (scrollToRestore > 0) {
    // If the grid is currently hidden (e.g. slideshow active), just update
    // the in-memory value for later restoration when grid becomes visible.
    if (scroller.value?.$el?.offsetParent !== null) {
      scroller.value.$el.scrollTop = scrollToRestore
      savedScrollPosition.value = scrollToRestore
      await nextTick()
      handleScroll()
    } else {
      savedScrollPosition.value = scrollToRestore
    }
  }
})
</script>

<style scoped>
.grid-cell {
  transition: transform 0.2s, box-shadow 0.2s;
  user-select: none;
  /* Prevent white artifact lines at rounded corners from subpixel rendering */
  -webkit-backface-visibility: hidden;
  backface-visibility: hidden;
  /* Prevent any resize handles or scrollbars from appearing */
  resize: none;
}

/* Hide any scrollbars or resize grips inside grid cells */
.grid-cell *::-webkit-scrollbar,
.grid-cell *::-webkit-scrollbar-corner,
.grid-cell *::-webkit-resizer {
  display: none !important;
  width: 0 !important;
  height: 0 !important;
  background: transparent !important;
}

.grid-cell:hover {
  transform: scale(1.03) translateZ(0);
  box-shadow: 0 4px 10px rgba(0, 0, 0, 0.45);
  z-index: 10;
  position: relative;
}

.grid-cell.multi-select-mode:hover {
  transform: scale(1.015) translateZ(0);
}

/* Allow scaled cards to escape row wrappers in virtual scroller */
:deep(.vue-recycle-scroller__item-wrapper) {
  overflow: visible;
}

/* Keep default rows under hovered rows to avoid overlap clipping */
:deep(.vue-recycle-scroller__item-view) {
  z-index: 0;
}

:deep(.vue-recycle-scroller__item-view:hover) {
  z-index: 20;
}

/* Placeholder skeleton animations */
.grid-cell-placeholder .loading-skeleton {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading-grid .loading-skeleton {
  background: linear-gradient(90deg, var(--color-surface) 25%, var(--color-surface-raised) 50%, var(--color-surface) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
}

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Scrollbar styling - chunky like Google Photos */
.media-grid-container::-webkit-scrollbar {
  -webkit-appearance: none;
  width: 16px;
}

.media-grid-container::-webkit-scrollbar-track {
  background: var(--color-surface-overlay);
  border-left: 1px solid var(--color-border);
}

.media-grid-container::-webkit-scrollbar-thumb {
  background: var(--color-scrollbar-thumb);
  border-radius: 12px;
  border: 4px solid var(--color-surface-overlay);
  min-height: 100px;
}

.media-grid-container::-webkit-scrollbar-thumb:hover {
  background: var(--color-scrollbar-thumb-hover);
}

.media-grid-container::-webkit-scrollbar-thumb:active {
  background: var(--color-scrollbar-thumb-hover);
}


/* Document dog ear effect */
.document-dog-ear {
  width: 0;
  height: 0;
  border-style: solid;
  border-width: 0 24px 24px 0;
  border-color: transparent #9ca3af transparent transparent;
  filter: drop-shadow(-2px 2px 2px rgba(0, 0, 0, 0.3));
}
</style>
