<template>
  <div class="relative w-full h-full flex flex-col bg-base">
    <!-- Slideshow Mode (overlays everything when active) -->
    <SlideshowMode
      v-if="slideshowState.active"
      :total-count="slideshowState.totalCount"
      :start-index="slideshowState.startIndex"
      :media-list="slideshowState.mediaList"
      :page-provider="slideshowState.pageProvider"
      :randomized="slideshowState.randomized"
      :random-seed="slideshowState.randomSeed"
      :inline="true"
      :is-trash-view="isTrashMode"
      @close="exitSlideshow"
      @update:current-media-id="updateCurrentMediaId"
      @compare-with-source="handleCompareFromSlideshow"
    />

    <!-- Compare Mode (overlays everything when active) -->
    <CompareMode
      v-if="compareState.active"
      :left-item="compareState.leftItem"
      :right-item="compareState.rightItem"
      :loading="compareState.loading"
      :error="compareState.error"
      @close="exitCompare"
      @swap="swapCompareImages"
      @action="handleCompareAction"
    />

    <!-- Normal Grid View - hidden but not destroyed when slideshow or compare is active -->
    <div v-show="!slideshowState.active && !compareState.active" class="w-full h-full flex flex-col">

    <!-- Trash Header (only in trash mode) -->
    <div v-if="isTrashMode" class="flex justify-between items-center px-2 py-2 border-b border-edge-subtle">
      <div>
        <h1 class="text-2xl font-semibold text-content">Trash</h1>
        <p class="text-sm text-content-secondary">
          {{ trashHeaderSubtitle }}
        </p>
      </div>
      <div class="flex items-center gap-3">
        <button
          v-if="totalCount > 0"
          class="flex items-center gap-2 px-4 py-2.5 bg-red-500/15 text-red-500 border border-red-500/30 rounded-lg text-sm font-medium hover:bg-red-500/25 hover:border-red-500/50 transition-all disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-red-500/15 disabled:hover:border-red-500/30"
          @click="confirmEmptyTrash"
          :disabled="isEmptyingTrash"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-[18px] h-[18px]">
            <path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
          {{ isEmptyingTrash ? 'Emptying...' : 'Empty Trash' }}
        </button>
        <div v-if="isEmptyingTrash" class="relative w-9 h-9 shrink-0" :title="`${Math.round(trashEmptyProgress * 100)}%`">
          <svg class="w-9 h-9 -rotate-90" viewBox="0 0 36 36">
            <circle cx="18" cy="18" r="15.5" fill="none" stroke="currentColor" stroke-width="3" class="text-white/10" />
            <circle
              cx="18" cy="18" r="15.5" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"
              class="text-red-500 transition-[stroke-dashoffset] duration-300"
              stroke-dasharray="97.39"
              :stroke-dashoffset="97.39 * (1 - trashEmptyProgress)"
            />
          </svg>
          <span class="absolute inset-0 flex items-center justify-center text-[10px] font-medium text-content-secondary">
            {{ Math.round(trashEmptyProgress * 100) }}
          </span>
        </div>
      </div>
    </div>

    <!-- Filter Bar -->
    <FilterBar
      ref="filterBarRef"
      v-model:captionQuery="filters.captionQuery"
      v-model:promptQuery="filters.promptQuery"
      v-model:similarToText="filters.similarToText"
      v-model:mediaTypes="filters.mediaTypes"
      v-model:excludedMediaTypes="filters.excludedMediaTypes"
      v-model:resolutions="filters.resolutions"
      v-model:excludedResolutions="filters.excludedResolutions"
      v-model:sortBy="filters.sortBy"
      v-model:selectedKeywords="filters.selectedKeywords"
      v-model:excludedKeywords="filters.excludedKeywords"
      v-model:selectedFolders="filters.selectedFolders"
      v-model:excludedFolders="filters.excludedFolders"
      v-model:selectedTags="filters.selectedTags"
      v-model:excludedTags="filters.excludedTags"
      v-model:selectedProjects="filters.selectedProjects"
      v-model:excludedProjects="filters.excludedProjects"
      v-model:projectMembership="filters.projectMembership"
      v-model:selectedTools="filters.selectedTools"
      v-model:excludedTools="filters.excludedTools"
      v-model:selectedMarkers="filters.selectedMarkers"
      v-model:excludedMarkers="filters.excludedMarkers"
      v-model:showExpiring="filters.showExpiring"
      v-model:excludeExpiring="filters.excludeExpiring"
      v-model:createdAfter="filters.createdAfter"
      v-model:createdBefore="filters.createdBefore"
      v-model:similarityThreshold="filters.similarityThreshold"
      :totalCount="totalCount"
      :markers="markers"
      :similarSearchActive="similarSearchActive"
      :similarSearchSourceItem="similarSearchSourceItem"
      :similarSearchSourceItems="similarSearchSourceItems"
      :similarTo="filters.similarTo"
      :similarFaceTo="filters.similarFaceTo"
      :savedViewId="savedViewId"
      :savedViewName="savedViewName"
      :isTrashMode="isTrashMode"
      :inProjectScope="projectId != null"
      @update="loadMedia"
      @clear-similar="clearSimilarSearch"
      @shuffle="handleShuffle"
      @save-view="showSaveViewModal = true"
      @delete-view="$emit('delete-view')"
      @rename-view="$emit('rename-view')"
      @move-up="$emit('move-view', 'up')"
      @move-down="$emit('move-view', 'down')"
    />

    <!-- Error state - show when we couldn't load data -->
    <ConnectionError
      v-if="loadError && !loading"
      @retry="loadMedia"
    />

    <!-- Virtual Media Grid -->
    <VirtualMediaGrid
      v-else-if="!initializing && !loading && totalCount > 0"
      ref="virtualGridRef"
      :key="filterKey"
      :total-count="totalCount"
      :media-list="mediaList"
      :page-provider="fetchPageItems"
      :loading="loading"
      :multi-select-mode="multiSelectMode"
      :selected-item-ids="selectedItemIds"
      :is-trash-view="isTrashMode"
      :storage-key="gridStorageKey"
      @item-click="openSlideshow"
      @item-find-similar="searchSimilar"
      @toggle-selection="handleToggleSelection"
      @shift-click-range="handleShiftClickRange"
      @context-menu-action="handleContextMenuAction"
      :in-project="!!projectId"
      :project-id="projectId"
      @empty-space-action="handleEmptySpaceAction"
      @items-removed="removeFromSelection"
    />

    <!-- Empty trash state -->
    <EmptyState
      v-else-if="!loading && !initializing && isTrashMode && totalCount === 0"
      icon="trash"
      title="Trash is empty"
      subtitle="Deleted items will appear here"
    />

    <!-- Empty state for filtered/saved views -->
    <EmptyState
      v-else-if="!loading && !initializing && !isTrashMode && totalCount === 0"
      icon="funnel"
      title="No assets found"
      subtitle="Try adjusting your filters"
    />

    <!-- Loading state when filtering -->
    <div v-if="loading && !initializing" class="flex-1 flex items-center justify-center">
      <div class="text-content-muted">Loading...</div>
    </div>

    <!-- Multi-select action bar -->
    <MultiSelectActionBar
      :visible="multiSelectMode && selectedItemIds.length > 0"
      :selected-count="selectedItemIds.length"
      :total-count="totalCount"
      :markers="markers"
      :active-marker-ids="activeMarkerIds"
      :first-selected-item="selectedItems[0] || null"
      :selected-items="selectedItems"
      :is-trash-view="isTrashMode"
      @clear="selectNone"
      @select-all="selectAll"
      @invert-selection="handleInvertSelection"
      @toggle-marker="handleToggleMarker"
      @add-tags="showTagEditor = true"
      @add-to-board="showBoardPicker = true"
      @find-similar="searchSimilarToSelected"
      @compare="handleCompareSelected"
      @edit-image="handleEditImage"
      @slideshow="startSlideshowFromSelected"
      @download="handleDownload"
      @print="handlePrint"
      @delete="handleMoveToTrash"
      @restore="handleBulkRestore"
      @delete-permanently="handleBulkPermanentDelete"
    />

    <!-- Board Picker Modal -->
    <BoardPicker
      :visible="showBoardPicker"
      :asset-ids="selectedItemIds"
      @close="showBoardPicker = false"
      @saved="handleBoardsAdded"
    />

    <!-- Export Modal -->
    <ExportModal
      :show="showExportModal"
      :media-ids="exportMediaIds"
      :media-items="exportMediaItems"
      @close="showExportModal = false"
    />

    <!-- Tag Editor Modal -->
    <BulkTagEditor
      :visible="showTagEditor"
      :asset-ids="selectedItemIds"
      :current-tag-counts="currentTagCounts"
      :selected-items="selectedItems"
      @close="showTagEditor = false"
      @saved="handleTagsSaved"
    />

    <!-- Save View Modal -->
    <SaveViewModal
      :visible="showSaveViewModal"
      :filters="{ ...filters }"
      :sort-by="filters.sortBy"
      @close="showSaveViewModal = false"
    />

    <!-- Confirm permanent delete modal (trash mode) -->
    <DeleteConfirmModal
      :visible="showDeleteConfirm"
      title="Permanently Delete?"
      :message="permanentDeleteMessage"
      confirm-text="Delete Permanently"
      @close="showDeleteConfirm = false"
      @confirm="permanentDelete"
    />

    <!-- Confirm empty trash modal (trash mode) -->
    <DeleteConfirmModal
      :visible="showEmptyTrashConfirm"
      title="Empty Trash?"
      message="This will permanently delete all items in trash. This action cannot be undone."
      confirm-text="Empty Trash"
      :count="totalCount"
      :count-message="`This will permanently delete ${totalCount} ${totalCount === 1 ? 'item' : 'items'}.`"
      @close="showEmptyTrashConfirm = false"
      @confirm="emptyTrash"
    />
    <!-- Upload FAB (only in browse mode, not trash) -->
    <button
      v-if="!isTrashMode"
      class="fixed right-6 bottom-6 w-14 h-14 rounded-full shadow-lg hover:shadow-xl transition-all flex items-center justify-center z-[101] bg-blue-600 hover:bg-blue-700 text-white"
      @click="goToUpload"
      title="Upload assets"
    >
      <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
      </svg>
    </button>
    </div>
    <!-- End of grid view wrapper -->
  </div>
</template>

<script setup>
// Component name for KeepAlive
defineOptions({
  name: 'BrowseGridView'
})
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import FilterBar from '../components/FilterBar.vue'
import VirtualMediaGrid from '../components/VirtualMediaGrid.vue'
import MultiSelectActionBar from '../components/MultiSelectActionBar.vue'
import BoardPicker from '../components/BoardPicker.vue'
import ExportModal from '../components/ExportModal.vue'
import BulkTagEditor from '../components/BulkTagEditor.vue'
import SlideshowMode from '../components/SlideshowMode.vue'
import CompareMode from '../components/CompareMode.vue'
import SaveViewModal from '../components/SaveViewModal.vue'
import ConnectionError from '../components/ConnectionError.vue'
import DeleteConfirmModal from '../components/DeleteConfirmModal.vue'
import EmptyState from '../components/EmptyState.vue'
import { useMediaApi } from '../composables/useMediaApi'
import { useAssetApi } from '../composables/useAssetApi'
import { useCompare } from '../composables/useCompare'
import { useWebSocket } from '../composables/useWebSocket'
import { useGlobalKeyboardShortcuts } from '../composables/useGlobalKeyboardShortcuts'
import { useBrowseFilters } from '../composables/useBrowseFilters'
import { useSlideshow } from '../composables/useSlideshow'
import { useTabNavigation } from '../composables/useTabNavigation'
import { useMultiSelect } from '../composables/useMultiSelect'
import { useVirtualGrid } from '../composables/useVirtualGrid'
import { useUrlState } from '../composables/useUrlState'
import { usePrint } from '../composables/usePrint'
import { useDeleteOperations } from '../composables/useDeleteOperations'
import { addToast } from '../composables/useToasts'
import { getCurrentProfileId } from '../composables/useProfile'
import { makeProfileKey } from '../utils/storageKeys'
import { useMediaList } from '../composables/useMediaList'
import { isSettingsLoaded } from '../appConfig'
import { useWorkspaceTabs } from '../composables/useWorkspaceTabs'
import { cloneDefaultBrowseFilters, normalizeBrowseFilters } from '../constants/browseFilters'
import { assetIdOf, mediaIdOf } from '../utils/assetIdentity'

// Props
const props = defineProps({
  isTrashMode: {
    type: Boolean,
    default: false
  },
  sidebarCollapsed: {
    type: Boolean,
    default: false
  },
  // External filter injection - when provided, use these instead of global state
  filterState: {
    type: Object,
    default: null
  },
  // External similar search state injection
  similarSearchState: {
    type: Object,
    default: null
  },
  // Saved view props - enables saved view controls in FilterBar
  savedViewId: {
    type: Number,
    default: null
  },
  savedViewName: {
    type: String,
    default: null
  },
  projectId: {
    type: Number,
    default: null
  }
})

// Emit events for filter changes when using external state, and saved view actions
const emit = defineEmits([
  'filter-change',
  'similar-search-cleared',
  'delete-view',
  'rename-view',
  'move-view'
])

// Computed for template usage
const isTrashMode = computed(() => props.isTrashMode)
const savedViewId = computed(() => props.savedViewId)
const savedViewName = computed(() => props.savedViewName)
const { activeDeleteOperation } = useDeleteOperations()
const isEmptyingTrash = computed(() => {
  const op = activeDeleteOperation.value
  return props.isTrashMode && op?.kind === 'empty_trash' && ['queued', 'running'].includes(op.status)
})
const trashHeaderSubtitle = computed(() => {
  if (isEmptyingTrash.value) {
    const op = activeDeleteOperation.value
    return `Emptying trash: ${op?.processed_items || 0} / ${op?.total_items || totalCount.value}`
  }
  return `${totalCount.value} deleted ${totalCount.value === 1 ? 'item' : 'items'}`
})
const trashEmptyProgress = computed(() => {
  const op = activeDeleteOperation.value
  const total = op?.total_items || totalCount.value || 0
  if (!total) return 0
  return Math.min(1, (op?.processed_items || 0) / total)
})

const route = useRoute()
const router = useRouter()
const { nextEditorId } = useWorkspaceTabs()
const { decodeFiltersFromUrl } = useUrlState()
const {
  getMediaItem: getPayloadMediaItem,
  getMarkers,
  downloadMedia,
  getThumbnailUrl
} = useMediaApi()
const {
  fetchAssets: fetchMedia,
  fetchAssetIds: fetchMediaIds,
  getAssetBrowserItem,
  findAssetIndex: findMediaIndex,
  bulkMarker: bulkMarkerOperation,
  trashMany: bulkDeleteMedia,
  restore: restoreFromTrash,
  restoreMany: bulkRestoreFromTrash,
  permanentlyDelete: permanentlyDeleteMedia,
  permanentlyDeleteMany: bulkPermanentlyDelete,
  emptyTrash: apiEmptyTrash,
  getDeletionPreview,
} = useAssetApi()

const getMediaItem = (assetId, options = {}) => (
  getAssetBrowserItem(assetId, options.includeTrashed === true)
)

// Determine if we're using external filter state (for SavedViewPage) or global state
// This is determined once at setup time - external filters won't toggle during component lifetime
const useExternalFilters = props.filterState !== null
const globalFilterScope = props.isTrashMode ? 'trash' : 'browse'

// Global filter state - always available but only used when external filters not provided
const globalFilterState = useBrowseFilters(globalFilterScope)

// Filters - use external when provided, otherwise global
// This is a reactive object that v-model can write to
const filters = props.filterState ?? globalFilterState.filters

// Similar search state - use external refs when provided, otherwise global
// These must be refs for reactivity in the template
const similarSearchActive = props.similarSearchState?.active ?? globalFilterState.similarSearchActive
const similarSearchSourceItem = props.similarSearchState?.sourceItem ?? globalFilterState.similarSearchSourceItem
const similarSearchSourceItems = props.similarSearchState?.sourceItems ?? globalFilterState.similarSearchSourceItems

// Filter change counter - only relevant for global state
const filterChangeCounter = computed(() => globalFilterState.filterChangeCounter.value)

function setSimilarSearch(ids) {
  if (useExternalFilters) {
    filters.similarTo = Array.isArray(ids) ? ids : [ids]
    filters.similarFaceTo = []
    filters.similarToText = ''
    filters.sortBy = 'similarity'
    if (similarSearchActive) {
      similarSearchActive.value = true
    }
  } else {
    globalFilterState.setSimilarSearch(ids)
  }
}

function setSimilarFaceSearch(ids) {
  if (useExternalFilters) {
    filters.similarFaceTo = Array.isArray(ids) ? ids : [ids]
    filters.similarTo = []
    filters.similarToText = ''
    filters.sortBy = 'similarity'
    if (similarSearchActive) {
      similarSearchActive.value = true
    }
  } else {
    globalFilterState.setSimilarFaceSearch(ids)
  }
}

async function setSimilarFilter(mediaId) {
  if (useExternalFilters) {
    // For external filters, just set the filter directly
    const item = await getPayloadMediaItem(mediaId)
    filters.similarTo = [mediaId]
    filters.similarFaceTo = []
    filters.similarToText = ''
    filters.sortBy = 'similarity'
    if (similarSearchActive) {
      similarSearchActive.value = true
      similarSearchSourceItem.value = item
      similarSearchSourceItems.value = [item]
    }
  } else {
    await globalFilterState.setSimilarFilter(mediaId)
  }
}

async function setSimilarFaceFilter(mediaId) {
  if (useExternalFilters) {
    const item = await getPayloadMediaItem(mediaId)
    filters.similarFaceTo = [mediaId]
    filters.similarTo = []
    filters.similarToText = ''
    filters.sortBy = 'similarity'
    if (similarSearchActive) {
      similarSearchActive.value = true
      similarSearchSourceItem.value = item
      similarSearchSourceItems.value = [item]
    }
  } else {
    await globalFilterState.setSimilarFaceFilter(mediaId)
  }
}

function clearSimilarSearch() {
  if (useExternalFilters) {
    if (similarSearchActive) {
      similarSearchActive.value = false
      similarSearchSourceItem.value = null
      similarSearchSourceItems.value = []
    }
    filters.similarTo = []
    filters.similarFaceTo = []
    filters.similarToText = ''
    if (filters.sortBy === 'similarity') {
      filters.sortBy = 'created_desc'
    }
    clearSimilarityRouteQuery()
    emit('similar-search-cleared')
    loadMedia()
  } else {
    globalFilterState.clearSimilarSearch()
    clearSimilarityRouteQuery()
  }
}

// WebSocket for live updates
const { on: wsOn, connected: wsConnected } = useWebSocket()
const wsUnsubscribers = []

// Slideshow composable
const { slideshowState, enterSlideshow: enterSlideshowBase, exitSlideshow: exitSlideshowBase, updateCurrentMediaId } = useSlideshow()
const { enterSlideshowMode, exitSlideshowMode } = useTabNavigation()

// Wrap enterSlideshow to notify tab navigation (so parent views like SavedViewPage can react)
function enterSlideshow(params) {
  enterSlideshowBase(params)
  enterSlideshowMode()
}

// Compare composable
const { compareState, enterCompare, exitCompare, swapImages: swapCompareImages } = useCompare()

// Shared media list - single source of truth for both grid and slideshow
// This is declared early but initialized after buildFilterParams is defined
let mediaList = null

// Wrap exitSlideshow to add view-specific logic
async function exitSlideshow() {
  // Clear pending reload - this is typically set spuriously by the route watcher
  // firing during KeepAlive reactivation, not because data actually changed.
  // Real-time data updates are handled by WebSocket via softReloadMedia.
  pendingReload.value = false

  exitSlideshowBase()
  exitSlideshowMode()

  await nextTick()

  // Restore scroll position - the grid was hidden (v-show) during slideshow,
  // so scroll position may not have been properly maintained during
  // KeepAlive deactivate/reactivate.
  if (virtualGridRef.value) {
    virtualGridRef.value.restoreScrollPosition()
  }

  // Refresh tags in case they were edited during slideshow
  if (filterBarRef.value) {
    filterBarRef.value.refreshTags()
  }
}

// State
const loading = ref(false)
const loadError = ref(false)
const totalCount = ref(0)
const filterKey = ref(0)
const randomSeed = ref(Date.now())
const initializing = ref(true)
const pendingReload = ref(false)  // Track if reload was deferred during slideshow
const loadRequestId = ref(0)

// Library management state
const markers = ref([])
const showBoardPicker = ref(false)
const showExportModal = ref(false)
const exportMediaIds = ref([])
const exportMediaItems = ref([])
const showTagEditor = ref(false)
const showSaveViewModal = ref(false)

// Trash mode state
const showDeleteConfirm = ref(false)
const showEmptyTrashConfirm = ref(false)
const itemToDelete = ref(null)
const deletionPreviews = ref([])
const deletionPreviewLoading = ref(false)
const permanentDeleteMessage = computed(() => {
  const count = itemToDelete.value?.length || 0
  if (deletionPreviewLoading.value) return 'Checking versions and other content that still uses this media…'
  if (!deletionPreviews.value.length) {
    return count > 1
      ? `This will permanently delete ${count} assets and their version history. This action cannot be undone.`
      : 'This will permanently delete this asset and its version history. This action cannot be undone.'
  }
  const versions = deletionPreviews.value.reduce((sum, item) => sum + item.revision_count, 0)
  const collectible = deletionPreviews.value.reduce((sum, item) => sum + item.collectible_media_ids.length, 0)
  const retained = deletionPreviews.value.reduce((sum, item) => sum + item.retained_media_ids.length, 0)
  const subject = count === 1 ? 'this asset' : `${count} assets`
  const retainedText = retained
    ? ` ${retained} media ${retained === 1 ? 'payload is' : 'payloads are'} also used by other content and will remain.`
    : ''
  return `This permanently removes ${subject} and ${versions} saved ${versions === 1 ? 'version' : 'versions'}. ${collectible} unreferenced media ${collectible === 1 ? 'payload' : 'payloads'} will be securely deleted.${retainedText} This action cannot be undone.`
})

// Get profile-specific localStorage key for filters
function getFiltersStorageKey() {
  return makeProfileKey(globalFilterScope, 'filters')
}

// Load saved filters from localStorage or use defaults
function loadSavedFilters() {
  try {
    const saved = localStorage.getItem(getFiltersStorageKey())
    if (saved) {
      const parsed = JSON.parse(saved)
      return normalizeBrowseFilters(parsed)
    }
  } catch (error) {
    console.error('Failed to load saved filters:', error)
  }
  return cloneDefaultBrowseFilters()
}

// Load saved filters into global state ONLY if:
// 1. We're not using external filters
// 2. Filters are still at defaults (don't overwrite filters that were set via navigation)
const isFiltersAtDefaults = () => {
  return JSON.stringify(normalizeBrowseFilters(filters)) === JSON.stringify(cloneDefaultBrowseFilters())
}

// Only load from localStorage when using global filters
if (!useExternalFilters && isFiltersAtDefaults()) {
  const savedFilters = loadSavedFilters()
  if (savedFilters) {
    Object.assign(filters, savedFilters)

    // If filters have similarity IDs but similarSearchActive is false, it's a stuck filter
    // Clear it to avoid being stuck with invisible similar search
    const hasSavedSimilarityIds =
      (filters.similarTo && filters.similarTo.length > 0) ||
      (filters.similarFaceTo && filters.similarFaceTo.length > 0)
    if (hasSavedSimilarityIds && !similarSearchActive.value) {
      console.warn('[BrowseGridView] Detected stuck similar filter, clearing it')
      filters.similarTo = []
      filters.similarFaceTo = []
      if (filters.sortBy === 'similarity') {
        filters.sortBy = 'created_desc'
      }
    }
  }
}

// Similar search state is now global (from useBrowseFilters)

// Save filters to localStorage whenever they change (profile-specific)
// Skip when using external filters (e.g., SavedViewPage manages its own state)
watch(filters, (newFilters) => {
  if (initializing.value || useExternalFilters) return
  try {
    localStorage.setItem(getFiltersStorageKey(), JSON.stringify(newFilters))
  } catch (error) {
    console.error('Failed to save filters:', error)
  }
}, { deep: true })

// Watch for external filter changes (e.g., saved view switching)
// When external filters are provided, reload media when they change
if (useExternalFilters) {
  let lastFilterSnapshot = JSON.stringify(filters)
  watch(filters, async () => {
    if (!initializing.value) {
      // Deep watchers can fire spuriously during KeepAlive reactivation
      // without actual value changes. Compare snapshots to avoid unnecessary reloads.
      const snapshot = JSON.stringify(filters)
      if (snapshot === lastFilterSnapshot) return
      lastFilterSnapshot = snapshot
      await loadMedia()
    }
  }, { deep: true })
}

// Save similar search state when it changes (profile-specific)
// Skip when using external filters
watch([similarSearchActive, similarSearchSourceItem, similarSearchSourceItems], () => {
  if (initializing.value || useExternalFilters) return
  try {
    localStorage.setItem(makeProfileKey(globalFilterScope, 'similar_search'), JSON.stringify({
      active: similarSearchActive.value,
      sourceItem: similarSearchSourceItem.value,
      sourceItems: similarSearchSourceItems.value
    }))
  } catch (error) {
    console.error('Failed to save similar search state:', error)
  }
}, { deep: true })

const virtualGridRef = ref(null)
const filterBarRef = ref(null)
const gridStorageKey = computed(() => {
  if (props.isTrashMode) return 'trash'
  if (props.savedViewId) return `saved-view-${props.savedViewId}`
  // Project assets get their own scroll memory, separate from global browse and
  // from each other, so returning to a project's Assets restores its scroll.
  if (props.projectId != null) return `project-${props.projectId}`
  return 'browse'
})

// Multi-select composable
const {
  multiSelectMode,
  selectedItemIds,
  selectingAll,
  toggleMultiSelectMode,
  handleToggleSelection,
  handleShiftClickRange,
  selectAll,
  selectNone,
  removeFromSelection,
  activeMarkerIds,
  selectedItems,
  currentTagCounts,
  createKeyboardHandler
} = useMultiSelect({
  fetchAllIds: async () => {
    const params = props.isTrashMode ? buildTrashFilterParams() : buildFilterParams()
    params.state = props.isTrashMode ? 'trashed' : 'active'
    const response = await fetchMediaIds(params)
    return response.ids || []
  },
  getItemsByIds: (ids) => virtualGridRef.value?.getItemsByIds(ids) || [],
  markers
})

// Global keyboard shortcuts - setup after composables are initialized
const multiSelectKeyHandler = createKeyboardHandler()

useGlobalKeyboardShortcuts({
  onKeydown: (event) => {
    // Priority 1: Close slideshow if active
    if (slideshowState.active && event.key === 'Escape') {
      exitSlideshow()
      return
    }

    // Priority 2: Multi-select keyboard shortcuts
    if (multiSelectKeyHandler(event)) {
      return  // Handled by multi-select composable
    }

    // Priority 3: Delete key to trash/permanently delete selected items
    if ((event.key === 'Delete' || event.key === 'Backspace') && multiSelectMode.value && selectedItemIds.value.length > 0) {
      event.preventDefault()
      if (props.isTrashMode) {
        handleBulkPermanentDelete()
      } else {
        handleMoveToTrash()
      }
      return
    }

    // Priority 4: Cmd/Ctrl+Enter to open context menu for selected item(s)
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter' && selectedItemIds.value.length > 0) {
      event.preventDefault()
      // Show context menu for the first selected item
      const firstSelectedId = selectedItemIds.value[0]
      virtualGridRef.value?.showContextMenuForItem(firstSelectedId)
      return
    }
  }
})

// Build filter params for API calls
function buildFilterParams() {
  const params = {
    caption_query: filters.captionQuery || undefined,
    prompt_query: filters.promptQuery || undefined,
    sort_by: filters.sortBy,
    random_seed: filters.sortBy === 'random' ? randomSeed.value : undefined,
  }
  if (props.projectId != null) {
    params.project_id = props.projectId
  }

  if (filters.mediaTypes && filters.mediaTypes.length > 0) {
    params.media_types = filters.mediaTypes.join(',')
  }
  if (filters.excludedMediaTypes && filters.excludedMediaTypes.length > 0) {
    params.excluded_media_types = filters.excludedMediaTypes.join(',')
  }
  if (filters.resolutions && filters.resolutions.length > 0) {
    params.resolutions = filters.resolutions.join(',')
  }
  if (filters.excludedResolutions && filters.excludedResolutions.length > 0) {
    params.excluded_resolutions = filters.excludedResolutions.join(',')
  }
  if (filters.selectedKeywords && filters.selectedKeywords.length > 0) {
    params.keywords = filters.selectedKeywords.join(',')
  }
  if (filters.excludedKeywords && filters.excludedKeywords.length > 0) {
    params.excluded_keywords = filters.excludedKeywords.join(',')
  }
  if (filters.selectedFolders && filters.selectedFolders.length > 0) {
    params.folders = filters.selectedFolders.join(',')
  }
  if (filters.excludedFolders && filters.excludedFolders.length > 0) {
    params.excluded_folders = filters.excludedFolders.join(',')
  }
  if (filters.selectedMarkers && filters.selectedMarkers.length > 0) {
    params.marker_ids = filters.selectedMarkers.join(',')
  }
  if (filters.excludedMarkers && filters.excludedMarkers.length > 0) {
    params.excluded_marker_ids = filters.excludedMarkers.join(',')
  }
  if (filters.selectedTags && filters.selectedTags.length > 0) {
    params.tag_ids = filters.selectedTags.join(',')
  }
  if (filters.excludedTags && filters.excludedTags.length > 0) {
    params.excluded_tag_ids = filters.excludedTags.join(',')
  }
  // Project-membership filter only applies to library-wide views. Inside a single project the
  // route's project_id is the scoping authority, and the column is hidden — don't let leftover
  // values from the shared global browse state leak in and contradict it.
  if (props.projectId == null) {
    if (filters.selectedProjects && filters.selectedProjects.length > 0) {
      params.project_ids = filters.selectedProjects.join(',')
    }
    if (filters.excludedProjects && filters.excludedProjects.length > 0) {
      params.excluded_project_ids = filters.excludedProjects.join(',')
    }
    if (filters.projectMembership === 'any') {
      params.has_project = true
    } else if (filters.projectMembership === 'none') {
      params.has_project = false
    }
  }
  if (filters.selectedTools && filters.selectedTools.length > 0) {
    params.tool_ids = filters.selectedTools.join(',')
  }
  if (filters.excludedTools && filters.excludedTools.length > 0) {
    params.excluded_tool_ids = filters.excludedTools.join(',')
  }
  if (filters.similarTo && filters.similarTo.length > 0) {
    params.similar_to = filters.similarTo.join(',')
    // Use backend default threshold (0.75) from config
  }
  if (filters.similarFaceTo && filters.similarFaceTo.length > 0) {
    params.similar_face_to = filters.similarFaceTo.join(',')
    // Use backend default face threshold; face scores are on a different scale than CLIP
  }
  if (filters.similarToText && filters.similarToText.trim()) {
    params.similar_to_text = filters.similarToText.trim()
    // Don't send similarity_threshold for text search - let backend use its text-specific default (0.20)
    // Text-to-image CLIP scores are typically 0.2-0.4, much lower than image-to-image scores
  }
  if (filters.createdAfter) {
    params.created_after = filters.createdAfter
  }
  if (filters.createdBefore) {
    params.created_before = filters.createdBefore
  }
  if (filters.showExpiring) {
    params.show_expiring = true
  }
  if (filters.excludeExpiring) {
    params.exclude_expiring = true
  }
  return params
}

// Wrapper function that calls the appropriate API based on mode
async function fetchMediaForMode(params) {
  return await fetchMedia({
    ...params,
    state: props.isTrashMode ? 'trashed' : 'active'
  })
}

// Build filter params for trash mode - mirrors buildFilterParams() for applicable filters
function buildTrashFilterParams() {
  const params = {}
  if (props.projectId != null) {
    params.project_id = props.projectId
  }

  // Text filters
  if (filters.captionQuery) params.caption_query = filters.captionQuery
  if (filters.promptQuery) params.prompt_query = filters.promptQuery

  // Similarity search (CLIP text-based)
  if (filters.similarToText) {
    params.similar_to_text = filters.similarToText
    if (filters.similarityThreshold) {
      params.similarity_threshold = filters.similarityThreshold
    }
  }

  // Media type filter (OR logic)
  if (filters.mediaTypes?.length > 0) {
    params.media_types = filters.mediaTypes.join(',')
  }
  if (filters.excludedMediaTypes?.length > 0) {
    params.excluded_media_types = filters.excludedMediaTypes.join(',')
  }

  // Resolution filter (OR logic)
  if (filters.resolutions?.length > 0) {
    params.resolutions = filters.resolutions.join(',')
  }
  if (filters.excludedResolutions?.length > 0) {
    params.excluded_resolutions = filters.excludedResolutions.join(',')
  }

  // Keyword filter (AND logic)
  if (filters.selectedKeywords?.length > 0) {
    params.keywords = filters.selectedKeywords.join(',')
  }
  if (filters.excludedKeywords?.length > 0) {
    params.excluded_keywords = filters.excludedKeywords.join(',')
  }

  // Folder filters
  if (filters.selectedFolders?.length > 0) {
    params.folders = filters.selectedFolders.join(',')
  }
  if (filters.excludedFolders?.length > 0) {
    params.excluded_folders = filters.excludedFolders.join(',')
  }

  // Marker filter
  if (filters.selectedMarkers?.length > 0) {
    params.marker_ids = filters.selectedMarkers.join(',')
  }
  if (filters.excludedMarkers?.length > 0) {
    params.excluded_marker_ids = filters.excludedMarkers.join(',')
  }

  // Tag filter
  if (filters.selectedTags?.length > 0) {
    params.tag_ids = filters.selectedTags.join(',')
  }
  if (filters.excludedTags?.length > 0) {
    params.excluded_tag_ids = filters.excludedTags.join(',')
  }

  // Tool lineage filter
  if (filters.selectedTools?.length > 0) {
    params.tool_ids = filters.selectedTools.join(',')
  }
  if (filters.excludedTools?.length > 0) {
    params.excluded_tool_ids = filters.excludedTools.join(',')
  }

  // Date filters
  if (filters.createdAfter) params.created_after = filters.createdAfter
  if (filters.createdBefore) params.created_before = filters.createdBefore

  // Sorting: use similarity when search is active, otherwise deleted date
  if (filters.similarToText) {
    params.sort_by = 'similarity'
  } else {
    params.sort_by = 'deleted_desc'
  }

  // Include hidden items
  return params
}

// Initialize shared media list now that buildFilterParams is defined
mediaList = useMediaList({
  fetchMedia: fetchMediaForMode,
  buildFilterParams: () => props.isTrashMode ? buildTrashFilterParams() : buildFilterParams(),
  gridPageSize: 200,
  slideshowPageSize: 50
})

async function fetchPageItems(pageNumber, pageSize) {
  if (props.isTrashMode) {
    const params = buildTrashFilterParams()
    const response = await fetchMedia({
      ...params,
      state: 'trashed',
      page: pageNumber + 1,
      page_size: pageSize
    })
    return response.items
  } else {
    const params = buildFilterParams()
    const response = await fetchMedia({
      ...params,
      page: pageNumber + 1,
      page_size: pageSize
    })
    return response.items
  }
}

async function loadMedia(options = {}) {
  const { force = false } = options

  // Defer reload if slideshow is active (unless forced)
  // This prevents the underlying data from being yanked while viewing
  if (slideshowState.active && !force) {
    pendingReload.value = true
    return
  }

  const requestId = ++loadRequestId.value
  loading.value = true
  loadError.value = false
  pendingReload.value = false
  try {
    const params = props.isTrashMode ? buildTrashFilterParams() : buildFilterParams()

    // Reset the shared media list with new filter params
    mediaList.reset(params)

    const response = await fetchMediaForMode({
      ...params,
      page: 1,
      page_size: 1
    })
    if (requestId !== loadRequestId.value) return
    totalCount.value = response.total

    // In browse mode, filter selected items to only those visible with current filters
    if (!props.isTrashMode && selectedItemIds.value.length > 0) {
      const idsResponse = await fetchMediaIds(params)
      if (requestId !== loadRequestId.value) return
      const visibleIds = new Set(idsResponse.ids || [])
      selectedItemIds.value = selectedItemIds.value.filter(id => visibleIds.has(id))
      if (selectedItemIds.value.length === 0) {
        multiSelectMode.value = false
      }
    }

    filterKey.value++
  } catch (error) {
    if (requestId !== loadRequestId.value) return
    console.error('Failed to update filters:', error)
    loadError.value = true
  } finally {
    if (requestId === loadRequestId.value) {
      loading.value = false
    }
  }
}

// Authoritative, idempotent reconcile after items left the current view
// server-side (move-to-trash, restore-from-trash, permanent delete). Drops the
// known-removed items from the cache for an immediate visual update, then syncs
// the count to the server's authoritative total. Safe to call from both the
// optimistic action and its websocket echo (and another client's echo): the
// cache drop is a no-op for already-removed items and the count is set
// absolutely, so nothing double-counts. The grid's totalCount watcher reloads
// the visible region (at the clamped scroll position) for large changes.
//
// This replaces the old `virtualGridRef.removeItems(ids)` + manual totalCount
// decrement, which ran twice (optimistically and on the echo) and could drive
// the total to 0 — blanking the grid / leaving unresolved spinners on large or
// cascading deletes.
async function reconcileRemoval(removedIds) {
  if (!mediaList) return
  if (removedIds?.length) {
    mediaList.removeFromCache(removedIds.map(id => parseInt(id)))
  }
  // silentReload sets the absolute server total and clears stale page tracking.
  await mediaList.silentReload()
  totalCount.value = mediaList.totalCount.value
  // The virtual scroller doesn't recompute its geometry on a count shrink until
  // it sees a scroll event, so explicitly rebuild + reload the visible region.
  await virtualGridRef.value?.refreshAfterRemoval?.()
}

// Soft reload - updates data without showing loading state or unmounting the grid
// Used for live updates (websocket events) where we want seamless visual updates
async function softReloadMedia() {
  if (mediaList) {
    // Use shared mediaList's silentReload which properly invalidates the cache
    // and triggers grid rebuild via cacheVersion
    // Note: Don't manually update totalCount.value here - the grid uses
    // mediaList.effectiveTotal for display, and updating totalCount would
    // trigger the grid's watcher causing a redundant reload/blink
    await mediaList.silentReload()
  }
}

async function searchSimilar(mediaIds) {
  try {
    const assetIds = Array.isArray(mediaIds) ? mediaIds : [mediaIds]
    if (assetIds.length === 0 || assetIds.length > 3) {
      console.error('Invalid number of reference IDs (must be 1-3):', assetIds.length)
      return
    }
    const items = await Promise.all(assetIds.map(id => getMediaItem(id)))
    const ids = items.map(mediaIdOf).filter(Boolean)

    // For single item, use the global setSimilarFilter
    if (ids.length === 1) {
      await setSimilarFilter(ids[0])
    } else {
      similarSearchSourceItems.value = items
      similarSearchSourceItem.value = items[0]
      setSimilarSearch(ids)
    }

    await loadMedia()

    await nextTick()
    virtualGridRef.value?.scrollToTop?.()
  } catch (error) {
    console.error('Failed to search similar:', error)
  }
}

async function searchSimilarFaces(mediaIds) {
  try {
    const assetIds = Array.isArray(mediaIds) ? mediaIds : [mediaIds]
    if (assetIds.length === 0 || assetIds.length > 3) {
      console.error('Invalid number of reference IDs (must be 1-3):', assetIds.length)
      return
    }
    const items = await Promise.all(assetIds.map(id => getMediaItem(id)))
    const ids = items.map(mediaIdOf).filter(Boolean)

    if (ids.length === 1) {
      await setSimilarFaceFilter(ids[0])
    } else {
      similarSearchSourceItems.value = items
      similarSearchSourceItem.value = items[0]
      setSimilarFaceSearch(ids)
    }

    await loadMedia()

    await nextTick()
    virtualGridRef.value?.scrollToTop?.()
  } catch (error) {
    console.error('Failed to search similar faces:', error)
    addToast(error.response?.data?.detail || 'Failed to search similar faces', 'error')
  }
}

// Multi-select helper - search similar to selected items
function searchSimilarToSelected() {
  if (selectedItemIds.value.length >= 1 && selectedItemIds.value.length <= 3) {
    searchSimilar(selectedItemIds.value)
    multiSelectMode.value = false
    selectedItemIds.value = []
  }
}

// Multi-select helper - invert selection
async function handleInvertSelection() {
  try {
    // Fetch all IDs with current filters
    const params = buildFilterParams()
    const response = await fetchMediaIds(params)
    const allIds = response.ids || []

    // Create a Set of currently selected IDs for fast lookup
    const selectedSet = new Set(selectedItemIds.value)

    // Invert: select all IDs that are NOT currently selected
    const invertedIds = allIds.filter(id => !selectedSet.has(id))

    // Update selection
    selectedItemIds.value = invertedIds

    // If nothing is selected after invert, exit multi-select mode
    if (invertedIds.length === 0) {
      multiSelectMode.value = false
    }
  } catch (error) {
    console.error('Failed to invert selection:', error)
  }
}

// Multi-select helper - compare two selected images
function handleCompareSelected() {
  if (selectedItemIds.value.length === 2) {
    enterCompare({
      leftMediaId: selectedItemIds.value[0],
      rightMediaId: selectedItemIds.value[1]
    })
    multiSelectMode.value = false
    selectedItemIds.value = []
  }
}

// Multi-select helper - edit selected image
function handleEditImage() {
  if (selectedItemIds.value.length === 1) {
    router.push({ name: 'edit-image', params: { editorId: nextEditorId(), mediaId: selectedItemIds.value[0] } })
    multiSelectMode.value = false
    selectedItemIds.value = []
  }
}

// Handle compare from context menu (custom event)
function handleCompareFromContextMenu(event) {
  const { leftMediaId, rightMediaId } = event.detail
  enterCompare({ leftMediaId, rightMediaId })
}

// Handle compare from slideshow (source image compare)
async function handleCompareFromSlideshow({ leftMediaId, rightMediaId }) {
  console.log('[BrowseGridView] handleCompareFromSlideshow called with:', { leftMediaId, rightMediaId })
  // Don't exit slideshow - keep it active so we return to it when compare closes
  // Compare mode will overlay on top (higher z-index)
  await enterCompare({ leftMediaId, rightMediaId, returnTo: 'slideshow' })
  console.log('[BrowseGridView] enterCompare finished, compareState:', compareState)
}

// Handle action from compare mode - execute the action on the specified item
async function handleCompareAction({ action, item, payload }) {
  if (!item) return

  switch (action) {
    case 'find-similar':
      await searchSimilar(item.id)
      break
    case 'delete':
      await handleMoveToTrash([item.id])
      break
    case 'filter-by-tag':
      if (payload) {
        addTagFilter(payload)
      }
      break
    case 'filter-by-keyword':
      if (payload) {
        addKeywordFilter(payload)
      }
      break
    case 'navigate-to-board':
      if (payload) {
        router.push({ name: 'board-detail', params: { id: payload } })
      }
      break
    case 'navigate-to-source-media':
      if (payload) {
        openSlideshow(payload)
      }
      break
    case 'compare-with-source':
      // payload is the sourceMediaId, item is the current item
      // Re-enter compare with source as left (before) and current as right (after)
      if (payload) {
        enterCompare({ leftMediaId: payload, rightMediaId: item.id })
      }
      break
    case 'download':
      await handleDownload([item.id])
      break
    case 'download-original':
      await downloadMedia([item.id])
      break
    case 'restore':
      await handleRestoreMultiple([item.id])
      break
    case 'permanent-delete':
      confirmPermanentDeleteMultiple([item.id])
      break
    case 'add-to-board':
      showBoardPicker.value = true
      break
    case 'toggle-marker':
    case 'tags-saved':
    case 'view-in-tool':
    case 'jump-to-chat':
      // These actions are handled in-panel or don't need additional work
      break
  }
}

const { printContactSheet } = usePrint()

// Print contact sheet of selected items
function handlePrint() {
  if (selectedItems.value.length === 0) return
  printContactSheet(selectedItems.value, getThumbnailUrl)
}

// Download selected items
function handleDownload(ids = null) {
  const assetIds = ids || selectedItemIds.value
  if (assetIds.length === 0) return

  // If specific IDs passed, find matching items from selectedItems or use IDs only
  const items = ids
    ? selectedItems.value.filter(item => ids.includes(assetIdOf(item)))
    : [...selectedItems.value]

  exportMediaIds.value = items.map(mediaIdOf).filter(Boolean)
  exportMediaItems.value = items
  showExportModal.value = true
}

async function handleToggleMarker({ markerId, add }) {
  if (selectedItemIds.value.length === 0) return

  try {
    await bulkMarkerOperation(selectedItemIds.value, markerId, add)
  } catch (error) {
    console.error('Failed to toggle marker:', error)
    addToast(add ? 'Failed to add marker' : 'Failed to remove marker', 'error')
  }
}

function handleBoardsAdded() {
  showBoardPicker.value = false
}

function handleTagsSaved() {
  showTagEditor.value = false
  filterBarRef.value?.refreshTags()
}

async function handleMoveToTrash() {
  if (selectedItemIds.value.length === 0) return

  try {
    const idsToDelete = [...selectedItemIds.value]
    await bulkDeleteMedia(idsToDelete)
    selectedItemIds.value = []
    multiSelectMode.value = false
    await reconcileRemoval(idsToDelete)
  } catch (error) {
    console.error('Failed to move items to trash:', error)
    addToast('Failed to move items to trash', 'error')
  }
}

// Handle single item deletion from context menu (legacy, kept for reference)
async function handleDeleteSingle(item) {
  try {
    await bulkDeleteMedia([item.id])
    await reconcileRemoval([item.id])
  } catch (error) {
    console.error('Failed to move item to trash:', error)
    addToast('Failed to move item to trash', 'error')
  }
}

// Handle delete for context menu (operates on targetIds from selection-aware context menu)
async function handleDeleteMultiple(targetIds) {
  if (!targetIds || targetIds.length === 0) return

  try {
    await bulkDeleteMedia(targetIds)
    // Clear selection if we deleted selected items
    if (targetIds.length > 1 || selectedItemIds.value.includes(targetIds[0])) {
      selectedItemIds.value = []
      multiSelectMode.value = false
    }
    await reconcileRemoval(targetIds)
  } catch (error) {
    console.error('Failed to move items to trash:', error)
    addToast('Failed to move items to trash', 'error')
  }
}

// === Trash Mode Actions ===

// Restore single item from trash
async function restoreItem(mediaId) {
  try {
    await restoreFromTrash(mediaId)
    await reconcileRemoval([mediaId])
  } catch (error) {
    console.error('Failed to restore item:', error)
    addToast('Failed to restore item', 'error')
  }
}

// Handle restore for context menu (operates on targetIds from selection-aware context menu)
async function handleRestoreMultiple(targetIds) {
  if (!targetIds || targetIds.length === 0) return

  try {
    await bulkRestoreFromTrash(targetIds)
    // Clear selection if we restored selected items
    if (targetIds.length > 1 || selectedItemIds.value.includes(targetIds[0])) {
      selectedItemIds.value = []
      multiSelectMode.value = false
    }
    await reconcileRemoval(targetIds)
  } catch (error) {
    console.error('Failed to restore items:', error)
    addToast(`Failed to restore items: ${error.response?.data?.detail || error.message}`, 'error')
  }
}

// Bulk restore selected items from trash
async function handleBulkRestore() {
  if (selectedItemIds.value.length === 0) return

  try {
    const idsToRestore = [...selectedItemIds.value]
    await bulkRestoreFromTrash(idsToRestore)
    selectedItemIds.value = []
    multiSelectMode.value = false
    await reconcileRemoval(idsToRestore)
  } catch (error) {
    console.error('Failed to restore items:', error)
    addToast(`Failed to restore items: ${error.response?.data?.detail || error.message}`, 'error')
  }
}

// Confirm permanent deletion of single item
async function loadDeletionPreviews(assetIds) {
  deletionPreviews.value = []
  deletionPreviewLoading.value = true
  try {
    deletionPreviews.value = await Promise.all(assetIds.map(getDeletionPreview))
  } catch (error) {
    console.error('Failed to preview permanent deletion:', error)
  } finally {
    deletionPreviewLoading.value = false
  }
}

function confirmPermanentDelete(mediaId) {
  itemToDelete.value = [mediaId]  // Store as array for consistency
  showDeleteConfirm.value = true
  void loadDeletionPreviews(itemToDelete.value)
}

// Confirm permanent deletion of multiple items (context menu)
function confirmPermanentDeleteMultiple(targetIds) {
  if (!targetIds || targetIds.length === 0) return
  itemToDelete.value = [...targetIds]  // Store as array
  showDeleteConfirm.value = true
  void loadDeletionPreviews(itemToDelete.value)
}

// Execute permanent deletion (handles both single and multiple)
async function permanentDelete() {
  if (!itemToDelete.value || itemToDelete.value.length === 0) return

  try {
    const idsToDelete = itemToDelete.value
    let response
    if (idsToDelete.length === 1) {
      response = await permanentlyDeleteMedia(idsToDelete[0])
    } else {
      response = await bulkPermanentlyDelete(idsToDelete)
    }
    // Clear selection if we deleted selected items
    if (idsToDelete.length > 1 || selectedItemIds.value.includes(idsToDelete[0])) {
      selectedItemIds.value = []
      multiSelectMode.value = false
    }
    itemToDelete.value = null
    showDeleteConfirm.value = false
    const accepted = response?.accepted ?? idsToDelete.length
    const results = response?.results || [response]
    const retainedCount = results.reduce(
      (count, result) => count + (result?.retained_media_ids?.length || 0),
      0,
    )
    if (retainedCount > 0) {
      addToast(
        `Removed ${accepted} ${accepted === 1 ? 'asset' : 'assets'}; ${retainedCount} media ${retainedCount === 1 ? 'revision is' : 'revisions are'} still retained by other content`,
        'info',
      )
    } else {
      addToast(`Permanent deletion started for ${accepted} ${accepted === 1 ? 'item' : 'items'}`, 'info')
    }
  } catch (error) {
    console.error('Failed to permanently delete:', error)
    addToast('Failed to permanently delete item(s)', 'error')
  }
}

// Bulk permanent delete selected items
async function handleBulkPermanentDelete() {
  if (selectedItemIds.value.length === 0) return

  try {
    const idsToDelete = [...selectedItemIds.value]
    const response = await bulkPermanentlyDelete(idsToDelete)
    selectedItemIds.value = []
    multiSelectMode.value = false
    const accepted = response?.accepted ?? idsToDelete.length
    addToast(`Deleted ${accepted} items permanently`, 'info')
  } catch (error) {
    console.error('Failed to permanently delete items:', error)
    addToast('Failed to permanently delete items', 'error')
  }
}

// Confirm empty trash
function confirmEmptyTrash() {
  if (isEmptyingTrash.value) return
  showEmptyTrashConfirm.value = true
}

// Execute empty trash
async function emptyTrash() {
  try {
    const response = await apiEmptyTrash()
    const accepted = response?.accepted ?? 0
    showEmptyTrashConfirm.value = false
    if (accepted > 0) {
      selectedItemIds.value = []
      multiSelectMode.value = false
      addToast(`Deleted ${accepted} ${accepted === 1 ? 'item' : 'items'} permanently`, 'info')
    }
  } catch (error) {
    console.error('Failed to empty trash:', error)
    addToast('Failed to empty trash', 'error')
  }
}

async function handleContextMenuAction({ action, item, targetIds, inSelection }) {
  switch (action) {
    case 'view':
      // View always opens the clicked item only
      openSlideshow({ itemId: item.id })
      break
    case 'similar':
      // Similar search uses only the clicked item
      if (item.has_clip_embedding) {
        searchSimilar(item.id)
      }
      break
    case 'delete':
      // Delete all targeted items (selection or single)
      await handleDeleteMultiple(targetIds)
      break
    case 'markers':
    case 'tags':
    case 'boards':
      // For bulk actions from context menu, temporarily set the selection
      // so the existing bulk modals work correctly
      if (targetIds.length > 0 && !inSelection) {
        // Item wasn't in selection, so we need to set selection temporarily
        selectedItemIds.value = targetIds
        multiSelectMode.value = true
      }
      // Open the appropriate modal
      if (action === 'markers') {
        showMarkerSheet.value = true
      } else if (action === 'tags') {
        showTagEditor.value = true
      } else if (action === 'boards') {
        showBoardPicker.value = true
      }
      break
    // Trash mode actions
    case 'restore':
      // Restore all targeted items
      await handleRestoreMultiple(targetIds)
      break
    case 'delete-permanently':
      // Permanent delete all targeted items
      confirmPermanentDeleteMultiple(targetIds)
      break
    default:
      console.warn('Unknown context menu action:', action)
  }
}

function handleEmptySpaceAction({ action }) {
  switch (action) {
    case 'select-all':
      if (!multiSelectMode.value) {
        multiSelectMode.value = true
      }
      selectAll()
      break
    case 'import':
      // Emit to parent or trigger import dialog
      // For now, log - actual import handling depends on parent
      console.log('Import requested from context menu')
      break
    default:
      console.warn('Unknown empty space action:', action)
  }
}

// Slideshow - enter slideshow mode
async function openSlideshow(clickData) {
  const itemId = clickData.itemId || clickData
  const gridIndex = clickData.index

  try {
    let startIndex = 0

    // Use cache-based lookup whenever similarity sort or filters are active,
    // since the findMediaIndex API doesn't support similarity search
    const isSimilarityMode = similarSearchActive.value ||
        filters.sortBy === 'similarity' ||
        (filters.similarTo && filters.similarTo.length > 0) ||
        (filters.similarFaceTo && filters.similarFaceTo.length > 0) ||
        (filters.similarToText && filters.similarToText.trim())

    if (isSimilarityMode) {
      // For similarity search, use the grid index directly since both grid and
      // slideshow share the same mediaList cache. Verify by looking up the item
      // by ID as a sanity check.
      const foundIndex = mediaList?.findIndex(itemId) ?? -1
      if (foundIndex >= 0) {
        startIndex = foundIndex
      } else if (gridIndex != null) {
        startIndex = gridIndex
      } else {
        startIndex = 0
      }
    } else {
      // For normal search, find the index via API
      const snapshotParams = buildFilterParams()
      const result = await findMediaIndex(itemId, snapshotParams)
      startIndex = result.index
    }

    // Enter slideshow mode with shared mediaList
    // This ensures both grid and slideshow share the same item cache
    enterSlideshow({
      totalCount: totalCount.value,
      startIndex,
      mediaList: mediaList,
      randomized: false,
      randomSeed: null
    })
  } catch (error) {
    console.error('Failed to open slideshow:', error)
    // Fallback: look up by ID first, then grid index
    const fallbackIndex = mediaList?.findIndex(itemId) ?? gridIndex ?? 0
    enterSlideshow({
      totalCount: totalCount.value,
      startIndex: Math.max(0, fallbackIndex),
      mediaList: mediaList,
      randomized: false,
      randomSeed: null
    })
  }
}

async function startSlideshowFromSelected() {
  if (selectedItemIds.value.length === 0) return

  try {
    const itemPromises = selectedItemIds.value.map(id => getMediaItem(id))
    const items = await Promise.all(itemPromises)

    // Create page provider for selected items
    const selectedPageProvider = async (pageNumber, pageSize) => {
      const start = pageNumber * pageSize
      const end = start + pageSize
      return items.slice(start, end)
    }

    enterSlideshow({
      totalCount: items.length,
      startIndex: 0,
      pageProvider: selectedPageProvider,
      randomized: false,
      randomSeed: null
    })

    multiSelectMode.value = false
    selectedItemIds.value = []
  } catch (error) {
    console.error('Failed to start slideshow from selection:', error)
  }
}

function handleKeywordFilter(keyword) {
  if (!filters.selectedKeywords.includes(keyword)) {
    filters.selectedKeywords.push(keyword)
  }
  loadMedia()
}

function generateNewRandomSeed() {
  randomSeed.value = Date.now()
}

async function handleShuffle() {
  generateNewRandomSeed()
  await nextTick()
  await loadMedia()
}

const browseFilterQueryKeys = new Set([
  'cq', 'pq', 'stt',
  'mt', 'xmt',
  'r', 'xr',
  's', 'k', 'xk',
  'f', 'xf',
  'tl', 'xtl',
  'prj', 'xprj',
  'sim', 'fsim',
  'st', 'rs'
])
let lastAppliedRouteQuerySignature = ''

function hasBrowseFilterQuery(query) {
  return Object.keys(query || {}).some(key => browseFilterQueryKeys.has(key))
}

function getRouteQuerySignature(query) {
  return Object.keys(query || {})
    .sort()
    .map((key) => {
      const value = query[key]
      return `${key}=${Array.isArray(value) ? value.join(',') : value ?? ''}`
    })
    .join('&')
}

async function hydrateSimilarSearchSourceItems(ids) {
  const items = await Promise.all(
    ids.map(async (id) => {
      try {
        return await getMediaItem(id)
      } catch (error) {
        console.error('Failed to fetch similarity source item:', id, error)
        return null
      }
    })
  )
  const resolvedItems = items.filter(Boolean)
  similarSearchSourceItems.value = resolvedItems
  similarSearchSourceItem.value = resolvedItems[0] || null
}

async function applyUrlFiltersFromQuery(query, { reload = false } = {}) {
  if (useExternalFilters) return

  if (!hasBrowseFilterQuery(query)) {
    lastAppliedRouteQuerySignature = getRouteQuerySignature(query)
    return
  }

  const signature = getRouteQuerySignature(query)
  if (signature === lastAppliedRouteQuerySignature) return
  lastAppliedRouteQuerySignature = signature

  const urlFilters = normalizeBrowseFilters(decodeFiltersFromUrl(query))
  Object.assign(filters, urlFilters)

  const similarIds = filters.similarTo || []
  const similarFaceIds = filters.similarFaceTo || []
  const hasSimilarIds = similarIds.length > 0 || similarFaceIds.length > 0
  const hasSimilarText = !!(filters.similarToText && filters.similarToText.trim())

  if (hasSimilarIds || hasSimilarText) {
    filters.sortBy = 'similarity'
    similarSearchActive.value = true

    if (hasSimilarIds) {
      await hydrateSimilarSearchSourceItems(similarFaceIds.length > 0 ? similarFaceIds : similarIds)
    } else {
      similarSearchSourceItem.value = null
      similarSearchSourceItems.value = []
    }
  } else {
    similarSearchActive.value = false
    similarSearchSourceItem.value = null
    similarSearchSourceItems.value = []
  }

  if (reload && !initializing.value) {
    await loadMedia()
    await nextTick()
    virtualGridRef.value?.scrollToTop?.()
  }
}

function clearSimilarityRouteQuery() {
  if (route.name !== 'browse') return

  const nextQuery = { ...route.query }
  let changed = false

  for (const key of ['sim', 'fsim', 'stt', 'st']) {
    if (nextQuery[key] !== undefined) {
      delete nextQuery[key]
      changed = true
    }
  }

  if (nextQuery.s === 'sim') {
    delete nextQuery.s
    changed = true
  }

  if (!changed) return

  lastAppliedRouteQuerySignature = ''
  router.replace({ query: nextQuery }).catch((error) => {
    console.error('Failed to clear similarity query params:', error)
  })
}

function goToUpload() {
  const query = {}
  if (props.projectId != null) {
    query.project_id = String(props.projectId)
  }
  router.push({ name: 'upload', query })
}

watch(() => filters.sortBy, (newSort, oldSort) => {
  if (initializing.value) return
  if (newSort === 'random' && oldSort && oldSort !== 'random') {
    generateNewRandomSeed()
  }
})

watch(() => route.query, async (query) => {
  if (initializing.value || route.name !== 'browse' || useExternalFilters) return
  await applyUrlFiltersFromQuery(query, { reload: true })
}, { deep: true })

// Watch for filter changes triggered by navigation (e.g., from slideshow)
watch(filterChangeCounter, async () => {
  if (!initializing.value && !useExternalFilters) {
    await loadMedia()
  }
})

// Reload media when websocket reconnects (backend came back up)
watch(wsConnected, async (connected, wasConnected) => {
  if (connected && wasConnected === false && !initializing.value) {
    console.log('[BrowseGridView] WebSocket reconnected, reloading media')
    await loadMedia()
  }
})

// Handle markers config change
async function handleMarkersChanged() {
  try {
    markers.value = await getMarkers()
  } catch (error) {
    console.error('Failed to reload markers:', error)
  }
}

onMounted(async () => {
  try {
    markers.value = await getMarkers()
  } catch (error) {
    console.error('Failed to load markers:', error)
  }

  // Listen for markers config changes
  window.addEventListener('markers-changed', handleMarkersChanged)

  // Listen for compare action from context menu
  window.addEventListener('media-compare', handleCompareFromContextMenu)

  // Listen for set created event to refresh the grid
  window.addEventListener('media-set-created', handleSetCreated)

  // Check for URL query parameters and apply them to browse filters only
  if (!useExternalFilters && route.name === 'browse' && hasBrowseFilterQuery(route.query)) {
    console.log('[BrowseGridView] Found URL query params:', route.query)
    await applyUrlFiltersFromQuery(route.query)
    console.log('[BrowseGridView] Decoded filters from URL:', JSON.stringify(filters))
  }

  // Handle slideshowMedia query param (e.g., after image editor save)
  // Do this BEFORE loadMedia to open slideshow instantly
  const slideshowAssetId = route.query.slideshowAsset
  if (slideshowAssetId) {
    // Clear the query param immediately
    const newQuery = { ...route.query }
    delete newQuery.slideshowAsset
    router.replace({ query: newQuery })

    // Open slideshow directly using findMediaIndex API (faster than waiting for full loadMedia)
    const id = parseInt(slideshowAssetId, 10)
    if (!isNaN(id)) {
      try {
        const snapshotParams = buildFilterParams()
        const result = await findMediaIndex(id, snapshotParams)
        // Open slideshow with pageProvider (not mediaList, since it's not populated yet)
        enterSlideshow({
          totalCount: result.total,
          startIndex: result.index,
          pageProvider: fetchPageItems,
          randomized: false,
          randomSeed: null
        })
      } catch (error) {
        console.error('Failed to open slideshow to media:', error)
      }
    }
  }

  // Load media with current global filter state
  // This will pick up any filters that were set before navigation
  await loadMedia()
  initializing.value = false

  console.log('[BrowseGridView] Mounted with filters:', JSON.stringify(filters))
  console.log('[BrowseGridView] similarSearchActive:', similarSearchActive.value)
  console.log('[BrowseGridView] similarSearchSourceItem:', similarSearchSourceItem.value)
  console.log('[BrowseGridView] similarSearchSourceItems:', similarSearchSourceItems.value)

  // Setup WebSocket event listeners
  wsUnsubscribers.push(wsOn('asset_created', async (data) => {
    const count = data.count || 1
    if (count > 0) {
      // Check if we can do a soft update (prepend items in place)
      // Use a conservative strategy for filtered and saved views.
      const hasSpecificIds = Boolean(data.asset_id || data.asset_ids?.length)
      const hasActiveFilterCriteria =
        !!filters.captionQuery ||
        !!filters.promptQuery ||
        !!filters.similarToText ||
        (filters.mediaTypes?.length > 0) ||
        (filters.excludedMediaTypes?.length > 0) ||
        (filters.resolutions?.length > 0) ||
        (filters.excludedResolutions?.length > 0) ||
        (filters.selectedKeywords?.length > 0) ||
        (filters.excludedKeywords?.length > 0) ||
        (filters.selectedFolders?.length > 0) ||
        (filters.excludedFolders?.length > 0) ||
        (filters.selectedTags?.length > 0) ||
        (filters.excludedTags?.length > 0) ||
        (filters.selectedTools?.length > 0) ||
        (filters.excludedTools?.length > 0) ||
        (filters.selectedMarkers?.length > 0) ||
        (filters.excludedMarkers?.length > 0) ||
        (filters.similarTo?.length > 0) ||
        (filters.similarFaceTo?.length > 0) ||
        !!filters.createdAfter ||
        !!filters.createdBefore ||
        !!filters.showExpiring ||
        !!filters.excludeExpiring
      const canSoftUpdate =
        !props.isTrashMode &&
        !useExternalFilters &&
        filters.sortBy === 'created_desc' &&
        !similarSearchActive.value &&
        !hasActiveFilterCriteria &&
        !hasSpecificIds

      if (canSoftUpdate && virtualGridRef.value) {
        try {
          // Fetch the new items from the beginning with current filters
          const params = buildFilterParams()
          const response = await fetchMedia({
            ...params,
            page: 1,
            page_size: count
          })

          // Check if new items actually match our filters
          // (they might not if filters are excluding them)
          if (response.items && response.items.length > 0) {
            // Prepend items to grid first - this sets skipNextTotalCountWatch flag
            await virtualGridRef.value.prependItems(response.items, response.total)
            // Update totalCount AFTER prependItems so the flag is set and watcher skips
            totalCount.value = response.total
          }
          // Note: No else branch needed - if items don't match filters,
          // softReloadMedia will be called on next media_added event
        } catch (error) {
          console.error('Failed to soft update, falling back to soft reload:', error)
          softReloadMedia()
        }
      } else {
        // Fall back to soft reload for filtered/saved views and non-default modes.
        softReloadMedia()
      }
    }
  }))

  wsUnsubscribers.push(wsOn('asset_deleted', (data) => {
    if (data.profile_id && data.profile_id !== getCurrentProfileId()) return
    const { asset_id } = data
    if (props.isTrashMode) {
      softReloadMedia()
    } else if (asset_id && mediaList) {
      removeFromSelection([asset_id])
      reconcileRemoval([asset_id])
    }
  }))

  wsUnsubscribers.push(wsOn('assets_trashed', (data) => {
    if (data.profile_id && data.profile_id !== getCurrentProfileId()) return
    const { asset_ids } = data
    if (props.isTrashMode) {
      softReloadMedia()
    } else if (asset_ids?.length && mediaList) {
      removeFromSelection(asset_ids)
      reconcileRemoval(asset_ids)
    }
  }))

  // Handle media restored events (for trash view)
  wsUnsubscribers.push(wsOn('asset_restored', (data) => {
    const asset_id = data.asset?.id || data.asset_id
    if (props.isTrashMode) {
      // Trash view: remove restored item from grid
      if (asset_id && mediaList) {
        removeFromSelection([asset_id])
        reconcileRemoval([asset_id])
      }
    } else {
      // Browse view: restored items should appear
      softReloadMedia()
    }
  }))

  wsUnsubscribers.push(wsOn('assets_restored', (data) => {
    const { asset_ids } = data
    if (props.isTrashMode) {
      // Trash view: remove restored items from grid
      if (asset_ids?.length && mediaList) {
        removeFromSelection(asset_ids)
        reconcileRemoval(asset_ids)
      }
    } else {
      // Browse view: restored items should appear
      softReloadMedia()
    }
  }))

  // Handle permanent deletion events (bulk permanent delete with known IDs)
  wsUnsubscribers.push(wsOn('asset_identity_deleted', (data) => {
    if (!props.isTrashMode) return  // Only relevant for trash view
    const { asset_id } = data
    if (asset_id && mediaList) {
      removeFromSelection([asset_id])
      reconcileRemoval([asset_id])
    }
  }))

  // Handle trash emptied event (large bulk deletes where IDs aren't sent)
  wsUnsubscribers.push(wsOn('asset_identities_deleted', () => {
    if (!props.isTrashMode) return
    // Full reload — all items are gone
    totalCount.value = 0
    selectedItemIds.value = []
    multiSelectMode.value = false
    filterKey.value++
  }))

  wsUnsubscribers.push(wsOn('asset_current_revision_changed', () => {
    softReloadMedia()
  }))

  wsUnsubscribers.push(wsOn('assets_updated', () => {
    softReloadMedia()
  }))

  // Listen for profile changes
  window.addEventListener('profile-changed', handleProfileChanged)

  // Listen for settings loaded (bundle_id/sandbox now available for correct localStorage keys)
  window.addEventListener('settings-loaded', handleSettingsLoaded)

  // If settings already loaded before we mounted, reload filters now
  if (isSettingsLoaded()) {
    handleSettingsLoaded()
  }
})

// Determine which route name this instance should respond to
const myRouteName = computed(() => props.isTrashMode ? 'trash' : 'browse')

// Watch for when this view becomes visible by watching the route
// Skip when using external filters (e.g., SavedViewPage) - the parent manages lifecycle
if (!useExternalFilters) {
  watch(
    () => route.name,
    async (newRouteName, oldRouteName) => {
      // Double-check: skip for external filters (belt-and-suspenders for HMR/KeepAlive)
      if (useExternalFilters) return
      const isNavigatingToMe = newRouteName === myRouteName.value && oldRouteName !== myRouteName.value

      // Navigated TO this view - reload data
      if (isNavigatingToMe && !initializing.value) {
        await loadMedia()
      }
    }
  )
}

// Handle settings loaded - reload filters now that bundle_id is available
// This fixes the timing issue where filters are loaded before settings
async function handleSettingsLoaded() {
  // Only reload if we're using global filters (not SavedViewPage's external filters)
  if (useExternalFilters) return

  console.log('[BrowseGridView] Settings loaded, reloading filters with correct storage key')
  const savedFilters = loadSavedFilters()
  if (savedFilters) {
    // Check if any filters were actually loaded (not just defaults)
    const hasNonDefaultFilters = savedFilters.captionQuery ||
      savedFilters.promptQuery ||
      savedFilters.mediaTypes?.length > 0 ||
      savedFilters.selectedKeywords?.length > 0 ||
      savedFilters.selectedTags?.length > 0 ||
      savedFilters.selectedFolders?.length > 0 ||
      savedFilters.selectedMarkers?.length > 0

    if (hasNonDefaultFilters) {
      Object.assign(filters, savedFilters)
      // Reload media with the restored filters
      await loadMedia()
    }
  }
}

// Handle profile changes - reset filters to defaults for new profile and reload
async function handleProfileChanged() {
  console.log('[BrowseGridView] Profile changed, resetting filters and reloading')

  // Reset all filters to defaults for the new profile
  Object.assign(filters, cloneDefaultBrowseFilters())

  // Clear similar search state
  similarSearchActive.value = false
  similarSearchSourceItem.value = null
  similarSearchSourceItems.value = []

  // Clear selection
  selectedItemIds.value = []
  multiSelectMode.value = false

  // Load profile-specific saved filters (if any exist for this profile)
  const savedFilters = loadSavedFilters()
  Object.assign(filters, savedFilters)

  // Reload markers for new profile
  try {
    markers.value = await getMarkers()
  } catch (error) {
    console.error('Failed to load markers for new profile:', error)
  }

  // Force FilterBar to reload its data (tags, keywords, etc.)
  filterKey.value++

  // Reload media
  await loadMedia()
}

// Handle set created event - refresh the grid to show the new set
async function handleSetCreated() {
  // Wait a short moment for the rescan to complete and index the new file
  await new Promise(resolve => setTimeout(resolve, 500))
  await loadMedia()
}

onUnmounted(() => {
  wsUnsubscribers.forEach(unsubscribe => {
    try {
      unsubscribe()
    } catch (error) {
      console.warn('Failed to unsubscribe websocket handler:', error)
    }
  })

  // Cleanup event listeners
  window.removeEventListener('profile-changed', handleProfileChanged)
  window.removeEventListener('settings-loaded', handleSettingsLoaded)
  window.removeEventListener('markers-changed', handleMarkersChanged)
  window.removeEventListener('media-compare', handleCompareFromContextMenu)
  window.removeEventListener('media-set-created', handleSetCreated)
})
</script>
