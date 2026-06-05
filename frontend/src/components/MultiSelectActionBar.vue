<template>
  <Transition name="slide-up">
    <div v-if="visible" class="multi-select-action-bar">
      <div class="action-bar-content">
        <!-- Selection controls (left) -->
        <div class="selection-info">
          <!-- Clear selection button (X) -->
          <button
            @click="handleSelectNone"
            class="clear-button"
            title="Clear selection"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
              <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
            </svg>
          </button>

          <!-- Selection count text (double-click to invert selection) -->
          <span
            class="count-text"
            @dblclick="$emit('invert-selection')"
            title="Double-click to invert selection"
          >
            {{ selectedCount }}<span v-if="totalCount > 0"> of {{ totalCount }}</span> selected
          </span>

          <!-- Select All button -->
          <button
            v-if="totalCount > 0 && !isAllSelected"
            @click="$emit('select-all')"
            class="select-all-button"
            title="Select all"
          >
            Select All
          </button>
        </div>

        <!-- Actions (center) -->
        <div class="actions">
          <!-- Trash view actions -->
          <template v-if="isTrashView">
            <!-- Find Similar (trash) -->
            <button
              v-if="selectedCount <= 3"
              class="icon-button"
              title="Find similar"
              @click="$emit('find-similar')"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="8" />
                <path d="m21 21-4.35-4.35" />
              </svg>
            </button>

            <div v-if="selectedCount <= 3" class="divider" />

            <!-- Restore -->
            <button
              class="icon-button restore"
              title="Restore"
              @click="$emit('restore')"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
              </svg>
            </button>

            <!-- Delete Permanently -->
            <button
              class="icon-button danger"
              title="Delete permanently"
              @click="$emit('delete-permanently')"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>

            <div class="divider" />

            <!-- Export (trash) -->
            <button
              class="icon-button"
              title="Export"
              @click="$emit('download')"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" />
              </svg>
            </button>
          </template>

          <!-- Normal browse view actions -->
          <template v-else>
            <!-- Markers -->
            <div v-if="markers && markers.length > 0" class="action-group">
              <button
                v-for="marker in markers"
                :key="marker.id"
                :class="['marker-button', { active: isMarkerActive(marker.id) }]"
                :title="isMarkerActive(marker.id) ? `Remove ${marker.name}` : `Add ${marker.name}`"
                @click="$emit('toggle-marker', { markerId: marker.id, add: !isMarkerActive(marker.id) })"
              >
                <span class="marker-icon icon-container" :style="isMarkerActive(marker.id) ? { color: marker.color } : { color: '#9ca3af' }" v-html="marker.icon_svg" />
              </button>
            </div>

            <div v-if="markers && markers.length > 0" class="divider" />

            <!-- Tags -->
            <button
              class="icon-button"
              title="Add tags"
              @click="$emit('add-tags')"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
              </svg>
            </button>

            <!-- Boards -->
            <button
              class="icon-button"
              title="Add to board"
              @click="$emit('add-to-board')"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                <path d="M3.75 3A1.75 1.75 0 002 4.75v3.5C2 9.216 2.784 10 3.75 10h3.5C8.216 10 9 9.216 9 8.25v-3.5C9 3.784 8.216 3 7.25 3h-3.5zM3.75 11A1.75 1.75 0 002 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 009 16.25v-3.5A1.75 1.75 0 007.25 11h-3.5zM11 4.75A1.75 1.75 0 0112.75 3h3.5c.966 0 1.75.784 1.75 1.75v3.5A1.75 1.75 0 0116.25 10h-3.5A1.75 1.75 0 0111 8.25v-3.5zM12.75 11A1.75 1.75 0 0011 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 0018 16.25v-3.5A1.75 1.75 0 0016.25 11h-3.5z" />
              </svg>
            </button>

            <div class="divider" />

            <!-- More actions (context menu trigger) -->
            <button
              ref="moreActionsButton"
              class="icon-button"
              title="More actions"
              @click.stop="showContextMenu"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                <path d="M3 10a1.5 1.5 0 113 0 1.5 1.5 0 01-3 0zM8.5 10a1.5 1.5 0 113 0 1.5 1.5 0 01-3 0zM15.5 8.5a1.5 1.5 0 100 3 1.5 1.5 0 000-3z" />
              </svg>
            </button>

            <!-- Share (single item only) -->
            <button
              v-if="selectedCount === 1"
              class="icon-button"
              title="Share"
              @click="$emit('share')"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" style="color: #8b5cf6">
                <path d="M13 4.5a2.5 2.5 0 1 1 .702 1.737L6.97 9.604a2.518 2.518 0 0 1 0 .792l6.733 3.367a2.5 2.5 0 1 1-.671 1.341l-6.733-3.367a2.5 2.5 0 1 1 0-3.475l6.733-3.366A2.52 2.52 0 0 1 13 4.5Z" />
              </svg>
            </button>

            <div class="divider" />

            <!-- Print -->
            <button
              class="icon-button"
              title="Print contact sheet"
              @click="$emit('print')"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M6 9V2h12v7M6 18H4a2 2 0 01-2-2v-5a2 2 0 012-2h16a2 2 0 012 2v5a2 2 0 01-2 2h-2M6 14h12v8H6z" />
              </svg>
            </button>

            <!-- Export -->
            <button
              class="icon-button"
              title="Export"
              @click="$emit('download')"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4M7 10l5 5 5-5M12 15V3" />
              </svg>
            </button>

            <!-- Move to Trash -->
            <button
              class="icon-button danger"
              title="Move to trash"
              @click="$emit('delete')"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </template>
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useMediaContextMenu } from '../composables/useMediaContextMenu'

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
  const mediaId = props.firstSelectedItem?.id
  const mediaIds = props.selectedItems.map(item => item.id)

  contextMenu.showAt({
    x,
    bottomY,
    mediaId,
    mediaIds,
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
.multi-select-action-bar {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
  max-width: 800px;
  width: fit-content;
  background: var(--color-surface);
  backdrop-filter: blur(20px);
  border: 1px solid var(--color-border);
  border-radius: 16px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15), 0 4px 8px rgba(0, 0, 0, 0.1);
}

.action-bar-content {
  padding: 12px 20px;
  display: flex;
  align-items: center;
  position: relative;
  gap: 16px;
}

.selection-info {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.clear-button {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 6px;
  background: none;
  border: none;
  color: var(--color-text-tertiary);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.clear-button:hover {
  background-color: var(--color-overlay-light);
  color: var(--color-text-primary);
}

.count-text {
  color: var(--color-text-primary);
  font-size: 0.875rem;
  font-weight: 500;
  white-space: nowrap;
}

.select-all-button {
  padding: 4px 10px;
  background: none;
  border: 1px solid var(--color-border-subtle);
  color: var(--color-text-tertiary);
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.select-all-button:hover {
  background-color: var(--color-overlay-light);
  border-color: var(--color-border);
  color: var(--color-text-primary);
}

.actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 auto;
}

.action-group {
  display: flex;
  gap: 8px;
  align-items: center;
}

.marker-button {
  background: none;
  border: none;
  padding: 4px;
  cursor: pointer;
  transition: opacity 0.15s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.marker-button:hover {
  opacity: 0.7;
}

.marker-button.active .marker-icon {
  filter: drop-shadow(0 0 4px currentColor);
}

.marker-icon :deep(svg) {
  width: 24px;
  height: 24px;
}

.action-button {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background-color: var(--color-overlay-light);
  color: var(--color-text-secondary);
  border: none;
  border-radius: 6px;
  font-size: 0.875rem;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}

.action-button:hover {
  background-color: var(--color-overlay-medium);
  transform: translateY(-1px);
}

.action-button svg {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.action-button.restore {
  @apply text-green-500;
}

.action-button.restore:hover {
  @apply bg-green-950;
}

.action-button.danger {
  @apply text-red-500;
}

.action-button.danger:hover {
  @apply bg-red-950;
}

/* Icon-only buttons for compact actions */
.icon-button {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px;
  background-color: var(--color-overlay-light);
  color: var(--color-text-secondary);
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.icon-button:hover {
  background-color: var(--color-overlay-medium);
  transform: translateY(-1px);
}

.icon-button svg {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
}

.icon-button.restore {
  @apply text-green-500;
}

.icon-button.restore:hover {
  @apply bg-green-950;
}

.icon-button.danger {
  @apply text-red-500;
}

.icon-button.danger:hover {
  @apply bg-red-950;
}

.divider {
  width: 1px;
  height: 24px;
  background: var(--color-border-subtle);
  margin: 0 8px;
}

/* Fade animation for dropdown */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Slide up animation */
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

  .action-button span {
    display: none;
  }

  .action-button {
    padding: 8px;
  }
}
</style>
