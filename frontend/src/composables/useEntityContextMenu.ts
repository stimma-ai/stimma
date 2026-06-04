import { ref, readonly } from 'vue'

export type EntityType = 'chat' | 'board' | 'project' | 'recipe'

export interface EntityContextMenuState {
  visible: boolean
  x: number
  y: number
  entityType: EntityType | null
  entityId: number | null
  entityName: string | null
  projectId: number | null
  isSelected: boolean
  selectedCount: number
}

// Singleton state
const state = ref<EntityContextMenuState>({
  visible: false,
  x: 0,
  y: 0,
  entityType: null,
  entityId: null,
  entityName: null,
  projectId: null,
  isSelected: false,
  selectedCount: 0
})

export function useEntityContextMenu() {
  function show(options: {
    event: MouseEvent
    entityType: EntityType
    entityId: number
    entityName: string
    projectId?: number | null
    isSelected: boolean
    selectedCount: number
  }) {
    const { event, entityType, entityId, entityName, projectId = null, isSelected, selectedCount } = options

    event.preventDefault()
    event.stopPropagation()

    // Store raw click coordinates - the component measures actual size and adjusts
    let x = event.clientX
    let y = event.clientY

    state.value = {
      visible: true,
      x,
      y,
      entityType,
      entityId,
      entityName,
      projectId,
      isSelected,
      selectedCount
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
