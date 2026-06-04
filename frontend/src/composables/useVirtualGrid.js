import { ref } from 'vue'

/**
 * Composable for managing virtual grid state and operations
 *
 * Provides:
 * - Page provider function standardization
 * - Loading state management
 * - Total count tracking
 * - Filter key for forcing grid reloads
 *
 * @param {Object} options - Configuration options
 * @param {Function} options.fetchMedia - Function to fetch media (params) => { items, total }
 * @param {Function} options.buildFilterParams - Function to build API filter parameters
 * @param {Function} options.fetchMediaIds - Function to fetch all media IDs matching filters (for select all)
 * @returns {Object} Virtual grid state and functions
 */
export function useVirtualGrid(options = {}) {
  const { fetchMedia, buildFilterParams, fetchMediaIds } = options

  // State
  const loading = ref(false)
  const totalCount = ref(0)
  const filterKey = ref(0)  // Increment this to force grid to reload

  /**
   * Page provider for virtual grid - called by the grid when it needs to load a page
   * NOTE: vue-virtual-scroll-grid uses 0-based page indexing, but APIs typically use 1-based
   *
   * @param {number} pageNumber - 0-based page number from grid
   * @param {number} pageSize - Number of items per page
   * @returns {Promise<Array>} Array of items for the page
   */
  async function fetchPageItems(pageNumber, pageSize) {
    if (!fetchMedia || !buildFilterParams) {
      console.error('[useVirtualGrid] fetchMedia or buildFilterParams not provided')
      return []
    }

    const params = buildFilterParams()
    const response = await fetchMedia({
      ...params,
      page: pageNumber + 1,  // Convert from 0-based to 1-based
      page_size: pageSize
    })
    return response.items || []
  }

  /**
   * Load media with current filters
   * Fetches first page to get total count and updates grid
   * Optionally filters selection to only items still visible
   *
   * @param {Object} options - Load options
   * @param {Array} [options.selectedItemIds] - Current selected item IDs to filter
   * @param {Function} [options.onSelectionFiltered] - Callback when selection is filtered: (newIds) => void
   */
  async function loadMedia(loadOptions = {}) {
    if (!fetchMedia || !buildFilterParams) {
      console.error('[useVirtualGrid] fetchMedia or buildFilterParams not provided')
      return
    }

    const { selectedItemIds, onSelectionFiltered } = loadOptions

    loading.value = true
    try {
      const params = buildFilterParams()

      // Just fetch first page to get total count
      const response = await fetchMedia({
        ...params,
        page: 1,
        page_size: 1
      })
      totalCount.value = response.total || 0

      // If we have selected items, filter selection to only items still visible
      if (selectedItemIds && selectedItemIds.length > 0 && fetchMediaIds) {
        const idsResponse = await fetchMediaIds(params)
        const visibleIds = new Set(idsResponse.ids || [])
        const filteredIds = selectedItemIds.filter(id => visibleIds.has(id))

        // Notify callback with filtered selection
        if (onSelectionFiltered) {
          onSelectionFiltered(filteredIds)
        }
      }

      // Increment filterKey to force grid to reload
      filterKey.value++
    } catch (error) {
      console.error('[useVirtualGrid] Failed to load media:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  /**
   * Fetch all media IDs matching current filters
   * Used for "select all" functionality
   *
   * @returns {Promise<Array>} Array of all media IDs
   */
  async function fetchAllIds() {
    if (!fetchMediaIds || !buildFilterParams) {
      console.error('[useVirtualGrid] fetchMediaIds or buildFilterParams not provided')
      return []
    }

    const params = buildFilterParams()
    const response = await fetchMediaIds(params)
    return response.ids || []
  }

  /**
   * Force grid to reload by incrementing filter key
   * Useful when you know data has changed but don't want to refetch total count
   */
  function forceGridReload() {
    filterKey.value++
  }

  return {
    // State
    loading,
    totalCount,
    filterKey,

    // Functions
    fetchPageItems,
    loadMedia,
    fetchAllIds,
    forceGridReload
  }
}
