import { ref, computed } from 'vue'

/**
 * Composable for managing multi-select state and operations
 *
 * Provides:
 * - Multi-select mode toggle
 * - Selection state management
 * - Item selection handlers (toggle, shift-range)
 * - Select all/none operations
 * - Keyboard shortcuts integration
 * - Computed properties for active markers and selected items
 *
 * @param {Object} options - Configuration options
 * @param {Function} options.fetchAllIds - Async function to fetch all IDs matching current filters
 * @param {Function} options.getItemsByIds - Function to get items from grid by IDs (for computing markers/tags)
 * @param {Array} options.markers - Ref to markers array (optional, for computing active markers)
 * @returns {Object} Multi-select state and functions
 */
export function useMultiSelect(options = {}) {
  const { fetchAllIds, getItemsByIds, markers } = options

  // Multi-select state
  const multiSelectMode = ref(false)
  const selectedItemIds = ref([])
  const selectingAll = ref(false)  // Loading state for Select All operation

  /**
   * Toggle multi-select mode on/off
   * Clears selection when turning off
   */
  function toggleMultiSelectMode() {
    multiSelectMode.value = !multiSelectMode.value
    if (!multiSelectMode.value) {
      selectedItemIds.value = []
    }
  }

  /**
   * Toggle selection of a single item
   * Auto-exits multi-select mode if selection becomes empty
   *
   * @param {number|string} itemId - ID of item to toggle
   */
  function toggleItemSelection(itemId) {
    const index = selectedItemIds.value.indexOf(itemId)
    if (index > -1) {
      selectedItemIds.value.splice(index, 1)
      // Auto-dismiss selection mode if selection becomes empty
      if (selectedItemIds.value.length === 0) {
        multiSelectMode.value = false
      }
    } else {
      selectedItemIds.value.push(itemId)
    }
  }

  /**
   * Handle single item selection toggle (used by grid item click, checkbox, cmd/ctrl-click)
   * Auto-enables multi-select mode when selecting items
   *
   * @param {number|string} itemId - ID of item to toggle
   * @param {number} index - Grid index of item (optional, not used but provided by grid)
   */
  function handleToggleSelection(itemId, index) {
    // Auto-enable multi-select mode when selecting (not when deselecting)
    if (!multiSelectMode.value && !selectedItemIds.value.includes(itemId)) {
      multiSelectMode.value = true
    }
    toggleItemSelection(itemId)
  }

  /**
   * Handle shift-click range selection/deselection
   * Auto-enables multi-select mode if not already enabled
   * Adds or removes all IDs in range based on action
   *
   * @param {Object} data - Range data from grid
   * @param {Array} data.ids - Array of item IDs in the shift-clicked range
   * @param {string} data.action - 'select' or 'deselect'
   */
  function handleShiftClickRange(data) {
    const action = data.action || 'select'

    if (action === 'deselect') {
      // Remove all IDs in range from selection
      selectedItemIds.value = selectedItemIds.value.filter(id => !data.ids.includes(id))

      // Auto-exit multi-select mode if selection becomes empty
      if (selectedItemIds.value.length === 0) {
        multiSelectMode.value = false
      }
    } else {
      // Auto-enable multi-select mode if not already enabled
      if (!multiSelectMode.value) {
        multiSelectMode.value = true
      }

      // Add all IDs in range to selection (if not already selected)
      data.ids.forEach(id => {
        if (!selectedItemIds.value.includes(id)) {
          selectedItemIds.value.push(id)
        }
      })
    }
  }

  /**
   * Select all items matching current filters
   * Uses the provided fetchAllIds function
   * Auto-exits multi-select mode if nothing was selected
   */
  async function selectAll() {
    if (!fetchAllIds) {
      console.error('[useMultiSelect] selectAll called but fetchAllIds not provided')
      return
    }

    try {
      selectingAll.value = true
      const ids = await fetchAllIds()
      selectedItemIds.value = ids || []

      // Exit multi-select mode if nothing was selected
      if (selectedItemIds.value.length === 0) {
        multiSelectMode.value = false
      }
    } catch (error) {
      console.error('[useMultiSelect] Failed to fetch all IDs:', error)
      multiSelectMode.value = false
    } finally {
      selectingAll.value = false
    }
  }

  /**
   * Clear selection and exit multi-select mode
   */
  function selectNone() {
    selectedItemIds.value = []
    multiSelectMode.value = false
  }

  /**
   * Remove specific IDs from selection
   * Used when items are removed from view (deleted, hidden, etc.)
   * Auto-exits multi-select mode if selection becomes empty
   *
   * @param {Array} idsToRemove - Array of item IDs to remove from selection
   */
  function removeFromSelection(idsToRemove) {
    if (!idsToRemove || idsToRemove.length === 0) return

    const idsSet = new Set(idsToRemove.map(id => parseInt(id)))
    const hadSelection = selectedItemIds.value.length > 0

    selectedItemIds.value = selectedItemIds.value.filter(id => !idsSet.has(parseInt(id)))

    // Auto-exit multi-select mode if selection becomes empty
    if (hadSelection && selectedItemIds.value.length === 0) {
      multiSelectMode.value = false
    }
  }

  /**
   * Get selected items from grid by their IDs
   * Requires getItemsByIds function to be provided
   *
   * @returns {Array} Array of selected item objects
   */
  const selectedItems = computed(() => {
    if (selectedItemIds.value.length === 0 || !getItemsByIds) return []
    return getItemsByIds(selectedItemIds.value)
  })

  /**
   * Compute which markers ALL selected items have (for toggle state in action bar)
   * Only includes markers that every selected item has
   * Requires markers and getItemsByIds to be provided
   *
   * @returns {Array} Array of marker IDs that all selected items have
   */
  const activeMarkerIds = computed(() => {
    if (selectedItemIds.value.length === 0 || !getItemsByIds || !markers) return []

    const items = getItemsByIds(selectedItemIds.value)
    if (items.length === 0) return []

    // Get marker IDs that ALL selected items have
    const activeIds = []
    const markerList = markers.value || markers // Support both ref and plain array

    for (const marker of markerList) {
      const allHaveMarker = items.every(item =>
        item.markers && item.markers.some(m => m.id === marker.id)
      )
      if (allHaveMarker) {
        activeIds.push(marker.id)
      }
    }

    return activeIds
  })

  /**
   * Compute tag counts for multi-select (how many selected items have each tag)
   * Used for showing tag state in bulk tag editor
   *
   * @returns {Object} Map of tag ID to count of how many selected items have that tag
   */
  const currentTagCounts = computed(() => {
    if (selectedItems.value.length === 0) return {}

    // Count how many items have each tag
    const counts = {}
    for (const item of selectedItems.value) {
      if (item.tags) {
        for (const tag of item.tags) {
          counts[tag.id] = (counts[tag.id] || 0) + 1
        }
      }
    }
    return counts
  })

  /**
   * Register keyboard shortcuts for multi-select
   * Designed to work with useGlobalKeyboardShortcuts
   *
   * Returns a handler function that should be called on keydown events
   * Handles: Escape (clear selection), Ctrl+A (select all), Ctrl+Shift+A (select none)
   *
   * @returns {Function} Keyboard event handler
   */
  function createKeyboardHandler() {
    return (event) => {
      // Escape - Clear selection when selection bar is visible
      if (event.key === 'Escape') {
        if (multiSelectMode.value && selectedItemIds.value.length > 0) {
          event.preventDefault()
          selectNone()
          return true  // Handled
        }
      }

      // Ctrl+A or Cmd+A - Select All (enter multi-select mode if needed)
      if ((event.ctrlKey || event.metaKey) && event.key === 'a' && !event.shiftKey) {
        event.preventDefault()
        if (!multiSelectMode.value) {
          multiSelectMode.value = true
        }
        selectAll()
        return true  // Handled
      }

      // Ctrl+Shift+A or Cmd+Shift+A - Select None
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && event.key === 'A') {
        event.preventDefault()
        if (multiSelectMode.value) {
          selectNone()
        }
        return true  // Handled
      }

      return false  // Not handled
    }
  }

  return {
    // State
    multiSelectMode,
    selectedItemIds,
    selectingAll,

    // Actions
    toggleMultiSelectMode,
    toggleItemSelection,
    handleToggleSelection,
    handleShiftClickRange,
    selectAll,
    selectNone,
    removeFromSelection,

    // Computed properties
    selectedItems,
    activeMarkerIds,
    currentTagCounts,

    // Keyboard shortcuts
    createKeyboardHandler
  }
}
