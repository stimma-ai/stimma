<template>
  <Teleport to="body">
    <div
      v-if="contextMenu.state.value.visible"
      ref="menuRef"
      class="fixed bg-surface border border-edge-subtle rounded-lg shadow-xl z-menu py-1 min-w-[210px]"
      :style="menuStyle"
    >
      <!-- Pin / Unpin -->
      <button
        v-if="!contextMenu.state.value.isPinned"
        @click="handlePin"
        class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
      >
        <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.25">
          <path d="M10.5 1.5L14.5 5.5L12 8L11.5 12L8 8.5L4.5 12L4 11.5L7.5 8L4 4.5L8 4L10.5 1.5Z" />
        </svg>
        <span>Pin</span>
      </button>
      <button
        v-else
        @click="handleUnpin"
        class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
      >
        <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" viewBox="0 0 16 16" fill="currentColor">
          <path d="M10.5 1.5L14.5 5.5L12 8L11.5 12L8 8.5L4.5 12L4 11.5L7.5 8L4 4.5L8 4L10.5 1.5Z" />
        </svg>
        <span>Unpin</span>
      </button>

      <!-- Close (only if not pinned) -->
      <button
        v-if="!contextMenu.state.value.isPinned"
        @click="handleClose"
        class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
      >
        <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
        <span>Close</span>
      </button>

      <div class="border-t border-edge-subtle my-1"></div>

      <!-- Close Others -->
      <button
        @click="handleCloseOthers"
        class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
      >
        <span class="w-4 h-4 flex-shrink-0"></span>
        <span>Close Others</span>
      </button>

      <!-- Close All Unpinned -->
      <button
        @click="handleCloseAllUnpinned"
        class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
      >
        <span class="w-4 h-4 flex-shrink-0"></span>
        <span>Close All Unpinned</span>
      </button>

      <!-- New / Duplicate Tab (tools) -->
      <template v-if="contextMenu.state.value.tabType === 'tool'">
        <div class="border-t border-edge-subtle my-1"></div>
        <button
          @click="handleNewToolTab"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-start gap-2"
        >
          <svg class="w-4 h-4 mt-0.5 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
          <span class="flex flex-col">
            <span>New Tab</span>
            <span class="text-[10px] leading-4 text-content-muted">Copy with default settings</span>
          </span>
        </button>
        <button
          @click="handleDuplicateToolTab"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-start gap-2"
        >
          <svg class="w-4 h-4 mt-0.5 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
            <rect x="8" y="8" width="11" height="11" rx="1.5" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M16 8V6.5A1.5 1.5 0 0 0 14.5 5h-9A1.5 1.5 0 0 0 4 6.5v9A1.5 1.5 0 0 0 5.5 17H8" />
          </svg>
          <span class="flex flex-col">
            <span>Duplicate Tab</span>
            <span class="text-[10px] leading-4 text-content-muted">Copy this tab's settings</span>
          </span>
        </button>
      </template>

      <!-- Rename (tools, chats, boards, flows & projects) -->
      <template v-if="contextMenu.state.value.tabType === 'tool' || contextMenu.state.value.tabType === 'chat' || contextMenu.state.value.tabType === 'board' || contextMenu.state.value.tabType === 'flow' || contextMenu.state.value.tabType === 'project'">
        <div class="border-t border-edge-subtle my-1"></div>
        <button
          @click="handleRename"
          class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        >
          <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L6.832 19.82a4.5 4.5 0 0 1-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 0 1 1.13-1.897L16.863 4.487Zm0 0L19.5 7.125" />
          </svg>
          <span>Rename</span>
        </button>
      </template>

      <!-- Move to Project (chats, boards & flows) -->
      <template v-if="contextMenu.state.value.tabType === 'chat' || contextMenu.state.value.tabType === 'board' || contextMenu.state.value.tabType === 'flow'">
        <div
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

          <!-- Invisible bridge for mouse travel -->
          <div
            v-if="showProjectSubmenu"
            class="fixed z-submenu"
            :style="projectBridgeStyle"
            @mouseenter="cancelHideProjectSubmenu"
          />

          <!-- Project submenu (fixed, viewport-aware) -->
          <div
            v-if="showProjectSubmenu"
            ref="projectSubmenuRef"
            class="fixed bg-surface border border-edge-subtle rounded-lg shadow-xl z-submenu py-1 min-w-[260px]"
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
      </template>

      <!-- Delete (chats, boards, flows & projects) -->
      <template v-if="contextMenu.state.value.tabType === 'chat' || contextMenu.state.value.tabType === 'board' || contextMenu.state.value.tabType === 'flow' || contextMenu.state.value.tabType === 'project'">
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
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useWorkspaceTabsContextMenu } from '../composables/useWorkspaceTabsContextMenu'
import { useWorkspaceTabs, toolTabRoute, toolInstanceRoute, toolRouteTabId } from '../composables/useWorkspaceTabs'
import { useProjectRoute } from '../composables/useProjectRoute'
import { useMediaApi } from '../composables/useMediaApi'
import { useToasts } from '../composables/useToasts'
import { useContextMenuPosition, useSubmenuPosition } from '../composables/useContextMenuPosition'
import ProjectPickerSubmenu from './ProjectPickerSubmenu.vue'

const contextMenu = useWorkspaceTabsContextMenu()
const { allTabs, findNextTab, removeTab, pinTab, unpinTab, closeOthers, closeAllUnpinned } = useWorkspaceTabs()
const { getLastProjectRoute } = useProjectRoute()
const { deleteBoard, restoreBoard, updateBoard } = useMediaApi()
const { addToast } = useToasts()

const showProjectSubmenu = ref(false)
const projectSubmenuRef = ref<HTMLElement | null>(null)
const projectTriggerRef = ref<HTMLElement | null>(null)
const hideProjectTimeout = ref<ReturnType<typeof setTimeout> | null>(null)
const projectTriggerRect = ref<DOMRect | null>(null)
const router = useRouter()
const route = useRoute()

function getActiveTabId(): string | null {
  if (route.name === 'tool') {
    return toolRouteTabId(route)
  }
  if (route.name === 'chat') return `chat:${route.params.id}`
  if (route.name === 'board-detail') return `board:${route.params.id}`
  if (route.name === 'flow') return `flow:${route.params.id}`
  if (String(route.name || '').startsWith('project-')) return `project:${route.params.id}`
  if (route.name === 'edit-image' || route.name === 'edit-image-empty') return `editor:${route.params.editorId}`
  return null
}

function goToTab(tab: import('../composables/useWorkspaceTabs').WorkspaceTab) {
  if (tab.type === 'tool') {
    router.push(toolTabRoute(tab))
  }
  else if (tab.type === 'chat') router.push({ name: 'chat', params: { id: tab.entityId } })
  else if (tab.type === 'board') router.push({ name: 'board-detail', params: { id: tab.entityId } })
  else if (tab.type === 'flow') router.push({ name: 'flow', params: { id: tab.entityId } })
  else if (tab.type === 'project') router.push({ name: getLastProjectRoute(tab.entityId), params: { id: tab.entityId } })
  else if (tab.type === 'editor') {
    if (tab.editorMediaId) router.push({ name: 'edit-image', params: { editorId: tab.entityId, mediaId: tab.editorMediaId } })
    else router.push({ name: 'edit-image-empty', params: { editorId: tab.entityId } })
  }
}

function navigateAfterClose(excludeIds: Set<string>) {
  const activeId = getActiveTabId()
  if (activeId && excludeIds.has(activeId)) {
    const next = findNextTab(excludeIds)
    if (next) goToTab(next)
    else router.push({ name: 'browse' })
  }
}

const menuRef = ref<HTMLElement | null>(null)

const emit = defineEmits<{
  (e: 'rename', tabType: 'board' | 'chat' | 'project' | 'flow', entityId: string, currentName: string): void
  (e: 'rename-tab', tabId: string): void
  (e: 'refresh'): void
}>()

// Viewport-aware main menu positioning
const menuCoords = computed(() => ({
  x: contextMenu.state.value.x,
  y: contextMenu.state.value.y,
}))
const menuVisible = computed(() => contextMenu.state.value.visible)
const { menuStyle } = useContextMenuPosition(menuRef, menuCoords, menuVisible)

// Viewport-aware submenu positioning with bridge
const { submenuStyle: projectSubmenuStyle, bridgeStyle: projectBridgeStyle } = useSubmenuPosition(
  menuRef, projectTriggerRect, projectSubmenuRef, showProjectSubmenu
)

async function handlePin() {
  const tabId = contextMenu.state.value.tabId
  contextMenu.hide()
  if (tabId) {
    await pinTab(tabId)
    emit('refresh')
  }
}

async function handleUnpin() {
  const tabId = contextMenu.state.value.tabId
  contextMenu.hide()
  if (tabId) {
    await unpinTab(tabId)
    emit('refresh')
  }
}

function handleClose() {
  const tabId = contextMenu.state.value.tabId
  contextMenu.hide()
  if (tabId) {
    navigateAfterClose(new Set([tabId]))
    removeTab(tabId)
  }
}

function handleCloseOthers() {
  const tabId = contextMenu.state.value.tabId
  contextMenu.hide()
  if (tabId) {
    const removedIds = new Set(allTabs.value.filter(t => t.id !== tabId && !t.pinned).map(t => t.id))
    navigateAfterClose(removedIds)
    closeOthers(tabId)
  }
}

function handleCloseAllUnpinned() {
  contextMenu.hide()
  const removedIds = new Set(allTabs.value.filter(t => !t.pinned).map(t => t.id))
  navigateAfterClose(removedIds)
  closeAllUnpinned()
}

function handleRename() {
  const { tabType, entityId, displayName, tabId } = contextMenu.state.value
  contextMenu.hide()
  // Tool tabs rename by tab id (entityId alone can't identify an instance).
  if (tabType === 'tool' && tabId) {
    emit('rename-tab', tabId)
    return
  }
  if (tabType && entityId && (tabType === 'chat' || tabType === 'board' || tabType === 'project' || tabType === 'flow')) {
    emit('rename', tabType, entityId, displayName || '')
  }
}

function handleNewToolTab() {
  const { tabType, entityId, projectId } = contextMenu.state.value
  contextMenu.hide()
  if (tabType !== 'tool' || !entityId) return
  const { resolveToolInstance } = useWorkspaceTabs()
  const { instanceId } = resolveToolInstance(entityId, projectId ?? null, { forceNew: true })
  router.push(toolInstanceRoute(entityId, projectId ?? null, instanceId))
}

async function handleDuplicateToolTab() {
  const { tabType, tabId } = contextMenu.state.value
  contextMenu.hide()
  if (tabType !== 'tool' || !tabId) return

  // ToolView handles this synchronously for the matching instance so the
  // duplicate includes edits that are still inside the save debounce window.
  window.dispatchEvent(new CustomEvent('stimma:flush-tool-instance-state', {
    detail: { tabId }
  }))

  const { duplicateToolTab } = useWorkspaceTabs()
  const duplicate = await duplicateToolTab(tabId)
  if (duplicate) router.push(toolTabRoute(duplicate))
}

async function handleDelete() {
  const { tabType, entityId, tabId } = contextMenu.state.value
  contextMenu.hide()

  if (!tabType || !entityId || !tabId) return

  try {
    if (tabType === 'board') {
      await deleteBoard(parseInt(entityId, 10))
    } else if (tabType === 'chat') {
      const response = await fetch(`/api/chats/${entityId}`, { method: 'DELETE' })
      if (!response.ok) throw new Error('chat delete failed')
    } else if (tabType === 'flow') {
      const response = await fetch(`/api/flows/${entityId}`, { method: 'DELETE' })
      if (!response.ok) throw new Error('flow delete failed')
    } else if (tabType === 'project') {
      const response = await fetch(`/api/projects/${entityId}`, { method: 'DELETE' })
      if (!response.ok) throw new Error('project delete failed')
    }
    navigateAfterClose(new Set([tabId]))
    removeTab(tabId)
    emit('refresh')
  } catch (err) {
    console.error(`Failed to delete ${tabType}:`, err)
    addToast(`Failed to delete ${tabType}`, 'error', 5000)
    return
  }

  if (tabType === 'board' || tabType === 'chat' || tabType === 'flow') {
    const id = parseInt(entityId, 10)
    addToast(`Deleted 1 ${tabType}`, 'info', 5000, {
      label: 'Undo',
      onClick: async () => {
        try {
          if (tabType === 'board') {
            await restoreBoard(id)
          } else if (tabType === 'flow') {
            const response = await fetch(`/api/flows/${id}/restore`, { method: 'POST' })
            if (!response.ok) throw new Error('restore failed')
          } else {
            const response = await fetch(`/api/chats/${id}/restore`, { method: 'POST' })
            if (!response.ok) throw new Error('restore failed')
          }
          emit('refresh')
        } catch (err) {
          console.error(`Failed to restore ${tabType}:`, err)
          addToast(`Failed to restore ${tabType}`, 'error', 5000)
        }
      }
    })
  }
}

async function handleMoveToProject(projectId: number | null) {
  const { tabType, entityId } = contextMenu.state.value
  contextMenu.hide()
  showProjectSubmenu.value = false
  if (!tabType || !entityId) return

  try {
    if (tabType === 'board') {
      await updateBoard(parseInt(entityId, 10), { project_id: projectId })
    } else if (tabType === 'chat') {
      await fetch(`/api/chats/${entityId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId })
      })
    } else if (tabType === 'flow') {
      await fetch(`/api/flows/${entityId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId })
      })
    }
    emit('refresh')
  } catch (err) {
    console.error(`Failed to move ${tabType} to project:`, err)
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
  if (event.key === 'Escape') {
    contextMenu.hide()
  }
}

watch(() => contextMenu.state.value.visible, (visible) => {
  if (!visible) {
    showProjectSubmenu.value = false
  }
})

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  document.addEventListener('keydown', handleKeyDown)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  document.removeEventListener('keydown', handleKeyDown)
})
</script>
