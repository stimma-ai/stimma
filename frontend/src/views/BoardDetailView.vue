<template>
  <div class="relative flex h-full flex-col">
    <SlideshowMode
      v-if="slideshowState.active"
      :total-count="slideshowState.totalCount"
      :start-index="slideshowState.startIndex"
      :page-provider="slideshowState.pageProvider"
      :inline="true"
      @close="exitSlideshow"
      @update:current-media-id="updateCurrentMediaId"
    />

    <div v-show="!slideshowState.active && board" class="flex items-center justify-between gap-4 border-b border-white/10 px-6 py-4">
      <div class="min-w-0 flex-1">
        <input
          v-if="isEditingBoardName || editedName"
          ref="boardNameInputRef"
          v-model="editedName"
          class="w-full max-w-xl bg-transparent text-2xl font-semibold text-content outline-none"
          placeholder="Name this board..."
          @blur="handleBoardNameBlur"
          @keydown.enter.prevent="saveBoardName"
          @keydown.esc.prevent="cancelBoardNameEdit"
        />
        <button
          v-else
          class="max-w-xl bg-transparent text-left text-2xl font-semibold italic text-content-muted outline-none transition-colors hover:text-content-secondary"
          @click="startBoardNameEdit"
        >
          Name this board...
        </button>
        <p class="mt-1 text-sm text-content-muted">{{ boardSummaryText }}</p>
      </div>
      <div class="relative">
        <button
          ref="boardMenuButtonRef"
          class="flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 text-content-muted transition-colors hover:bg-white/[0.05] hover:text-content"
          title="Board actions"
          @click="toggleBoardMenu"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-5 w-5">
            <path d="M10 3a1.75 1.75 0 110 3.5A1.75 1.75 0 0110 3zm0 5.25a1.75 1.75 0 110 3.5 1.75 1.75 0 010-3.5zm0 5.25a1.75 1.75 0 110 3.5 1.75 1.75 0 010-3.5z" />
          </svg>
        </button>

        <div
          v-if="boardMenuOpen"
          ref="boardMenuRef"
          class="absolute right-0 top-11 z-20 min-w-[180px] overflow-hidden rounded-xl border border-white/10 bg-surface shadow-2xl"
        >
          <button
            class="flex w-full items-center gap-3 px-4 py-3 text-left text-sm text-red-400 transition-colors hover:bg-red-500/10"
            @click="handleBoardMenuDeleteBoard"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4">
              <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5z" clip-rule="evenodd" />
            </svg>
            <span>Delete Board</span>
          </button>
        </div>
      </div>
    </div>

    <div v-show="!slideshowState.active" ref="scrollerRef" class="flex-1 overflow-y-auto px-6 py-5" :class="{ 'pb-24': multiSelectMode && selectedItemIds.length > 0 }">
      <div v-if="loading" class="py-20 text-center text-content-muted">Loading board...</div>
      <div v-else-if="!board" class="py-20 text-center text-content-muted">Board not found.</div>
      <TransitionGroup v-else tag="div" class="space-y-5">
        <section
          v-for="section in displaySections"
          :key="section.id"
          :ref="(el) => setSectionRef(section.id, el)"
          data-board-section="true"
          class="overflow-hidden rounded-lg border border-edge-subtle shadow-[inset_0_1px_0_rgba(255,255,255,0.03)] transition-colors"
          :class="[
            sectionDragCollapsed && dragState.sectionDragId === section.id ? 'opacity-40' : ''
          ]"
          :style="pitStyle"
          @dragover.prevent="handleSectionContainerDragOver(section, $event)"
          @drop.prevent="handleSectionContainerDrop(section, $event)"
        >
          <div
            class="flex select-none items-center gap-2 px-4 py-3"
            :class="!dragState.item ? 'cursor-grab active:cursor-grabbing' : ''"
            draggable="true"
            @dragstart.stop="onSectionDragStart(section, $event)"
            @dragend="onSectionDragEnd"
            @dragover.stop.prevent="handleSectionHeaderDragOver(section, $event)"
            @drop.stop.prevent="commitSectionDrop()"
          >
            <div class="flex flex-1 justify-start px-2">
              <input
                v-if="sectionEditingId === section.id"
                v-model="sectionNames[section.id]"
                :ref="(el) => setSectionInputRef(section.id, el)"
                :style="{ width: getSectionLabelWidth(section) }"
                class="rounded-full border border-black/5 bg-white/95 px-3 py-1 text-left text-xs font-medium text-zinc-500 shadow-sm outline-none dark:border-white/5 dark:bg-white/90 dark:text-zinc-500"
                @blur="saveSection(section)"
                @keydown.enter.prevent="saveSection(section)"
                @keydown.esc.prevent="cancelSectionEdit(section)"
              />
              <button
                v-else
                :style="{ width: getSectionLabelWidth(section) }"
                class="rounded-full border border-black/5 bg-white/95 px-3 py-1 text-left text-xs font-medium text-zinc-500 shadow-sm transition-colors hover:border-black/10 hover:bg-white dark:border-white/5 dark:bg-white/90 dark:text-zinc-500 dark:hover:border-white/10 dark:hover:bg-white"
                @click.stop="startSectionEdit(section)"
              >
                <span v-if="section.name" class="truncate">{{ section.name }}</span>
                <span v-else class="block h-[1.25rem] opacity-35">&nbsp;</span>
              </button>
            </div>
          </div>

          <div
            v-if="!(sectionDragCollapsed && dragState.sectionDragId === section.id)"
            class="select-none"
            :class="[sectionDragCollapsed ? 'pb-2' : 'min-h-[180px] pb-4', 'px-4']"
            @dragover.stop.prevent="handleSectionBodyDragOver(section, $event)"
            @drop.stop.prevent="commitSectionBodyDrop(section, $event)"
          >
            <div class="space-y-3">
              <div
                v-for="(row, rowIndex) in sectionDragCollapsed ? (layoutRows[section.id] || []).slice(0, 1) : (layoutRows[section.id] || [])"
                :key="`${section.id}-${rowIndex}`"
                class="flex gap-3"
              >
                <div
                  v-for="item in row.items"
                  :key="String(item.id)"
                  :ref="(el) => setTileRef(section.id, item, el)"
                  class="group relative overflow-hidden rounded-xl text-left"
                  :class="[
                    item.__placeholder ? 'bg-white/[0.08]' : 'cursor-grab select-none bg-white/[0.04] hover:scale-[1.04] active:cursor-grabbing',
                    !item.__placeholder && selectedItemIds.includes(item.id) ? 'ring-[3px] ring-blue-500 ring-inset' : ''
                  ]"
                  :style="{ width: `${item._layoutWidth}px`, height: `${row.height}px` }"
                  @click="!item.__placeholder && handleItemClick(section, item, $event)"
                  @contextmenu.stop.prevent="!item.__placeholder && handleItemContextMenu(section, item, $event)"
                  @dragover.stop.prevent="handleItemOrPlaceholderDragOver(section, item, $event)"
                  @drop.stop.prevent="handleItemOrPlaceholderDrop(section, item, $event)"
                  @dragstart.stop="!item.__placeholder && onItemDragStart(section, item, $event)"
                  @dragend.stop="onItemDragEnd()"
                  :draggable="!item.__placeholder"
                >
                  <div
                    :data-board-item="item.__placeholder ? undefined : 'true'"
                    class="h-full w-full"
                  >
                    <MediaImage
                      :media-id="item.id"
                      :file-hash="item.file_hash"
                      :file-path="item.file_path"
                      :file-format="item.file_format"
                      :is-video="item.file_format && ['mp4','webm','mov','avi','mkv','ogg'].includes(item.file_format)"
                      thumbnail
                      thumbnail-mode="fit"
                      :thumbnail-size="256"
                      :contain="true"
                      :draggable="false"
                      :enable-context-menu="false"
                      container-class="h-full w-full"
                      img-class="h-full w-full object-contain"
                    />
                  </div>
                  <div
                    v-if="item.__placeholder"
                    class="pointer-events-none absolute inset-0 rounded-xl ring-2 ring-inset ring-blue-500/70"
                  />
                  <!-- Marker badges -->
                  <MarkerBadges
                    v-if="!item.__placeholder && item.markers && item.markers.length > 0"
                    :markers="item.markers"
                    class="absolute bottom-2 right-2 z-[6]"
                  />
                  <!-- Selection checkbox - visible on hover or when selected -->
                  <div
                    v-if="!item.__placeholder"
                    :class="[
                      'absolute top-2 left-2 z-10 transition-opacity',
                      selectedItemIds.includes(item.id) ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
                    ]"
                    @click.stop="handleCheckboxClick(section, item, $event)"
                  >
                    <div :class="[
                      'w-6 h-6 bg-black/60 backdrop-blur-md border-2 rounded-md flex items-center justify-center transition-all cursor-pointer',
                      selectedItemIds.includes(item.id) ? 'bg-blue-500 border-blue-500' : 'border-edge-strong hover:border-edge-strong'
                    ]">
                      <svg v-if="selectedItemIds.includes(item.id)" class="w-4 h-4 text-content" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                      </svg>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div
              v-if="sectionDragCollapsed && (layoutRows[section.id] || []).length > 1"
              class="pt-1 text-center text-xs text-content-muted"
            >
              and {{ (layoutRows[section.id] || []).slice(1).reduce((sum, r) => sum + r.items.length, 0) }} more
            </div>
          </div>
        </section>

      </TransitionGroup>
    </div>

    <Transition name="fade">
      <div
        v-if="dragState.item"
        class="pointer-events-none absolute bottom-6 left-0 right-0 z-50 flex items-center justify-center gap-3"
      >
        <div
          class="pointer-events-auto rounded-xl border px-5 py-2.5 shadow-lg transition-all"
          :class="dragState.newSectionHover ? 'border-blue-400 bg-blue-500 text-white scale-105 shadow-blue-500/30' : 'border-white/10 bg-zinc-800 text-zinc-200 shadow-black/40'"
          @dragenter.prevent="dragState.newSectionHover = true"
          @dragover.prevent="handleNewSectionDragOver"
          @dragleave="handleNewSectionDragLeave"
          @drop.prevent="createSectionFromDrop($event)"
        >
          <div class="flex items-center gap-2 text-sm font-medium">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4">
              <path d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" />
            </svg>
            Create new section
          </div>
        </div>
        <div
          class="pointer-events-auto rounded-xl border px-5 py-2.5 shadow-lg transition-all"
          :class="dragState.removeFromBoardHover ? 'border-red-400 bg-red-500 text-white scale-105 shadow-red-500/30' : 'border-white/10 bg-zinc-800 text-zinc-200 shadow-black/40'"
          @dragenter.prevent="dragState.removeFromBoardHover = true"
          @dragover.prevent="handleRemoveFromBoardDragOver"
          @dragleave="handleRemoveFromBoardDragLeave"
          @drop.prevent="removeFromBoardDrop($event)"
        >
          <div class="flex items-center gap-2 text-sm font-medium">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4">
              <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5z" clip-rule="evenodd" />
            </svg>
            Remove from board
          </div>
        </div>
      </div>
    </Transition>

    <Transition name="fade">
      <div
        v-if="dragState.sectionDragId"
        class="pointer-events-none absolute bottom-6 left-0 right-0 z-50 flex items-center justify-center gap-3"
      >
        <div
          v-if="!draggedSectionIsDefault"
          class="pointer-events-auto rounded-xl border px-5 py-2.5 shadow-lg transition-all"
          :class="dragState.explodeSectionHover ? 'border-blue-400 bg-blue-500 text-white scale-105 shadow-blue-500/30' : 'border-white/10 bg-zinc-800 text-zinc-200 shadow-black/40'"
          @dragenter.prevent="dragState.explodeSectionHover = true"
          @dragover.prevent="dragState.explodeSectionHover = true"
          @dragleave="handleExplodeSectionDragLeave"
          @drop.prevent="explodeSectionDrop()"
        >
          <div class="flex items-center gap-2 text-sm font-medium">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4">
              <path fill-rule="evenodd" d="M4.25 2A2.25 2.25 0 002 4.25v2.5A2.25 2.25 0 004.25 9h2.5A2.25 2.25 0 009 6.75v-2.5A2.25 2.25 0 006.75 2h-2.5zm0 9A2.25 2.25 0 002 13.25v2.5A2.25 2.25 0 004.25 18h2.5A2.25 2.25 0 009 15.75v-2.5A2.25 2.25 0 006.75 11h-2.5zm9-9A2.25 2.25 0 0011 4.25v2.5A2.25 2.25 0 0013.25 9h2.5A2.25 2.25 0 0018 6.75v-2.5A2.25 2.25 0 0015.75 2h-2.5zm0 9A2.25 2.25 0 0011 13.25v2.5A2.25 2.25 0 0013.25 18h2.5A2.25 2.25 0 0018 15.75v-2.5A2.25 2.25 0 0015.75 11h-2.5z" clip-rule="evenodd" />
            </svg>
            Explode section
          </div>
        </div>
        <div
          class="pointer-events-auto rounded-xl border px-5 py-2.5 shadow-lg transition-all"
          :class="dragState.deleteSectionHover ? 'border-red-400 bg-red-500 text-white scale-105 shadow-red-500/30' : 'border-white/10 bg-zinc-800 text-zinc-200 shadow-black/40'"
          @dragenter.prevent="dragState.deleteSectionHover = true"
          @dragover.prevent="dragState.deleteSectionHover = true"
          @dragleave="handleDeleteSectionDragLeave"
          @drop.prevent="deleteSectionDrop()"
        >
          <div class="flex items-center gap-2 text-sm font-medium">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4">
              <path fill-rule="evenodd" d="M8.75 1A2.75 2.75 0 006 3.75v.443c-.795.077-1.584.176-2.365.298a.75.75 0 10.23 1.482l.149-.022.841 10.518A2.75 2.75 0 007.596 19h4.807a2.75 2.75 0 002.742-2.53l.841-10.52.149.023a.75.75 0 00.23-1.482A41.03 41.03 0 0014 4.193V3.75A2.75 2.75 0 0011.25 1h-2.5z" clip-rule="evenodd" />
            </svg>
            Delete section
          </div>
        </div>
      </div>
    </Transition>

    <MediaContextMenu />

    <MultiSelectActionBar
      :visible="multiSelectMode && selectedItemIds.length > 0"
      :selected-count="selectedItemIds.length"
      :total-count="totalAssetCount"
      :markers="markersData"
      :active-marker-ids="activeMarkerIds"
      :in-board="true"
      :first-selected-item="selectedItems[0] || null"
      :selected-items="selectedItems"
      @clear="selectNone"
      @select-all="selectAll"
      @toggle-marker="handleToggleMarker"
      @add-tags="showTagEditor = true"
      @add-to-board="showBoardPicker = true"
      @download="handleExport"
      @delete="handleBulkMoveToTrash"
    />

    <BoardPicker
      :visible="showBoardPicker"
      :media-ids="selectedItemIds"
      @close="showBoardPicker = false"
      @saved="handleBoardsAdded"
    />

    <BulkTagEditor
      :visible="showTagEditor"
      :media-ids="selectedItemIds"
      :current-tag-counts="currentTagCounts"
      :selected-items="selectedItems"
      @close="showTagEditor = false"
      @saved="handleTagsSaved"
    />

    <ExportModal
      :show="showExportModal"
      :media-ids="selectedItemIds"
      :media-items="selectedItems"
      @close="showExportModal = false"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MarkerBadges from '../components/MarkerBadges.vue'
import MultiSelectActionBar from '../components/MultiSelectActionBar.vue'
import BoardPicker from '../components/BoardPicker.vue'
import BulkTagEditor from '../components/BulkTagEditor.vue'
import ExportModal from '../components/ExportModal.vue'
import { MediaContextMenu, MediaImage } from '../components/media'
import SlideshowMode from '../components/SlideshowMode.vue'
import { useBoardMultiSelect } from '../composables/useBoardMultiSelect'
import { useMediaContextMenu } from '../composables/useMediaContextMenu'
import { useMediaApi } from '../composables/useMediaApi'
import { useToasts } from '../composables/useToasts'
import { createDragPreview, createSectionDragPreview, cleanupSectionDragPreview, handleDragEnd as handleDragPreviewEnd } from '../composables/useDragPreview'
import { useSlideshow } from '../composables/useSlideshow'
import { useTheme } from '../composables/useTheme'
import { useWebSocket } from '../composables/useWebSocket'

const { on } = useWebSocket()
const route = useRoute()
const router = useRouter()
const { resolvedTheme } = useTheme()
const mediaContextMenu = useMediaContextMenu()
const {
  bulkDeleteMedia,
  bulkMarkerOperation,
  bulkMoveBoardItems,
  bulkRemoveFromBoard,
  createBoardSection,
  deleteBoard,
  restoreBoard,
  deleteBoardSection,
  getBoard,
  getMarkers,
  getMediaItem,
  getThumbnailUrl,
  moveBoardItem,
  removeMediaFromBoardSection,
  reorderBoardSections,
  updateBoard,
  updateBoardSection
} = useMediaApi()
const { addToast } = useToasts()
const { slideshowState, enterSlideshow, exitSlideshow, updateCurrentMediaId } = useSlideshow()

const markersData = ref([])
const showBoardPicker = ref(false)
const showTagEditor = ref(false)
const showExportModal = ref(false)

const loading = ref(false)
const board = ref(null)
const editedName = ref('')
const isEditingBoardName = ref(false)
const boardNameInputRef = ref(null)
const boardMenuOpen = ref(false)
const boardMenuButtonRef = ref(null)
const boardMenuRef = ref(null)
const sectionEditingId = ref(null)
const scrollerRef = ref(null)
const sectionNames = reactive({})
const sectionInputRefs = new Map()
const sectionRefs = new Map()
const tileRefs = new Map()
let pendingItemDragCleanup = null
let pendingSectionFallbackCommit = null
const sectionDragCollapsed = ref(false) // delayed flag so collapse doesn't abort the drag
let autoScrollFrame = null
let autoScrollClientY = null
// --- Drag threshold & hysteresis tracking ---
let lastEnteredItemId = null   // ID of item pointer is currently over
let itemEntryEdge = null       // 'left' | 'right' — side the pointer entered from
let lastReflowPointer = null   // { x, y } at time of last item target change
let lastSectionReflowPointer = null // { x, y } at time of last section target change
let lastSectionPointerY = null     // tracks every dragover for direction detection
let scrollToSectionAfterDrop = null // section ID to scroll into view after drop
const HYSTERESIS_DISTANCE = 16 // px of actual pointer travel required after a reflow
const ITEM_THRESHOLD = 0.25    // 25% penetration into item before nudging
const containerWidth = ref(1200)
const dragState = reactive({
  item: null,
  section: null,
  targetSectionId: null,
  targetIndex: null,
  targetSide: null,
  sectionDragId: null,
  sectionTargetId: null,
  sectionTargetIndex: null,
  newSectionHover: false,
  removeFromBoardHover: false,
  deleteSectionHover: false,
  explodeSectionHover: false,
  committing: false
})
const slideshowItemCache = new Map()
const transparentDragImage = typeof Image !== 'undefined'
  ? (() => {
      const image = new Image()
      image.src = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=='
      return image
    })()
  : null

const {
  multiSelectMode,
  selectedItemIds,
  handleItemClick: handleMultiSelectClick,
  handleToggleSelection,
  lastClickedItem,
  lastClickedAction,
  selectAll,
  selectNone,
  removeFromSelection,
  selectedItems,
  activeMarkerIds,
  currentTagCounts,
  selectedItemSectionMap,
  createKeyboardHandler
} = useBoardMultiSelect({ board, markers: markersData })

const multiSelectKeyboardHandler = createKeyboardHandler()

function logBoardDnD(eventName, payload = {}) {
  const timestamp = new Date().toISOString()
  console.log(`[BoardDnD ${timestamp}] ${eventName}`, {
    boardId: board.value?.id ?? null,
    dragState: {
      item: dragState.item ? { ...dragState.item } : null,
      targetSectionId: dragState.targetSectionId,
      targetIndex: dragState.targetIndex,
      targetSide: dragState.targetSide,
      sectionDragId: dragState.sectionDragId,
      sectionTargetId: dragState.sectionTargetId,
      sectionTargetIndex: dragState.sectionTargetIndex,
      newSectionHover: dragState.newSectionHover,
      committing: dragState.committing
    },
    ...payload
  })
}

function aspectRatio(item) {
  const width = Math.max(item.width || 1, 1)
  const height = Math.max(item.height || 1, 1)
  return width / height
}

function buildRows(items, width) {
  const maxWidth = Math.max(width - 32, 320)
  const targetHeight = 190
  const gap = 12
  const rows = []
  let pending = []
  let ratioSum = 0

  const flush = (justify) => {
    if (pending.length === 0) return
    const rowGap = gap * Math.max(pending.length - 1, 0)
    const height = justify
      ? Math.max(120, Math.min(260, Math.floor((maxWidth - rowGap) / Math.max(ratioSum, 0.1))))
      : targetHeight
    const rowItems = pending.map((item) => ({
      ...item,
      _layoutWidth: Math.max(96, Math.floor(height * aspectRatio(item)))
    }))
    rows.push({ items: rowItems, height })
    pending = []
    ratioSum = 0
  }

  for (const item of items) {
    pending.push(item)
    ratioSum += aspectRatio(item)
    const estimatedWidth = ratioSum * targetHeight + gap * Math.max(pending.length - 1, 0)
    if (estimatedWidth >= maxWidth) flush(true)
  }
  flush(false)
  return rows
}

function getDraggedSourceItem() {
  if (!board.value || !dragState.item) return null
  const sourceSection = (board.value.sections || []).find((section) => section.id === dragState.item.fromSectionId)
  return (sourceSection?.items || []).find((item) => item.id === dragState.item.mediaId) || null
}

function getDisplayItemsForSection(section) {
  const items = [...(section.items || [])]
  if (!dragState.item || dragState.targetSectionId == null || dragState.targetIndex == null) {
    return items
  }

  // Filter out all dragged items (multi-drag or single)
  const dragIds = new Set(dragState.item.allMediaIds || [dragState.item.mediaId])
  const filtered = items.filter((item) => !dragIds.has(item.id))
  if (section.id !== dragState.targetSectionId) {
    return filtered
  }

  const sourceItem = getDraggedSourceItem()
  if (!sourceItem) return filtered

  let insertIndex = dragState.targetIndex
  if (section.id === dragState.item.fromSectionId) {
    // Adjust insert index for all dragged items that were before the target
    const removedBefore = items.filter((item, idx) => dragIds.has(item.id) && idx < insertIndex).length
    insertIndex -= removedBefore
  }

  const placeholder = {
    ...sourceItem,
    __placeholder: true,
    __placeholderKey: `placeholder-${section.id}-${dragState.item.mediaId}`,
    __sourceMediaId: sourceItem.id
  }
  filtered.splice(Math.max(0, Math.min(insertIndex, filtered.length)), 0, placeholder)
  return filtered
}

const visibleSections = computed(() => {
  if (!board.value) return []
  return board.value.sections || []
})

const displaySections = computed(() => {
  const sections = [...visibleSections.value]
  if (!dragState.sectionDragId || dragState.sectionTargetIndex == null) {
    return sections
  }
  const dragged = sections.find((section) => section.id === dragState.sectionDragId)
  if (!dragged) return sections
  const reordered = sections.filter((section) => section.id !== dragState.sectionDragId)
  const targetIndex = Math.max(0, Math.min(dragState.sectionTargetIndex, reordered.length))
  reordered.splice(targetIndex, 0, dragged)
  return reordered
})

const layoutRows = computed(() => {
  const map = {}
  for (const section of displaySections.value) {
    map[section.id] = buildRows(getDisplayItemsForSection(section), containerWidth.value)
  }
  return map
})

const draggedSectionIsDefault = computed(() => {
  if (!dragState.sectionDragId || !board.value) return false
  const section = (board.value.sections || []).find((s) => s.id === dragState.sectionDragId)
  return Boolean(section?.is_default)
})

const totalAssetCount = computed(() => (board.value?.sections || []).reduce((sum, section) => sum + (section.item_count || section.items.length || 0), 0))
const boardSummaryText = computed(() => {
  const itemText = formatCount(totalAssetCount.value, 'item')
  const sectionCount = visibleSections.value.length
  return sectionCount > 1 ? `${itemText} · ${formatCount(sectionCount, 'section')}` : itemText
})
const pitStyle = computed(() => ({
  backgroundColor: resolvedTheme.value === 'light' ? 'rgba(255,255,255,0.98)' : 'rgba(255,255,255,0.06)',
  backgroundImage: `radial-gradient(circle at 1px 1px, ${resolvedTheme.value === 'light' ? 'rgba(0,0,0,0.14)' : 'rgba(255,255,255,0.14)'} 1px, transparent 0)`,
  backgroundSize: '16px 16px'
}))
const slideshowItems = computed(() => (
  displaySections.value.flatMap((section) => (section.items || []).map((item) => ({
    ...item,
    section_id: section.id
  })))
))

async function loadBoard() {
  // Only show loading spinner on initial load, not on refreshes
  const isInitialLoad = !board.value
  if (isInitialLoad) loading.value = true
  try {
    board.value = await getBoard(Number(route.params.id))
    editedName.value = board.value.name || ''
    isEditingBoardName.value = false
    for (const section of board.value.sections || []) {
      sectionNames[section.id] = section.name || ''
    }
  } finally {
    loading.value = false
  }
}

function measureWidth() {
  containerWidth.value = scrollerRef.value?.clientWidth || 1200
}

function stopAutoScroll() {
  autoScrollClientY = null
  if (autoScrollFrame != null) {
    cancelAnimationFrame(autoScrollFrame)
    autoScrollFrame = null
  }
}

function runAutoScroll() {
  autoScrollFrame = null
  const scroller = scrollerRef.value
  if (!scroller || autoScrollClientY == null) return

  const rect = scroller.getBoundingClientRect()
  const threshold = 96
  let delta = 0

  if (autoScrollClientY < rect.top + threshold) {
    const ratio = 1 - ((autoScrollClientY - rect.top) / threshold)
    delta = -Math.ceil(Math.max(6, ratio * 24))
  } else if (autoScrollClientY > rect.bottom - threshold) {
    const ratio = 1 - ((rect.bottom - autoScrollClientY) / threshold)
    delta = Math.ceil(Math.max(6, ratio * 24))
  }

  if (delta !== 0) {
    scroller.scrollTop += delta
    autoScrollFrame = requestAnimationFrame(runAutoScroll)
  }
}

function updateAutoScroll(event) {
  autoScrollClientY = event?.clientY ?? null
  if (autoScrollFrame == null && autoScrollClientY != null) {
    autoScrollFrame = requestAnimationFrame(runAutoScroll)
  }
}

async function loadSlideshowItem(item) {
  if (!item?.id) return item
  if (slideshowItemCache.has(item.id)) {
    return slideshowItemCache.get(item.id)
  }

  try {
    const fullItem = await getMediaItem(item.id)
    slideshowItemCache.set(item.id, fullItem)
    return fullItem
  } catch (error) {
    console.error('Failed to load board slideshow item:', error)
    return item
  }
}

function createBoardSlideshowPageProvider(items) {
  return async (pageNumber, pageSize) => {
    const start = pageNumber * pageSize
    const pageItems = items.slice(start, start + pageSize)
    return Promise.all(pageItems.map(loadSlideshowItem))
  }
}

function openItemSlideshow(mediaId) {
  if (dragState.item || dragState.sectionDragId) return

  const items = slideshowItems.value
  const startIndex = items.findIndex((item) => item.id === mediaId)
  if (startIndex === -1) return

  enterSlideshow({
    totalCount: items.length,
    startIndex,
    pageProvider: createBoardSlideshowPageProvider(items)
  })
}

function handleCheckboxClick(section, item, event) {
  if (event?.shiftKey && lastClickedItem.value) {
    handleMultiSelectClick(section, item, event)
    return
  }
  const wasSelected = selectedItemIds.value.includes(item.id)
  lastClickedAction.value = wasSelected ? 'deselect' : 'select'
  handleToggleSelection(item.id)
  lastClickedItem.value = { sectionId: section.id, itemId: item.id }
}

function handleItemClick(section, item, event) {
  const handled = handleMultiSelectClick(section, item, event)
  if (!handled) {
    openItemSlideshow(item.id)
  }
}

function handleItemContextMenu(section, item, event) {
  const ids = multiSelectMode.value && selectedItemIds.value.includes(item.id)
    ? [...selectedItemIds.value]
    : [item.id]
  const items = ids.length > 1 ? selectedItems.value : []
  mediaContextMenu.show({
    event,
    mediaId: item.id,
    mediaIds: ids,
    selectedItems: items,
    fileHash: item.file_hash,
    inBoard: true,
    boardSectionId: section.id
  })
}

function formatCount(count, singular) {
  return `${count} ${count === 1 ? singular : `${singular}s`}`
}

function getSectionLabelWidth(section) {
  const text = (sectionEditingId.value === section.id ? sectionNames[section.id] : section.name) || ''
  const minWidth = 112
  const maxWidth = 288
  const estimatedWidth = 32 + (text.length * 7.25)
  const clampedWidth = Math.max(minWidth, Math.min(maxWidth, estimatedWidth))
  return `${clampedWidth}px`
}

async function saveBoardName() {
  if (!board.value) return
  isEditingBoardName.value = false
  if ((editedName.value || '') === (board.value.name || '')) return
  board.value = await updateBoard(board.value.id, { name: editedName.value })
}

function startBoardNameEdit() {
  isEditingBoardName.value = true
  nextTick(() => {
    boardNameInputRef.value?.focus()
    boardNameInputRef.value?.select?.()
  })
}

function cancelBoardNameEdit() {
  editedName.value = board.value?.name || ''
  isEditingBoardName.value = false
}

function handleBoardNameBlur() {
  saveBoardName()
}

async function saveSection(section) {
  const nextName = sectionNames[section.id] || null
  const updated = await updateBoardSection(section.id, { name: nextName })
  section.name = updated.name
  section.is_default = updated.is_default
  sectionEditingId.value = null
}

function startSectionEdit(section) {
  sectionEditingId.value = section.id
  nextTick(() => {
    const input = sectionInputRefs.get(section.id)
    input?.focus()
    input?.select?.()
  })
}

function cancelSectionEdit(section) {
  sectionNames[section.id] = section.name || ''
  sectionEditingId.value = null
}

async function deleteSection(section) {
  await deleteBoardSection(section.id)
  await loadBoard()
}

async function deleteCurrentBoard() {
  if (!board.value) return
  const id = board.value.id
  try {
    await deleteBoard(id)
  } catch (err) {
    console.error('Failed to delete board:', err)
    addToast('Failed to delete board', 'error', 5000)
    return
  }
  router.push({ name: 'boards' })
  addToast('Deleted 1 board', 'info', 5000, {
    label: 'Undo',
    onClick: async () => {
      try {
        await restoreBoard(id)
      } catch (err) {
        console.error('Failed to restore board:', err)
        addToast('Failed to restore board', 'error', 5000)
      }
    }
  })
}

function toggleBoardMenu() {
  boardMenuOpen.value = !boardMenuOpen.value
}

async function handleBoardMenuDeleteBoard() {
  boardMenuOpen.value = false
  await deleteCurrentBoard()
}

function handleDocumentClick(event) {
  const target = event.target
  if (boardMenuOpen.value && !boardMenuRef.value?.contains(target) && !boardMenuButtonRef.value?.contains(target)) {
    boardMenuOpen.value = false
  }
}

function handleWindowKeydown(event) {
  // Escape during drag: cancel drag and revert
  if (event.key === 'Escape' && (dragState.item || dragState.sectionDragId)) {
    event.preventDefault()
    cancelAllDrags()
    return
  }

  // Let multi-select handle Escape and Cmd+A first
  if (multiSelectKeyboardHandler(event)) return

  if (event.key === 'Escape') {
    boardMenuOpen.value = false
  }
}

// --- Multi-select action handlers ---

async function handleBulkRemoveFromBoard() {
  if (!board.value || selectedItemIds.value.length === 0) return
  const ids = [...selectedItemIds.value]
  selectNone()
  await bulkRemoveFromBoard(board.value.id, ids)
  await loadBoard()
}

async function handleMoveToSection(sectionId) {
  if (!board.value || selectedItemIds.value.length === 0) return
  const ids = [...selectedItemIds.value]
  selectNone()
  await bulkMoveBoardItems(board.value.id, ids, sectionId)
  await loadBoard()
}

async function handleMoveToNewSection() {
  if (!board.value || selectedItemIds.value.length === 0) return
  const ids = [...selectedItemIds.value]
  const created = await createBoardSection(board.value.id, '')
  selectNone()
  await bulkMoveBoardItems(board.value.id, ids, created.id)
  await loadBoard()
}

async function handleCreateSectionFromSelection() {
  await handleMoveToNewSection()
}

async function handleToggleMarker({ markerId, add }) {
  if (selectedItemIds.value.length === 0) return
  await bulkMarkerOperation(selectedItemIds.value, markerId, add)
}

function handleTagsSaved() {
  showTagEditor.value = false
}

function handleBoardsAdded() {
  showBoardPicker.value = false
}

async function handleBulkMoveToTrash() {
  if (selectedItemIds.value.length === 0) return
  const ids = [...selectedItemIds.value]
  selectNone()
  await bulkDeleteMedia(ids)
  await loadBoard()
}

function handleExport() {
  showExportModal.value = true
}

function onItemDragStart(section, item, event) {
  if (!event.dataTransfer) return


  // Determine if this is a multi-drag
  const isMultiDrag = multiSelectMode.value && selectedItemIds.value.includes(item.id) && selectedItemIds.value.length > 1
  const allDragIds = isMultiDrag ? [...selectedItemIds.value] : null

  dragState.item = { mediaId: item.id, fromSectionId: section.id, allMediaIds: allDragIds }
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('application/x-media-id', String(item.id))
  event.dataTransfer.setData('application/x-board-drag', JSON.stringify({
    mediaId: item.id,
    fromSectionId: section.id,
    allMediaIds: allDragIds
  }))
  if (allDragIds) {
    event.dataTransfer.setData('application/x-media-ids', JSON.stringify(allDragIds))
  }
  if (item?.file_hash) {
    event.dataTransfer.setData('application/x-file-hash', item.file_hash)
  }

  const thumbnailIdentifier = item?.file_hash || item?.id
  if (!thumbnailIdentifier) return

  const thumbnailUrl = getThumbnailUrl(thumbnailIdentifier, 128)
  const fileFormat = item.file_format || ''
  const itemIsVideo = !!(item.file_format && ['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg'].includes(item.file_format))
  logBoardDnD('item-dragstart', {
    mediaId: item.id,
    fromSectionId: section.id,
    fileHash: item.file_hash ?? null,
    multiDrag: isMultiDrag,
    allMediaIds: allDragIds
  })
  createDragPreview(event, thumbnailUrl, item.id, fileFormat, itemIsVideo, allDragIds)
}

function getDraggedBoardPayload(event) {
  try {
    const raw = event?.dataTransfer?.getData('application/x-board-drag')
    if (raw) {
      const parsed = JSON.parse(raw)
      if (parsed?.mediaId != null && parsed?.fromSectionId != null) {
        return {
          mediaId: Number(parsed.mediaId),
          fromSectionId: Number(parsed.fromSectionId),
          allMediaIds: parsed.allMediaIds || null
        }
      }
    }
  } catch {
  }

  if (dragState.item?.mediaId != null && dragState.item?.fromSectionId != null) {
    return {
      mediaId: Number(dragState.item.mediaId),
      fromSectionId: Number(dragState.item.fromSectionId),
      allMediaIds: dragState.item.allMediaIds || null
    }
  }

  return null
}

function resetItemDragState() {
  dragState.item = null
  dragState.targetSectionId = null
  dragState.targetIndex = null
  dragState.targetSide = null
  dragState.newSectionHover = false
  dragState.removeFromBoardHover = false
  lastEnteredItemId = null
  itemEntryEdge = null
  lastReflowPointer = null
  handleDragPreviewEnd()
}

function resetSectionDragState() {
  const scrollTarget = scrollToSectionAfterDrop
  scrollToSectionAfterDrop = null
  dragState.sectionDragId = null
  dragState.sectionTargetId = null
  dragState.sectionTargetIndex = null
  dragState.deleteSectionHover = false
  dragState.explodeSectionHover = false
  lastSectionReflowPointer = null
  lastSectionPointerY = null
  sectionDragCollapsed.value = false
  cleanupSectionDragPreview()
  if (scrollTarget) {
    nextTick(() => {
      const el = sectionRefs.get(scrollTarget)
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    })
  }
}

function cancelAllDrags() {
  stopAutoScroll()
  if (pendingItemDragCleanup) {
    clearTimeout(pendingItemDragCleanup)
    pendingItemDragCleanup = null
  }
  if (pendingSectionFallbackCommit) {
    clearTimeout(pendingSectionFallbackCommit)
    pendingSectionFallbackCommit = null
  }
  if (dragState.item && !dragState.committing) {
    logBoardDnD('drag-cancelled')
    resetItemDragState()
  }
  if (dragState.sectionDragId && !dragState.committing) {
    logBoardDnD('section-drag-cancelled')
    resetSectionDragState()
  }
}

function onItemDragEnd() {
  logBoardDnD('item-dragend')
  stopAutoScroll()

  if (pendingItemDragCleanup) {
    clearTimeout(pendingItemDragCleanup)
    pendingItemDragCleanup = null
  }

  // Always reset drag state after a short delay.
  // For successful drops, finalizeItemDrop already resets state synchronously
  // in its try block and again in finally, so this is a no-op.
  // For aborts (no drop event), this is the only cleanup path.
  pendingItemDragCleanup = setTimeout(() => {
    pendingItemDragCleanup = null
    logBoardDnD('item-dragend-cleanup')
    resetItemDragState()
  }, 100)
}

function onSectionDragStart(section, event) {
  if (event.target?.closest?.('input, button, [data-board-item="true"]')) {
    event.preventDefault()
    return
  }

  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('text/plain', String(section.id))
  createSectionDragPreview(event, section.name || '', resolvedTheme.value === 'light' ? 'light' : 'dark')
  dragState.sectionDragId = section.id
  dragState.sectionTargetId = section.id
  dragState.sectionTargetIndex = null
  // Defer visual collapse so the browser captures the drag image before layout shifts
  requestAnimationFrame(() => {
    sectionDragCollapsed.value = true
  })
}

function onSectionDragEnd() {
  stopAutoScroll()

  if (pendingSectionFallbackCommit) {
    clearTimeout(pendingSectionFallbackCommit)
    pendingSectionFallbackCommit = null
  }

  pendingSectionFallbackCommit = setTimeout(async () => {
    pendingSectionFallbackCommit = null
    if (dragState.sectionDragId && dragState.sectionTargetIndex != null) {
      logBoardDnD('section-dragend-fallback-commit')
      await commitSectionDrop()
    } else {
      logBoardDnD('section-dragend-cleanup')
    }
    resetSectionDragState()
  }, 100)
}

function setSectionInputRef(sectionId, el) {
  if (el) {
    sectionInputRefs.set(sectionId, el)
  } else {
    sectionInputRefs.delete(sectionId)
  }
}

function setSectionRef(sectionId, el) {
  if (el) {
    sectionRefs.set(sectionId, el)
  } else {
    sectionRefs.delete(sectionId)
  }
}

function setTileRef(sectionId, item, el) {
  if (item?.__placeholder) return
  let sectionMap = tileRefs.get(sectionId)
  if (!sectionMap) {
    sectionMap = new Map()
    tileRefs.set(sectionId, sectionMap)
  }
  if (el) {
    sectionMap.set(item.id, el)
  } else {
    sectionMap.delete(item.id)
    if (sectionMap.size === 0) {
      tileRefs.delete(sectionId)
    }
  }
}

function getPointerTargetIndex(section, event) {
  const items = section.items || []
  if (items.length === 0) return 0

  const sectionMap = tileRefs.get(section.id)
  if (!sectionMap || sectionMap.size === 0) return items.length

  const positioned = items
    .map((item, index) => {
      const el = sectionMap.get(item.id)
      if (!el) return null
      const rect = el.getBoundingClientRect()
      return {
        id: item.id,
        index,
        top: rect.top,
        left: rect.left,
        right: rect.right,
        bottom: rect.bottom,
        centerX: rect.left + (rect.width / 2),
        centerY: rect.top + (rect.height / 2)
      }
    })
    .filter(Boolean)

  if (positioned.length === 0) return items.length

  const pointerY = event.clientY
  const pointerX = event.clientX
  const rowTolerance = 24
  const rows = []

  for (const tile of positioned.sort((a, b) => (a.top - b.top) || (a.left - b.left))) {
    const lastRow = rows[rows.length - 1]
    if (!lastRow || Math.abs(lastRow.centerY - tile.centerY) > rowTolerance) {
      rows.push({ centerY: tile.centerY, tiles: [tile] })
    } else {
      lastRow.tiles.push(tile)
      lastRow.centerY = lastRow.tiles.reduce((sum, entry) => sum + entry.centerY, 0) / lastRow.tiles.length
    }
  }

  let targetRow = rows[0]
  let bestDistance = Math.abs(pointerY - rows[0].centerY)
  for (const row of rows.slice(1)) {
    const distance = Math.abs(pointerY - row.centerY)
    if (distance < bestDistance) {
      bestDistance = distance
      targetRow = row
    }
  }

  const rowTiles = [...targetRow.tiles].sort((a, b) => a.left - b.left)
  for (const tile of rowTiles) {
    if (pointerX < tile.centerX) return tile.index
  }

  const lastTile = rowTiles[rowTiles.length - 1]
  return lastTile.index + 1
}

function updateSectionTarget(event) {
  if (!dragState.sectionDragId) return

  const sections = visibleSections.value.filter((entry) => entry.id !== dragState.sectionDragId)
  if (sections.length === 0) return

  const pointerY = event.clientY
  const movingUp = lastSectionPointerY != null ? pointerY < lastSectionPointerY : false
  lastSectionPointerY = pointerY
  let insertIndex = sections.length

  for (let index = 0; index < sections.length; index += 1) {
    const sectionEl = sectionRefs.get(sections[index].id)
    const rect = sectionEl?.getBoundingClientRect?.()
    if (!rect) continue
    // 25% threshold in the direction of movement:
    // moving down → enter from top, swap at 25% from top
    // moving up → enter from bottom, swap at 25% from bottom (75% from top)
    const threshold = movingUp
      ? rect.top + rect.height * 0.75
      : rect.top + rect.height * 0.25
    if (pointerY < threshold) {
      insertIndex = index
      break
    }
  }

  if (dragState.sectionTargetIndex !== insertIndex) {
    // Displacement hysteresis for sections
    if (lastSectionReflowPointer != null) {
      const dy = pointerY - lastSectionReflowPointer.y
      if (dy * dy < HYSTERESIS_DISTANCE * HYSTERESIS_DISTANCE) {
        return
      }
    }
    dragState.sectionTargetIndex = insertIndex
    dragState.sectionTargetId = sections[Math.min(insertIndex, sections.length - 1)]?.id ?? null
    lastSectionReflowPointer = { x: event.clientX, y: pointerY }
  }
}

function handleSectionHeaderDragOver(section, event) {
  updateSectionTarget(event)
}

function handleSectionContainerDragOver(section, event) {
  if (dragState.sectionDragId) {
    updateAutoScroll(event)
    updateSectionTarget(event)
    return
  }
  handleSectionDragOver(section, section.items.length, event)
}

async function commitSectionDrop() {
  if (dragState.committing) return
  if (!dragState.sectionDragId || !board.value) return
  if (dragState.sectionTargetIndex == null) return
  if (pendingSectionFallbackCommit) {
    clearTimeout(pendingSectionFallbackCommit)
    pendingSectionFallbackCommit = null
  }
  const droppedSectionId = dragState.sectionDragId
  const ordered = displaySections.value.map((entry) => entry.id).filter((id) => id !== droppedSectionId)
  const index = Math.max(0, Math.min(dragState.sectionTargetIndex, ordered.length))
  ordered.splice(index, 0, droppedSectionId)
  applyLocalSectionReorder(ordered)
  dragState.sectionDragId = null
  dragState.sectionTargetId = null
  dragState.sectionTargetIndex = null
  scrollToSectionAfterDrop = droppedSectionId
  try {
    await reorderBoardSections(board.value.id, ordered)
  } catch (error) {
    await loadBoard()
    throw error
  }
}

async function handleSectionContainerDrop(section, event) {
  if (dragState.sectionDragId) {
    stopAutoScroll()
    await commitSectionDrop()
    return
  }

  const payload = getDraggedBoardPayload(event)
  if (!payload) return
  await commitDrop(payload, section, section.items.length)
}

function handleSectionDragOver(section, targetIndex, event) {
  if (!dragState.item) return
  setDragTarget(section.id, targetIndex, event?.clientX, event?.clientY)
  dragState.targetSide = 'after'
}

function handleSectionBodyDragOver(section, event) {
  if (dragState.sectionDragId) {
    updateAutoScroll(event)
    updateSectionTarget(event)
    return
  }
  if (!dragState.item) return
  updateAutoScroll(event)
  const target = event.target
  if (target?.closest?.('[data-board-item="true"]')) return
  // Pointer is in empty space between items — reset item entry tracking
  lastEnteredItemId = null
  itemEntryEdge = null
  setDragTarget(section.id, getPointerTargetIndex(section, event), event.clientX, event.clientY)
  dragState.targetSide = 'after'
}

function handleItemOrPlaceholderDragOver(section, item, event) {
  if (item.__placeholder) {
    // Pointer is over the drop-preview placeholder — the current target is
    // already correct (it placed the placeholder here). Just keep auto-scroll
    // running and clear entry tracking so moving off the placeholder onto a
    // real item gets fresh edge detection.
    updateAutoScroll(event)
    lastEnteredItemId = null
    itemEntryEdge = null
    return
  }
  handleItemDragOver(section, item, event)
}

function handleItemOrPlaceholderDrop(section, item, event) {
  if (item.__placeholder) {
    // Delegate to section body drop — placeholder shouldn't eat the drop event
    commitSectionBodyDrop(section, event)
    return
  }
  commitItemDrop(section, item, event)
}

function setDragTarget(sectionId, index, pointerX, pointerY) {
  if (dragState.targetSectionId === sectionId && dragState.targetIndex === index) {
    return false
  }

  // Displacement-based hysteresis: require actual pointer travel after a
  // reflow before allowing another. This prevents oscillation when items
  // shift under a stationary pointer (different-sized items reflowing).
  // Section changes bypass hysteresis so cross-section drags feel snappy.
  const sectionChanged = dragState.targetSectionId !== sectionId
  if (!sectionChanged && lastReflowPointer != null && pointerX != null && pointerY != null) {
    const dx = pointerX - lastReflowPointer.x
    const dy = pointerY - lastReflowPointer.y
    if (dx * dx + dy * dy < HYSTERESIS_DISTANCE * HYSTERESIS_DISTANCE) {
      return false
    }
  }

  dragState.targetSectionId = sectionId
  dragState.targetIndex = index
  if (pointerX != null && pointerY != null) {
    lastReflowPointer = { x: pointerX, y: pointerY }
  }
  return true
}

// After a target change triggers a reflow that changes row heights, adjust
// scrollTop so the anchor element's nearest Y edge stays at the same screen
// position. The cursor is the origin -- the layout reforms around it.
function compensateScrollAfterReflow(anchorEl, anchorEdge, anchorY) {
  nextTick(() => {
    const newRect = anchorEl.getBoundingClientRect()
    const newAnchorY = anchorEdge === 'top' ? newRect.top : newRect.bottom
    const delta = newAnchorY - anchorY
    if (Math.abs(delta) > 0.5 && scrollerRef.value) {
      scrollerRef.value.scrollTop += delta
    }
  })
}

function handleItemDragOver(section, item, event) {
  if (!dragState.item) return
  updateAutoScroll(event)

  const el = event.currentTarget
  const rect = el.getBoundingClientRect()
  const pointerX = event.clientX
  const pointerY = event.clientY

  // Track entry edge when the pointer enters a new item's bounds.
  // The entry edge determines which 25% threshold to check.
  if (lastEnteredItemId !== item.id) {
    lastEnteredItemId = item.id
    const fromLeft = pointerX - rect.left
    const fromRight = rect.right - pointerX
    itemEntryEdge = fromLeft <= fromRight ? 'left' : 'right'
  }

  const sectionItems = section.items || []
  const rawIndex = sectionItems.findIndex((entry) => entry.id === item.id)

  // 25% penetration from entry edge triggers the nudge.
  // Enter from left (moving right) → item kicks left → insert AFTER.
  // Enter from right (moving left) → item kicks right → insert BEFORE.
  const threshold = rect.width * ITEM_THRESHOLD
  let changed = false
  if (itemEntryEdge === 'left') {
    if (pointerX >= rect.left + threshold) {
      changed = setDragTarget(section.id, rawIndex + 1, pointerX, pointerY)
      dragState.targetSide = 'after'
    }
  } else {
    if (pointerX <= rect.right - threshold) {
      changed = setDragTarget(section.id, rawIndex, pointerX, pointerY)
      dragState.targetSide = 'before'
    }
  }

  // When the target changes, row heights may reflow. Anchor the nearest Y
  // edge of this item so the layout reforms around the cursor position.
  if (changed) {
    const distToTop = Math.abs(pointerY - rect.top)
    const distToBottom = Math.abs(pointerY - rect.bottom)
    const anchorEdge = distToTop <= distToBottom ? 'top' : 'bottom'
    const anchorY = anchorEdge === 'top' ? rect.top : rect.bottom
    compensateScrollAfterReflow(el, anchorEdge, anchorY)
  }
}

async function commitItemDrop(section, item, event) {
  if (dragState.committing) return
  stopAutoScroll()
  const payload = getDraggedBoardPayload(event)
  if (!payload) return
  logBoardDnD('item-drop', {
    payload,
    sectionId: section.id,
    itemId: item.id
  })
  // Use the last settled target from dragover (threshold + hysteresis already applied)
  const targetSectionId = dragState.targetSectionId ?? section.id
  const targetIndex = dragState.targetIndex ?? 0
  await finalizeItemDrop(payload, targetSectionId, targetIndex)
}

async function commitSectionBodyDrop(section, event) {
  if (dragState.sectionDragId) {
    stopAutoScroll()
    await commitSectionDrop()
    return
  }
  if (dragState.committing) return
  stopAutoScroll()
  const payload = getDraggedBoardPayload(event)
  if (!payload) return
  const target = event.target
  if (target?.closest?.('[data-board-item="true"]')) return
  const targetIndex = getPointerTargetIndex(section, event)
  logBoardDnD('section-body-drop', {
    payload,
    sectionId: section.id,
    targetIndex
  })
  await commitDrop(payload, section, targetIndex)
}

async function commitDrop(payload, section, targetIndex) {
  if (dragState.committing) return
  dragState.targetSectionId = section.id
  dragState.targetIndex = targetIndex
  logBoardDnD('commit-drop', {
    payload,
    sectionId: section.id,
    targetIndex
  })
  await finalizeItemDrop(payload, section.id, targetIndex)
}

async function finalizeItemDrop(payload, targetSectionId, rawTargetIndex) {
  if (dragState.committing) return
  if (!board.value || !payload || targetSectionId == null || rawTargetIndex == null) return
  const item = { ...payload }
  dragState.committing = true

  // Adjust index for same-section moves: targetIndex was computed against
  // the original items array (including the dragged item). After removing
  // the dragged item, indices shift down by 1 if the item was before the target.
  let targetIndex = rawTargetIndex
  if (item.fromSectionId === targetSectionId) {
    const section = board.value.sections.find((s) => s.id === item.fromSectionId)
    if (section) {
      const originalIndex = (section.items || []).findIndex((i) => i.id === item.mediaId)
      if (originalIndex !== -1 && originalIndex < rawTargetIndex) {
        targetIndex = rawTargetIndex - 1
      }
    }
  }

  try {
    logBoardDnD('finalize-drop-start', {
      payload: item,
      targetSectionId,
      rawTargetIndex,
      targetIndex
    })
    if (pendingItemDragCleanup) {
      clearTimeout(pendingItemDragCleanup)
      pendingItemDragCleanup = null
    }
    const isMultiDrag = item.allMediaIds && item.allMediaIds.length > 1
    if (!isMultiDrag) {
      applyLocalItemMove(item.mediaId, item.fromSectionId, targetSectionId, targetIndex)
    }
    dragState.item = null
    dragState.targetSectionId = null
    dragState.targetIndex = null
    dragState.targetSide = null
    dragState.newSectionHover = false
    dragState.removeFromBoardHover = false
    await nextTick()
    handleDragPreviewEnd()
    if (isMultiDrag) {
      await bulkMoveBoardItems(board.value.id, item.allMediaIds, targetSectionId)
      selectNone()
      await loadBoard()
    } else {
      await moveBoardItem(
        board.value.id,
        item.mediaId,
        item.fromSectionId,
        targetSectionId,
        targetIndex
      )
    }
    logBoardDnD('finalize-drop-success', {
      payload: item,
      targetSectionId,
      targetIndex
    })
  } catch (error) {
    logBoardDnD('finalize-drop-error', {
      payload: item,
      targetSectionId,
      targetIndex,
      error: error?.message || String(error)
    })
    await loadBoard()
    handleDragPreviewEnd()
    throw error
  } finally {
    dragState.committing = false
    // Safety net: ensure all item drag state is fully cleared
    dragState.item = null
    dragState.targetSectionId = null
    dragState.targetIndex = null
    dragState.targetSide = null
    dragState.newSectionHover = false
    dragState.removeFromBoardHover = false
  }
}

function handleNewSectionDragLeave(event) {
  const nextTarget = event.relatedTarget
  if (nextTarget && event.currentTarget?.contains?.(nextTarget)) return
  dragState.newSectionHover = false
  stopAutoScroll()
}

function handleNewSectionDragOver(event) {
  dragState.newSectionHover = true
  updateAutoScroll(event)
}

function handleRemoveFromBoardDragLeave(event) {
  const nextTarget = event.relatedTarget
  if (nextTarget && event.currentTarget?.contains?.(nextTarget)) return
  dragState.removeFromBoardHover = false
}

function handleRemoveFromBoardDragOver(event) {
  dragState.removeFromBoardHover = true
}

async function removeFromBoardDrop(event) {
  if (dragState.committing) return
  const payload = getDraggedBoardPayload(event)
  if (!payload || !board.value) return
  dragState.committing = true
  try {
    if (pendingItemDragCleanup) {
      clearTimeout(pendingItemDragCleanup)
      pendingItemDragCleanup = null
    }
    const isMultiDrag = payload.allMediaIds && payload.allMediaIds.length > 1
    if (isMultiDrag) {
      await bulkRemoveFromBoard(board.value.id, payload.allMediaIds)
      selectNone()
    } else {
      await removeMediaFromBoardSection(payload.fromSectionId, payload.mediaId)
    }
    dragState.item = null
    dragState.targetSectionId = null
    dragState.targetIndex = null
    dragState.targetSide = null
    dragState.removeFromBoardHover = false
    handleDragPreviewEnd()
    await loadBoard()
  } catch (error) {
    await loadBoard()
    handleDragPreviewEnd()
    throw error
  } finally {
    dragState.committing = false
    dragState.item = null
    dragState.targetSectionId = null
    dragState.targetIndex = null
    dragState.targetSide = null
    dragState.removeFromBoardHover = false
  }
}

function handleDeleteSectionDragLeave(event) {
  const nextTarget = event.relatedTarget
  if (nextTarget && event.currentTarget?.contains?.(nextTarget)) return
  dragState.deleteSectionHover = false
}

function handleExplodeSectionDragLeave(event) {
  const nextTarget = event.relatedTarget
  if (nextTarget && event.currentTarget?.contains?.(nextTarget)) return
  dragState.explodeSectionHover = false
}

async function deleteSectionDrop() {
  if (!board.value || !dragState.sectionDragId) return
  const sectionId = dragState.sectionDragId
  const section = (board.value.sections || []).find((s) => s.id === sectionId)
  if (!section) {
    resetSectionDragState()
    return
  }
  try {
    await deleteBoardSection(sectionId)
  } finally {
    resetSectionDragState()
    await loadBoard()
  }
}

async function explodeSectionDrop() {
  if (!board.value || !dragState.sectionDragId) return
  const sectionId = dragState.sectionDragId
  const section = (board.value.sections || []).find((s) => s.id === sectionId)
  if (!section || section.is_default) {
    resetSectionDragState()
    return
  }
  const defaultSection = (board.value.sections || []).find((entry) => entry.is_default)
  if (!defaultSection) {
    resetSectionDragState()
    return
  }
  const items = [...(section.items || [])]
  try {
    if (items.length > 0) {
      // Bulk-move auto-deletes the empty source section via _delete_section_if_empty.
      await bulkMoveBoardItems(board.value.id, items.map((item) => item.id), defaultSection.id)
    } else {
      await deleteBoardSection(sectionId)
    }
  } finally {
    resetSectionDragState()
    await loadBoard()
  }
}

function syncSectionCounts() {
  if (!board.value?.sections) return
  for (const section of board.value.sections) {
    section.item_count = section.items?.length || 0
  }
}

function applyLocalItemMove(mediaId, fromSectionId, toSectionId, targetIndex) {
  if (!board.value?.sections) return
  const sourceSection = board.value.sections.find((section) => section.id === fromSectionId)
  const targetSection = board.value.sections.find((section) => section.id === toSectionId)
  if (!sourceSection || !targetSection) return

  const sourceItems = [...(sourceSection.items || [])]
  const sourceIndex = sourceItems.findIndex((item) => item.id === mediaId)
  if (sourceIndex === -1) return

  const [movedItem] = sourceItems.splice(sourceIndex, 1)
  sourceSection.items = sourceItems

  const targetItemsBase = sourceSection.id === targetSection.id
    ? sourceItems
    : [...(targetSection.items || [])]
  const targetItems = targetItemsBase.filter((item) => item.id !== mediaId)
  const clampedIndex = Math.max(0, Math.min(targetIndex, targetItems.length))
  targetItems.splice(clampedIndex, 0, movedItem)
  targetSection.items = targetItems

  if (fromSectionId !== toSectionId && !sourceSection.is_default && sourceSection.items.length === 0) {
    board.value.sections = board.value.sections.filter((section) => section.id !== fromSectionId)
  }

  syncSectionCounts()
  board.value = {
    ...board.value,
    sections: [...board.value.sections]
  }
}

function insertLocalSection(section) {
  if (!board.value?.sections) return
  board.value = {
    ...board.value,
    sections: [...board.value.sections, { ...section, items: [], item_count: 0 }]
  }
}

function applyLocalSectionReorder(orderedIds) {
  if (!board.value?.sections) return
  const sectionMap = new Map(board.value.sections.map((section) => [section.id, section]))
  const reordered = orderedIds
    .map((id) => sectionMap.get(id))
    .filter(Boolean)

  if (reordered.length !== board.value.sections.length) return

  board.value = {
    ...board.value,
    sections: reordered
  }
}

async function createSectionFromDrop(event) {
  if (dragState.committing) return
  const payload = getDraggedBoardPayload(event)
  if (!payload || !board.value) return
  dragState.committing = true
  const item = { ...payload }
  try {
    logBoardDnD('create-section-drop-start', { payload: item })
    if (pendingItemDragCleanup) {
      clearTimeout(pendingItemDragCleanup)
      pendingItemDragCleanup = null
    }
    const createdSection = await createBoardSection(board.value.id, '')
    const isMultiDrag = item.allMediaIds && item.allMediaIds.length > 1
    if (isMultiDrag) {
      await bulkMoveBoardItems(board.value.id, item.allMediaIds, createdSection.id)
      selectNone()
    } else {
      insertLocalSection(createdSection)
      await moveBoardItem(board.value.id, item.mediaId, item.fromSectionId, createdSection.id, 0)
      applyLocalItemMove(item.mediaId, item.fromSectionId, createdSection.id, 0)
    }
    dragState.item = null
    dragState.targetSectionId = null
    dragState.targetIndex = null
    dragState.targetSide = null
    dragState.newSectionHover = false
    dragState.removeFromBoardHover = false
    handleDragPreviewEnd()
    if (isMultiDrag) {
      await loadBoard()
    }
    logBoardDnD('create-section-drop-success', {
      payload: item,
      newSectionId: createdSection.id
    })
    await nextTick()
    const input = sectionInputRefs.get(createdSection.id)
    if (input) {
      input.focus()
      input.select?.()
    }
  } catch (error) {
    logBoardDnD('create-section-drop-error', {
      payload: item,
      error: error?.message || String(error)
    })
    await loadBoard()
    handleDragPreviewEnd()
    throw error
  } finally {
    dragState.committing = false
    dragState.item = null
    dragState.targetSectionId = null
    dragState.targetIndex = null
    dragState.targetSide = null
    dragState.newSectionHover = false
    dragState.removeFromBoardHover = false
  }
}

watch(() => route.params.id, loadBoard)

const unsubBoardChanged = on('board_items_changed', (data) => {
  if (data.board_id === board.value?.id) loadBoard()
})

const unsubMediaUpdated = on('media_updated', (data) => {
  const { media_id, fields, media } = data
  if (!board.value || !media_id || !media) return
  if (!fields.includes('markers') && !fields.includes('tags')) return
  for (const section of board.value.sections || []) {
    for (const item of section.items || []) {
      if (item.id === media_id) {
        if (fields.includes('markers')) item.markers = media.markers || []
        if (fields.includes('tags')) item.tags = media.tags || []
      }
    }
  }
})

onMounted(async () => {
  await loadBoard()
  markersData.value = await getMarkers()
  measureWidth()
  document.addEventListener('mousedown', handleDocumentClick)
  window.addEventListener('keydown', handleWindowKeydown)
  window.addEventListener('resize', measureWidth)
  await nextTick()
  measureWidth()
})

onUnmounted(() => {
  unsubBoardChanged()
  unsubMediaUpdated()
  stopAutoScroll()
  if (pendingSectionFallbackCommit) {
    clearTimeout(pendingSectionFallbackCommit)
    pendingSectionFallbackCommit = null
  }
  if (pendingItemDragCleanup) {
    clearTimeout(pendingItemDragCleanup)
    pendingItemDragCleanup = null
  }
  document.removeEventListener('mousedown', handleDocumentClick)
  window.removeEventListener('keydown', handleWindowKeydown)
  window.removeEventListener('resize', measureWidth)
})
</script>

<style scoped>
[data-board-item="true"] {
  transition:
    transform 180ms cubic-bezier(0.2, 0.8, 0.2, 1),
    opacity 180ms ease,
    filter 180ms ease;
  will-change: transform;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 150ms ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
