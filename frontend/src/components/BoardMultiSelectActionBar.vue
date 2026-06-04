<template>
  <Transition name="slide-up">
    <div v-if="visible" class="multi-select-action-bar">
      <div class="action-bar-content">
        <!-- Selection controls (left) -->
        <div class="selection-info">
          <button
            @click="$emit('clear')"
            class="clear-button"
            title="Clear selection"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4">
              <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
            </svg>
          </button>

          <span class="count-text">
            {{ selectedCount }}<span v-if="totalCount > 0"> of {{ totalCount }}</span> selected
          </span>

          <button
            v-if="totalCount > 0 && selectedCount < totalCount"
            @click="$emit('select-all')"
            class="select-all-button"
            title="Select all"
          >
            Select All
          </button>
        </div>

        <!-- Actions (center) -->
        <div class="actions">
          <!-- Remove from board -->
          <button
            class="icon-button"
            title="Remove from board"
            @click="$emit('remove-from-board')"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
              <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
            </svg>
          </button>

          <!-- Move to section -->
          <div class="relative">
            <button
              ref="moveToSectionButton"
              class="icon-button"
              title="Move to section"
              @click.stop="showSectionPicker = !showSectionPicker"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M2 4.75C2 3.784 2.784 3 3.75 3h4.836c.464 0 .909.184 1.237.513l1.414 1.414a.25.25 0 00.177.073h4.836c.966 0 1.75.784 1.75 1.75v8.5A1.75 1.75 0 0116.25 17H3.75A1.75 1.75 0 012 15.25V4.75z" clip-rule="evenodd" />
              </svg>
            </button>
            <Transition name="fade">
              <div
                v-if="showSectionPicker"
                class="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 min-w-[200px] overflow-hidden rounded-xl border border-white/10 bg-surface shadow-2xl"
              >
                <div class="px-3 py-2 text-xs font-medium text-content-muted">Move to section</div>
                <button
                  v-for="section in sections"
                  :key="section.id"
                  class="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm text-content transition-colors hover:bg-white/[0.05]"
                  @click="handleMoveToSection(section.id)"
                >
                  <span class="truncate">{{ section.name || (section.is_default ? 'Default' : 'Untitled') }}</span>
                </button>
                <div class="border-t border-white/10">
                  <button
                    class="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm text-blue-400 transition-colors hover:bg-white/[0.05]"
                    @click="handleMoveToNewSection"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-4 w-4">
                      <path d="M10.75 4.75a.75.75 0 00-1.5 0v4.5h-4.5a.75.75 0 000 1.5h4.5v4.5a.75.75 0 001.5 0v-4.5h4.5a.75.75 0 000-1.5h-4.5v-4.5z" />
                    </svg>
                    <span>New section</span>
                  </button>
                </div>
              </div>
            </Transition>
          </div>

          <!-- Create section from selection -->
          <button
            class="icon-button"
            title="Create section from selection"
            @click="$emit('create-section-from-selection')"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
              <path d="M2 4.75C2 3.784 2.784 3 3.75 3h4.836c.464 0 .909.184 1.237.513l1.414 1.414a.25.25 0 00.177.073h4.836c.966 0 1.75.784 1.75 1.75v8.5A1.75 1.75 0 0116.25 17H3.75A1.75 1.75 0 012 15.25V4.75z" clip-rule="evenodd" />
              <path d="M10.75 8.75a.75.75 0 00-1.5 0v1.5h-1.5a.75.75 0 000 1.5h1.5v1.5a.75.75 0 001.5 0v-1.5h1.5a.75.75 0 000-1.5h-1.5v-1.5z" />
            </svg>
          </button>

          <div class="divider" />

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

          <!-- Add to board -->
          <button
            class="icon-button"
            title="Add to another board"
            @click="$emit('add-to-board')"
          >
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor">
              <path d="M3.75 3A1.75 1.75 0 002 4.75v3.5C2 9.216 2.784 10 3.75 10h3.5C8.216 10 9 9.216 9 8.25v-3.5C9 3.784 8.216 3 7.25 3h-3.5zM3.75 11A1.75 1.75 0 002 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 009 16.25v-3.5A1.75 1.75 0 007.25 11h-3.5zM11 4.75A1.75 1.75 0 0112.75 3h3.5c.966 0 1.75.784 1.75 1.75v3.5A1.75 1.75 0 0116.25 10h-3.5A1.75 1.75 0 0111 8.25v-3.5zM12.75 11A1.75 1.75 0 0011 12.75v3.5c0 .966.784 1.75 1.75 1.75h3.5A1.75 1.75 0 0018 16.25v-3.5A1.75 1.75 0 0016.25 11h-3.5z" />
            </svg>
          </button>

          <div class="divider" />

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
        </div>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  selectedCount: { type: Number, default: 0 },
  totalCount: { type: Number, default: 0 },
  markers: { type: Array, default: () => [] },
  activeMarkerIds: { type: Array, default: () => [] },
  sections: { type: Array, default: () => [] }
})

const emit = defineEmits([
  'clear',
  'select-all',
  'remove-from-board',
  'move-to-section',
  'move-to-new-section',
  'create-section-from-selection',
  'toggle-marker',
  'add-tags',
  'add-to-board',
  'download',
  'delete'
])

const showSectionPicker = ref(false)

function isMarkerActive(markerId) {
  return props.activeMarkerIds.includes(markerId)
}

function handleMoveToSection(sectionId) {
  showSectionPicker.value = false
  emit('move-to-section', sectionId)
}

function handleMoveToNewSection() {
  showSectionPicker.value = false
  emit('move-to-new-section')
}

function handleClickOutside(event) {
  if (showSectionPicker.value) {
    showSectionPicker.value = false
  }
}

watch(() => props.visible, (val) => {
  if (!val) showSectionPicker.value = false
})

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})
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

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

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
</style>
