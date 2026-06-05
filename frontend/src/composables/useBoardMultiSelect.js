import { computed, ref } from 'vue'
import { useMultiSelect } from './useMultiSelect'

/**
 * Board-specific multi-select composable.
 * Wraps useMultiSelect with section-aware shift-click and item-to-section mapping.
 *
 * @param {Object} options
 * @param {import('vue').Ref} options.board - Ref to board data
 * @param {import('vue').Ref} options.markers - Ref to markers array
 */
export function useBoardMultiSelect(options = {}) {
  const { board, markers } = options

  const lastClickedItem = ref(null) // { sectionId, itemId, itemIndex }
  const lastClickedAction = ref('select') // 'select' or 'deselect'

  function getAllItems() {
    if (!board?.value?.sections) return []
    return board.value.sections.flatMap(section =>
      (section.items || []).map(item => ({ ...item, _sectionId: section.id }))
    )
  }

  function getItemsByIds(ids) {
    const idSet = new Set(ids.map(id => parseInt(id)))
    return getAllItems().filter(item => idSet.has(item.id))
  }

  const {
    multiSelectMode,
    selectedItemIds,
    selectingAll,
    handleToggleSelection,
    handleShiftClickRange,
    selectAll,
    selectNone,
    removeFromSelection,
    selectedItems,
    activeMarkerIds,
    currentTagCounts,
    createKeyboardHandler
  } = useMultiSelect({
    fetchAllIds: () => {
      return getAllItems().map(item => item.id)
    },
    getItemsByIds,
    markers
  })

  /**
   * Map of mediaId -> sectionId for all selected items
   */
  const selectedItemSectionMap = computed(() => {
    const map = new Map()
    if (!board?.value?.sections) return map
    const selectedSet = new Set(selectedItemIds.value)
    for (const section of board.value.sections) {
      for (const item of section.items || []) {
        if (selectedSet.has(item.id)) {
          map.set(item.id, section.id)
        }
      }
    }
    return map
  })

  /**
   * Handle item click with modifier key detection.
   * Returns true if the click was handled as a selection action.
   */
  function handleItemClick(section, item, event) {
    const isModifier = event.metaKey || event.ctrlKey

    if (event.shiftKey && lastClickedItem.value) {
      // Shift-click: range select across all sections (flat order)
      const allSections = board?.value?.sections || []
      const flatItems = allSections.flatMap(s => (s.items || []).map(i => ({ id: i.id, sectionId: s.id })))
      const anchorIndex = flatItems.findIndex(fi => fi.id === lastClickedItem.value.itemId)
      const targetIndex = flatItems.findIndex(fi => fi.id === item.id)
      if (anchorIndex !== -1 && targetIndex !== -1) {
        const start = Math.min(anchorIndex, targetIndex)
        const end = Math.max(anchorIndex, targetIndex)
        const rangeIds = flatItems.slice(start, end + 1).map(fi => fi.id)
        handleShiftClickRange({ ids: rangeIds, action: lastClickedAction.value })
        lastClickedItem.value = { sectionId: section.id, itemId: item.id }
        return true
      }
    }

    if (isModifier) {
      const wasSelected = selectedItemIds.value.includes(item.id)
      lastClickedAction.value = wasSelected ? 'deselect' : 'select'
      handleToggleSelection(item.id)
      lastClickedItem.value = { sectionId: section.id, itemId: item.id }
      return true
    }

    // Plain click while in multi-select mode
    if (multiSelectMode.value) {
      // Click on selected item: deselect
      if (selectedItemIds.value.includes(item.id)) {
        handleToggleSelection(item.id)
        return true
      }
      // Click on unselected item: clear selection, don't handle (let slideshow open)
      selectNone()
      return false
    }

    return false // Not handled — let the normal click action (slideshow) proceed
  }

  /**
   * Get selected item IDs that belong to a specific section
   */
  function getSelectedIdsInSection(sectionId) {
    const result = []
    for (const id of selectedItemIds.value) {
      if (selectedItemSectionMap.value.get(id) === sectionId) {
        result.push(id)
      }
    }
    return result
  }

  return {
    // State
    multiSelectMode,
    selectedItemIds,
    selectingAll,
    lastClickedItem,
    lastClickedAction,

    // Actions
    handleItemClick,
    handleToggleSelection,
    handleShiftClickRange,
    selectAll,
    selectNone,
    removeFromSelection,

    // Computed
    selectedItems,
    activeMarkerIds,
    currentTagCounts,
    selectedItemSectionMap,
    getSelectedIdsInSection,

    // Keyboard
    createKeyboardHandler
  }
}
