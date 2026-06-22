import { reactive, ref } from 'vue'
import { useMediaApi } from './useMediaApi'
import { cloneDefaultBrowseFilters, normalizeBrowseFilters } from '../constants/browseFilters'

function createScopedState() {
  return {
    filters: reactive(cloneDefaultBrowseFilters()),
    similarSearchActive: ref(false),
    similarSearchSourceItem: ref(null),
    similarSearchSourceItems: ref([]),
    filterChangeCounter: ref(0)
  }
}

const scopedState = {
  browse: createScopedState(),
  trash: createScopedState()
}

export function useBrowseFilters(scope = 'browse') {
  const state = scopedState[scope] || scopedState.browse
  const {
    filters,
    similarSearchActive,
    similarSearchSourceItem,
    similarSearchSourceItems,
    filterChangeCounter
  } = state

  // Set filters (used when navigating to browse with specific filters)
  function setFilters(newFilters) {
    Object.assign(filters, normalizeBrowseFilters(newFilters))
    filterChangeCounter.value++
  }

  // Set a single filter
  function setFilter(key, value) {
    filters[key] = value
  }

  // Clear all filters
  function clearFilters() {
    Object.assign(filters, cloneDefaultBrowseFilters())
    clearSimilarSearch()
  }

  // Set similar search
  function setSimilarSearch(mediaIds) {
    const ids = Array.isArray(mediaIds) ? mediaIds : [mediaIds]
    filters.similarTo = ids
    filters.similarFaceTo = []
    filters.similarToText = ''
    filters.sortBy = 'similarity'
    similarSearchActive.value = true
  }

  function setSimilarFaceSearch(mediaIds) {
    const ids = Array.isArray(mediaIds) ? mediaIds : [mediaIds]
    filters.similarFaceTo = ids
    filters.similarTo = []
    filters.similarToText = ''
    filters.sortBy = 'similarity'
    similarSearchActive.value = true
  }

  // Clear similar search
  function clearSimilarSearch() {
    similarSearchActive.value = false
    similarSearchSourceItem.value = null
    similarSearchSourceItems.value = []
    filters.similarTo = []
    filters.similarFaceTo = []
    filters.similarToText = ''
    if (filters.sortBy === 'similarity') {
      filters.sortBy = 'created_desc'
    }
    // Trigger reload in BrowseGridView
    filterChangeCounter.value++
  }

  // Set keyword filter (clears other filters)
  function setKeywordFilter(keyword) {
    console.log('[useBrowseFilters] setKeywordFilter:', keyword)
    setFilters({
      selectedKeywords: [keyword]
    })
    console.log('[useBrowseFilters] filters after set:', JSON.stringify(filters))
  }

  // Set tag filter (clears other filters)
  function setTagFilter(tagId) {
    console.log('[useBrowseFilters] setTagFilter:', tagId)
    setFilters({
      selectedTags: [tagId]
    })
    console.log('[useBrowseFilters] filters after set:', JSON.stringify(filters))
  }

  // Set similar filter (clears other filters)
  async function setSimilarFilter(mediaId, mediaItem = null) {
    console.log('[useBrowseFilters] setSimilarFilter:', mediaId, mediaItem)
    clearFilters()
    setSimilarSearch(mediaId)

    // Fetch the source item if not provided
    if (!mediaItem) {
      const { getMediaItem } = useMediaApi()
      try {
        mediaItem = await getMediaItem(mediaId)
      } catch (error) {
        console.error('Failed to fetch media item for similar search:', error)
      }
    }

    // Set the source item for display
    if (mediaItem) {
      similarSearchSourceItem.value = mediaItem
      similarSearchSourceItems.value = [mediaItem]
    }

    // Trigger reload in BrowseGridView
    filterChangeCounter.value++

    console.log('[useBrowseFilters] filters after set:', JSON.stringify(filters))
    console.log('[useBrowseFilters] similarSearchActive:', similarSearchActive.value)
    console.log('[useBrowseFilters] similarSearchSourceItem:', similarSearchSourceItem.value)
    console.log('[useBrowseFilters] similarSearchSourceItems:', similarSearchSourceItems.value)
  }

  // Set face-similar filter (clears other filters)
  async function setSimilarFaceFilter(mediaId, mediaItem = null) {
    console.log('[useBrowseFilters] setSimilarFaceFilter:', mediaId, mediaItem)
    clearFilters()
    setSimilarFaceSearch(mediaId)

    // Fetch the source item if not provided
    if (!mediaItem) {
      const { getMediaItem } = useMediaApi()
      try {
        mediaItem = await getMediaItem(mediaId)
      } catch (error) {
        console.error('Failed to fetch media item for face similarity search:', error)
      }
    }

    // Set the source item for display
    if (mediaItem) {
      similarSearchSourceItem.value = mediaItem
      similarSearchSourceItems.value = [mediaItem]
    }

    // Trigger reload in BrowseGridView
    filterChangeCounter.value++

    console.log('[useBrowseFilters] filters after face set:', JSON.stringify(filters))
    console.log('[useBrowseFilters] similarSearchActive:', similarSearchActive.value)
    console.log('[useBrowseFilters] similarSearchSourceItem:', similarSearchSourceItem.value)
    console.log('[useBrowseFilters] similarSearchSourceItems:', similarSearchSourceItems.value)
  }

  return {
    filters,
    similarSearchActive,
    similarSearchSourceItem,
    similarSearchSourceItems,
    filterChangeCounter,
    setFilters,
    setFilter,
    clearFilters,
    setSimilarSearch,
    clearSimilarSearch,
    setSimilarFaceSearch,
    setKeywordFilter,
    setTagFilter,
    setSimilarFilter,
    setSimilarFaceFilter
  }
}
