import { ref, readonly } from 'vue'
import type { WorkspaceTabType } from './useWorkspaceTabs'

export interface WorkspaceTabContextMenuState {
  visible: boolean
  x: number
  y: number
  tabId: string | null
  tabType: WorkspaceTabType | null
  entityId: string | null
  displayName: string | null
  isPinned: boolean
  projectId: number | null
}

// Singleton state
const state = ref<WorkspaceTabContextMenuState>({
  visible: false,
  x: 0,
  y: 0,
  tabId: null,
  tabType: null,
  entityId: null,
  displayName: null,
  isPinned: false,
  projectId: null
})

export function useWorkspaceTabsContextMenu() {
  function show(options: {
    event: MouseEvent
    tabId: string
    tabType: WorkspaceTabType
    entityId: string
    displayName: string
    isPinned: boolean
    projectId?: number | null
  }) {
    const { event, tabId, tabType, entityId, displayName, isPinned, projectId } = options

    event.preventDefault()
    event.stopPropagation()

    // Store raw click coordinates - the component measures actual size and adjusts
    let x = event.clientX
    let y = event.clientY

    state.value = {
      visible: true,
      x,
      y,
      tabId,
      tabType,
      entityId,
      displayName,
      isPinned,
      projectId: projectId ?? null
    }
  }

  function hide() {
    state.value = { ...state.value, visible: false }
  }

  return {
    state: readonly(state),
    show,
    hide
  }
}
