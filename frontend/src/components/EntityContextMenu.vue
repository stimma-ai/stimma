<template>
  <Teleport to="body">
    <div
      v-if="contextMenu.state.value.visible"
      ref="menuRef"
      class="fixed bg-surface border border-edge-subtle rounded-lg shadow-xl z-[9999] py-1 min-w-[160px]"
      :style="menuStyle"
    >
      <!-- Single item actions -->
      <template v-if="!isMultiAction">
        <button
          @click="handleOpen"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
          </svg>
          <span>Open</span>
        </button>

        <div class="border-t border-edge-subtle my-1"></div>

        <!-- Rename -->
        <button
          @click="handleRename"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125" />
          </svg>
          <span>Rename</span>
        </button>

        <!-- Move to Project (boards and chats only) -->
        <div
          v-if="contextMenu.state.value.entityType === 'board' || contextMenu.state.value.entityType === 'chat' || contextMenu.state.value.entityType === 'recipe'"
          class="relative"
          ref="projectTriggerRef"
          @mouseenter="openProjectSubmenu"
          @mouseleave="hideProjectSubmenuDelayed"
        >
          <button
            class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
          >
            <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="m20.25 7.5-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z" />
            </svg>
            <span class="flex-1">Move to Project</span>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 text-content-muted">
              <path fill-rule="evenodd" d="M8.22 5.22a.75.75 0 0 1 1.06 0l4.25 4.25a.75.75 0 0 1 0 1.06l-4.25 4.25a.75.75 0 0 1-1.06-1.06L11.94 10 8.22 6.28a.75.75 0 0 1 0-1.06Z" clip-rule="evenodd" />
            </svg>
          </button>

          <!-- Invisible bridge for mouse travel between menu and submenu -->
          <div
            v-if="showProjectSubmenu"
            class="fixed z-[10000]"
            :style="projectBridgeStyle"
            @mouseenter="cancelHideProjectSubmenu"
          />

          <!-- Project submenu (fixed, viewport-aware) -->
          <div
            v-if="showProjectSubmenu"
            ref="projectSubmenuRef"
            class="fixed bg-surface border border-edge-subtle rounded-lg shadow-xl z-[10001] py-1 min-w-[260px]"
            :style="projectSubmenuStyle"
            @mouseenter="cancelHideProjectSubmenu"
            @mouseleave="hideProjectSubmenuDelayed"
            @click.stop
          >
            <ProjectPickerSubmenu
              mode="move"
              :current-project-id="contextMenu.state.value.projectId"
              @select="handleMoveToProject"
            />
          </div>
        </div>

        <div class="border-t border-edge-subtle my-1"></div>

        <button
          @click="handleDelete"
          class="w-full px-3 py-2 text-left text-xs text-red-500 hover:bg-overlay-light flex items-center gap-2"
        >
          <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
          </svg>
          <span>Delete</span>
        </button>
      </template>

      <!-- Multi-select actions -->
      <template v-else>
        <button
          @click="handleDeleteSelected"
          class="w-full px-3 py-2 text-left text-xs text-red-500 hover:bg-overlay-light flex items-center gap-2"
        >
          <svg class="w-4 h-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
          </svg>
          <span>Delete {{ contextMenu.state.value.selectedCount }} {{ entityLabel }}</span>
        </button>
      </template>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useEntityContextMenu } from '../composables/useEntityContextMenu'
import { useContextMenuPosition, useSubmenuPosition } from '../composables/useContextMenuPosition'
import ProjectPickerSubmenu from './ProjectPickerSubmenu.vue'

const contextMenu = useEntityContextMenu()

const emit = defineEmits<{
  (e: 'open', entityType: string, entityId: number): void
  (e: 'delete', entityType: string, entityId: number): void
  (e: 'delete-selected'): void
  (e: 'rename', entityType: string, entityId: number, entityName: string): void
  (e: 'move-to-project', entityType: string, entityId: number, projectId: number | null): void
}>()

const menuRef = ref<HTMLElement | null>(null)
const projectSubmenuRef = ref<HTMLElement | null>(null)
const projectTriggerRef = ref<HTMLElement | null>(null)
const showProjectSubmenu = ref(false)
const hideProjectTimeout = ref<ReturnType<typeof setTimeout> | null>(null)
const projectTriggerRect = ref<DOMRect | null>(null)

// Viewport-aware main menu positioning
const menuCoords = computed(() => ({
  x: contextMenu.state.value.x,
  y: contextMenu.state.value.y,
}))
const menuVisible = computed(() => contextMenu.state.value.visible)
const { menuStyle } = useContextMenuPosition(menuRef, menuCoords, menuVisible)

// Viewport-aware submenu positioning with bridge
const { submenuStyle: projectSubmenuStyle, bridgeStyle: projectBridgeStyle, reposition: repositionSubmenu } = useSubmenuPosition(
  menuRef, projectTriggerRect, projectSubmenuRef, showProjectSubmenu
)

const isMultiAction = computed(() => {
  const s = contextMenu.state.value
  return s.isSelected && s.selectedCount > 1
})

const entityLabel = computed(() => {
  const s = contextMenu.state.value
  if (s.entityType === 'chat') return s.selectedCount === 1 ? 'chat' : 'chats'
  if (s.entityType === 'project') return s.selectedCount === 1 ? 'project' : 'projects'
  if (s.entityType === 'recipe') return s.selectedCount === 1 ? 'recipe' : 'recipes'
  return s.selectedCount === 1 ? 'board' : 'boards'
})

function handleOpen() {
  const { entityType, entityId } = contextMenu.state.value
  contextMenu.hide()
  if (entityType && entityId) {
    emit('open', entityType, entityId)
  }
}

function handleDelete() {
  const { entityType, entityId } = contextMenu.state.value
  contextMenu.hide()
  if (entityType && entityId) {
    emit('delete', entityType, entityId)
  }
}

function handleDeleteSelected() {
  contextMenu.hide()
  emit('delete-selected')
}

function handleRename() {
  const { entityType, entityId, entityName } = contextMenu.state.value
  contextMenu.hide()
  if (entityType && entityId != null) {
    emit('rename', entityType, entityId, entityName || '')
  }
}

function handleMoveToProject(projectId: number | null) {
  const { entityType, entityId } = contextMenu.state.value
  contextMenu.hide()
  showProjectSubmenu.value = false
  if (entityType && entityId != null) {
    emit('move-to-project', entityType, entityId, projectId)
  }
}

function openProjectSubmenu() {
  cancelHideProjectSubmenu()
  if (projectTriggerRef.value) {
    projectTriggerRect.value = projectTriggerRef.value.getBoundingClientRect()
  }
  showProjectSubmenu.value = true
}

function hideProjectSubmenuDelayed() {
  hideProjectTimeout.value = setTimeout(() => {
    showProjectSubmenu.value = false
  }, 300)
}

function cancelHideProjectSubmenu() {
  if (hideProjectTimeout.value) {
    clearTimeout(hideProjectTimeout.value)
    hideProjectTimeout.value = null
  }
}

// Close submenu when main menu hides
watch(() => contextMenu.state.value.visible, (visible) => {
  if (!visible) {
    showProjectSubmenu.value = false
  }
})

// Close on click outside
function handleClickOutside(event: MouseEvent) {
  if (!contextMenu.state.value.visible) return
  const target = event.target as Element
  if (menuRef.value?.contains(target)) return
  if (projectSubmenuRef.value?.contains(target)) return
  contextMenu.hide()
}

// Close on escape
function handleKeyDown(event: KeyboardEvent) {
  if (event.key === 'Escape' && contextMenu.state.value.visible) {
    contextMenu.hide()
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('keydown', handleKeyDown)
})
</script>
