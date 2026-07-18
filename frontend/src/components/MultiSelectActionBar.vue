<template>
  <Transition name="slide-up">
    <div v-if="visible" class="multi-select-action-bar fixed bottom-6 left-1/2 -translate-x-1/2 z-chrome max-w-[800px] w-fit bg-surface backdrop-blur-xl border border-edge-subtle rounded-lg shadow-lg">
      <div class="action-bar-content flex items-center relative gap-4 px-5 py-3">
        <!-- Selection controls (left) -->
        <div class="selection-info flex-shrink-0 flex items-center gap-2">
          <!-- Clear selection button (X) -->
          <Tooltip text="Clear selection">
            <button
              @click="handleSelectNone"
              class="flex items-center justify-center p-1.5 rounded-md text-content-tertiary hover:bg-overlay-subtle hover:text-content transition-colors"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
                <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
              </svg>
            </button>
          </Tooltip>

          <!-- Selection count text (double-click to invert selection) -->
          <Tooltip text="Double-click to invert selection">
            <span
              class="text-sm font-medium text-content whitespace-nowrap"
              @dblclick="$emit('invert-selection')"
            >
              <span class="font-mono tabular-nums">{{ selectedCount }}</span><span v-if="totalCount > 0"> of <span class="font-mono tabular-nums">{{ totalCount }}</span></span> selected
            </span>
          </Tooltip>

          <!-- Select All button -->
          <Tooltip v-if="totalCount > 0 && !isAllSelected" text="Select all">
            <button
              @click="$emit('select-all')"
              class="px-2.5 py-1 border border-edge-subtle rounded text-xs font-medium text-content-tertiary hover:bg-overlay-subtle hover:border-edge hover:text-content transition-colors"
            >
              Select All
            </button>
          </Tooltip>
        </div>

        <!-- Actions (center) -->
        <div class="actions flex items-center gap-2 mx-auto">
          <!-- Trash view actions -->
          <template v-if="isTrashView">
            <!-- Find Similar (trash) -->
            <Tooltip v-if="selectedCount <= 3" text="Find similar">
              <button
                class="icon-button flex items-center justify-center p-2 rounded-md bg-overlay-subtle text-content-secondary hover:bg-overlay-hover transition-colors"
                @click="$emit('find-similar')"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-[18px] h-[18px]">
                  <circle cx="11" cy="11" r="8" />
                  <path d="m21 21-4.35-4.35" />
                </svg>
              </button>
            </Tooltip>

            <div v-if="selectedCount <= 3" class="divider w-px h-6 bg-edge-subtle mx-2" />

            <!-- Restore -->
            <Tooltip text="Restore">
              <button
                class="icon-button flex items-center justify-center p-2 rounded-md bg-overlay-subtle text-green-400 hover:bg-green-500/15 transition-colors"
                @click="$emit('restore')"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-[18px] h-[18px]">
                  <path d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
                </svg>
              </button>
            </Tooltip>

            <!-- Delete Permanently -->
            <Tooltip text="Delete permanently">
              <button
                class="icon-button flex items-center justify-center p-2 rounded-md bg-overlay-subtle text-red-400 hover:bg-red-500/15 transition-colors"
                @click="$emit('delete-permanently')"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-[18px] h-[18px]">
                  <path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </Tooltip>

            <div class="divider w-px h-6 bg-edge-subtle mx-2" />

            <!-- Export (trash) -->
            <Tooltip text="Export">
              <button
                class="icon-button flex items-center justify-center p-2 rounded-md bg-overlay-subtle text-content-secondary hover:bg-overlay-hover transition-colors"
                @click="$emit('download')"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-[18px] h-[18px]">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" />
                </svg>
              </button>
            </Tooltip>
          </template>

          <!-- Normal browse view actions -->
          <template v-else>
            <!-- Markers -->
            <div v-if="markers && markers.length > 0" class="action-group flex items-center gap-2">
              <Tooltip
                v-for="marker in markers"
                :key="marker.id"
                :text="isMarkerActive(marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
              >
                <button
                  :class="['marker-button p-1 flex items-center justify-center transition-opacity hover:opacity-70', { active: isMarkerActive(marker.id) }]"
                  @click="$emit('toggle-marker', { markerId: marker.id, add: !isMarkerActive(marker.id) })"
                >
                  <span class="marker-icon w-6 h-6 flex items-center justify-center" :style="isMarkerActive(marker.id) ? { color: marker.color } : { color: 'var(--color-text-muted)' }" v-html="sanitizeSvg(marker.icon_svg)" />
                </button>
              </Tooltip>
            </div>

            <div v-if="markers && markers.length > 0" class="divider w-px h-6 bg-edge-subtle mx-2" />

            <!-- Tags -->
            <Tooltip text="Add tags">
              <button
                class="icon-button flex items-center justify-center p-2 rounded-md bg-overlay-subtle text-content-secondary hover:bg-overlay-hover transition-colors"
                @click="$emit('add-tags')"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-[18px] h-[18px]">
                  <path d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
                </svg>
              </button>
            </Tooltip>

            <!-- Boards -->
            <Tooltip text="Add to board">
              <button
                class="icon-button flex items-center justify-center p-2 rounded-md bg-overlay-subtle text-content-secondary hover:bg-overlay-hover transition-colors"
                @click="$emit('add-to-board')"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-[18px] h-[18px]">
                  <path d="M3.75 3A1.75 1.75 0 002 4.75v3.5C2 9.216 2.784 10 3.75 10h3.5C8.216 10 9 9.216 9 8.25v-3.5C9 3.784 8.216 3 7.25 3h-3.5zM3.75 11A1.75 1.75 0 002 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 009 16.25v-3.5A1.75 1.75 0 007.25 11h-3.5zM11 4.75A1.75 1.75 0 0112.75 3h3.5c.966 0 1.75.784 1.75 1.75v3.5A1.75 1.75 0 0116.25 10h-3.5A1.75 1.75 0 0111 8.25v-3.5zM12.75 11A1.75 1.75 0 0011 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 0018 16.25v-3.5A1.75 1.75 0 0016.25 11h-3.5z" />
                </svg>
              </button>
            </Tooltip>

            <div class="divider w-px h-6 bg-edge-subtle mx-2" />

            <!-- More actions (context menu trigger) -->
            <Tooltip text="More actions">
              <button
                ref="moreActionsButton"
                class="icon-button flex items-center justify-center p-2 rounded-md bg-overlay-subtle text-content-secondary hover:bg-overlay-hover transition-colors"
                @click.stop="showContextMenu"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-[18px] h-[18px]">
                  <path d="M3 10a1.5 1.5 0 113 0 1.5 1.5 0 01-3 0zM8.5 10a1.5 1.5 0 113 0 1.5 1.5 0 01-3 0zM15.5 8.5a1.5 1.5 0 100 3 1.5 1.5 0 000-3z" />
                </svg>
              </button>
            </Tooltip>

            <!-- Share (single item only) -->
            <Tooltip v-if="selectedCount === 1" text="Share">
              <button
                class="icon-button flex items-center justify-center p-2 rounded-md bg-overlay-subtle text-purple-400 hover:bg-purple-500/15 transition-colors"
                @click="$emit('share')"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-[18px] h-[18px]">
                  <path d="M13 4.5a2.5 2.5 0 1 1 .702 1.737L6.97 9.604a2.518 2.518 0 0 1 0 .792l6.733 3.367a2.5 2.5 0 1 1-.671 1.341l-6.733-3.367a2.5 2.5 0 1 1 0-3.475l6.733-3.366A2.52 2.52 0 0 1 13 4.5Z" />
                </svg>
              </button>
            </Tooltip>

            <div class="divider w-px h-6 bg-edge-subtle mx-2" />

            <!-- Print -->
            <Tooltip text="Print contact sheet">
              <button
                class="icon-button flex items-center justify-center p-2 rounded-md bg-overlay-subtle text-content-secondary hover:bg-overlay-hover transition-colors"
                @click="$emit('print')"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-[18px] h-[18px]">
                  <path d="M6 9V2h12v7M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2M6 14h12v8H6z" />
                </svg>
              </button>
            </Tooltip>

            <!-- Export -->
            <Tooltip text="Export">
              <button
                class="icon-button flex items-center justify-center p-2 rounded-md bg-overlay-subtle text-content-secondary hover:bg-overlay-hover transition-colors"
                @click="$emit('download')"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-[18px] h-[18px]">
                  <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" />
                </svg>
              </button>
            </Tooltip>

            <!-- Move to Trash -->
            <Tooltip text="Move to trash">
              <button
                class="icon-button flex items-center justify-center p-2 rounded-md bg-overlay-subtle text-red-400 hover:bg-red-500/15 transition-colors"
                @click="$emit('delete')"
              >
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="w-[18px] h-[18px]">
                  <path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </Tooltip>
          </template>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useMediaContextMenu } from '../composables/useMediaContextMenu'
import { sanitizeSvg } from '../utils/sanitizeHtml'
import { assetIdOf, mediaIdOf } from '../utils/assetIdentity'
import Tooltip from './ui/Tooltip.vue'

const contextMenu = useMediaContextMenu()

// Ref for the more actions button to position the context menu
const moreActionsButton = ref(null)

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  },
  selectedCount: {
    type: Number,
    default: 0
  },
  totalCount: {
    type: Number,
    default: 0
  },
  markers: {
    type: Array,
    default: () => []
  },
  activeMarkerIds: {
    type: Array,
    default: () => []  // Marker IDs that ALL selected items have
  },
  inBoard: {
    type: Boolean,
    default: false
  },
  boardSectionId: {
    type: Number,
    default: null
  },
  isTrashView: {
    type: Boolean,
    default: false
  },
  // First selected item data (for single selection actions)
  firstSelectedItem: {
    type: Object,
    default: null
  },
  // All selected items (for multi-select send-to)
  selectedItems: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits([
  'clear',
  'select-all',
  'invert-selection',
  'toggle-marker',
  'add-tags',
  'add-to-board',
  'remove-from-board',
  'set-cover',
  'find-similar',
  'compare',
  'edit-image',
  'download',
  'delete',
  'restore',
  'delete-permanently',
  'print',
  'share'
])

// Computed: check if all items are selected (hides "All" button when true)
const isAllSelected = computed(() => {
  return props.totalCount > 0 && props.selectedCount === props.totalCount
})

// Show context menu from the "more actions" button
function showContextMenu() {
  if (!moreActionsButton.value) return

  const rect = moreActionsButton.value.getBoundingClientRect()

  // Position menu so its bottom edge sits just above the action bar
  // We use bottomY to anchor the menu's bottom to the top of the action bar
  const x = rect.left
  const bottomY = rect.top - 8  // 8px gap between menu and action bar

  // Get the first selected item's ID
  const assetId = props.firstSelectedItem ? assetIdOf(props.firstSelectedItem) : null
  const assetIds = props.selectedItems.map(assetIdOf).filter(Boolean)
  const mediaId = props.firstSelectedItem ? mediaIdOf(props.firstSelectedItem) : null
  const mediaIds = props.selectedItems.map(mediaIdOf).filter(Boolean)

  contextMenu.showAt({
    x,
    bottomY,
    mediaId,
    mediaIds,
    assetId,
    assetIds,
    selectedItems: props.selectedItems,
    inBoard: props.inBoard,
    boardSectionId: props.boardSectionId
  })
}

function isMarkerActive(markerId) {
  return props.activeMarkerIds.includes(markerId)
}

function handleSelectNone() {
  emit('clear')
}
</script>

<style scoped>
/* Active-marker glow — dynamic per-marker color, not expressible as a
   static Tailwind class. */
.marker-button.active .marker-icon {
  filter: drop-shadow(0 0 4px currentColor);
}

.marker-icon :deep(svg) {
  width: 24px;
  height: 24px;
}

/* Slide up animation (positional transform, kept as scoped CSS — not a
   color/opacity transition covered by the global recipe vocabulary). */
.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease;
}

.slide-up-enter-from,
.slide-up-leave-to {
  transform: translate(-50%, 120%);
  opacity: 0;
}

.slide-up-enter-to,
.slide-up-leave-from {
  transform: translate(-50%, 0);
  opacity: 1;
}

/* Mobile responsiveness - matches App.vue mobile breakpoint of 1024px */
@media (max-width: 1024px) {
  .multi-select-action-bar {
    max-width: calc(100% - 32px);
    bottom: 16px;
  }

  .action-bar-content {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
    padding: 12px 16px;
  }

  .selection-info {
    justify-content: flex-start;
  }

  .actions {
    justify-content: flex-start;
    flex-wrap: wrap;
    margin: 0;
  }
}
</style>
