import { reactive, ref, computed, shallowRef } from 'vue'

/**
 * Shared media list composable
 *
 * Provides a single source of truth for media items that can be shared
 * between VirtualMediaGrid and SlideshowMode. This ensures both views
 * always see the same items in the same order, preventing divergence bugs.
 *
 * @param options Configuration options
 * @returns Shared media list state and methods
 */
export interface MediaItem {
  id: number
  file_hash: string
  file_format: string
  [key: string]: any
}

export interface FetchMediaParams {
  page?: number
  page_size?: number
  [key: string]: any
}

export interface FetchMediaResponse {
  items: MediaItem[]
  total: number  // API uses 'total', not 'total_count'
}

export interface UseMediaListOptions {
  /** Function to fetch media from API */
  fetchMedia: (params: FetchMediaParams) => Promise<FetchMediaResponse>
  /** Function to build current filter parameters */
  buildFilterParams: () => FetchMediaParams
  /** Page size for the grid (default 200) */
  gridPageSize?: number
  /** Page size for slideshow lazy loading (default 50) */
  slideshowPageSize?: number
}

export interface MediaListState {
  /** Items indexed by position */
  itemsCache: Map<number, MediaItem>
  /** Which pages have been loaded (keyed by "pageNumber:pageSize") */
  loadedPages: Set<string>
  /** Promises for pages currently loading (keyed by "pageNumber:pageSize") */
  loadingPages: Map<string, Promise<MediaItem[]>>
  /** Total count from API */
  totalCount: number
  /** IDs that have been soft-deleted locally */
  removedIds: Set<number>
  /** Snapshot of filter params when media list was created/reset */
  filterParams: FetchMediaParams | null
}

export function useMediaList(options: UseMediaListOptions) {
  const {
    fetchMedia,
    buildFilterParams,
    gridPageSize = 200,
    slideshowPageSize = 50
  } = options

  // Core state - using shallowRef for Maps/Sets to avoid deep reactivity overhead
  const itemsCache = shallowRef<Map<number, MediaItem>>(new Map())
  const loadedPages = shallowRef<Set<string>>(new Set())
  const loadingPages = ref<Map<string, Promise<MediaItem[]>>>(new Map())
  const totalCount = ref(0)
  const removedIds = shallowRef<Set<number>>(new Set())
  const filterParams = ref<FetchMediaParams | null>(null)

  // Trigger for reactivity when cache contents change
  const cacheVersion = ref(0)

  /**
   * Notify that cache contents changed (for reactivity)
   */
  function notifyCacheChanged() {
    cacheVersion.value++
  }

  /**
   * Load a page of items into the shared cache
   * @param pageNumber 0-indexed page number
   * @param pageSize Number of items per page
   * @returns The loaded items
   */
  async function loadPage(pageNumber: number, pageSize: number = gridPageSize): Promise<MediaItem[]> {
    // Guard against invalid page numbers
    if (!Number.isFinite(pageNumber) || pageNumber < 0) {
      console.warn(`[useMediaList] Invalid page number: ${pageNumber}`)
      return []
    }

    // Create a unique key for this page request (page number + page size)
    const pageKey = `${pageNumber}:${pageSize}`

    // Check if already loaded with this page size
    if (loadedPages.value.has(pageKey)) {
      // Return cached items for this page
      const startIndex = pageNumber * pageSize
      const items: MediaItem[] = []
      for (let i = 0; i < pageSize; i++) {
        const item = itemsCache.value.get(startIndex + i)
        if (item) items.push(item)
      }
      return items
    }

    // Check if this page is currently loading (keyed by page+size)
    if (loadingPages.value.has(pageKey)) {
      return loadingPages.value.get(pageKey)!
    }

    // Start loading
    const loadPromise = (async () => {
      try {
        const params = filterParams.value || buildFilterParams()
        const response = await fetchMedia({
          ...params,
          page: pageNumber + 1, // API uses 1-indexed pages
          page_size: pageSize
        })

        const items = response.items

        // Update total count
        totalCount.value = response.total

        // Cache items by index
        const startIndex = pageNumber * pageSize
        const newCache = new Map(itemsCache.value)
        items.forEach((item, i) => {
          newCache.set(startIndex + i, item)
        })
        itemsCache.value = newCache

        // Mark page as loaded
        const newLoadedPages = new Set(loadedPages.value)
        newLoadedPages.add(pageKey)
        loadedPages.value = newLoadedPages

        notifyCacheChanged()
        return items
      } catch (error) {
        console.error(`[useMediaList] Failed to load page ${pageNumber}:`, error)
        throw error
      } finally {
        loadingPages.value.delete(pageKey)
      }
    })()

    loadingPages.value.set(pageKey, loadPromise)
    return loadPromise
  }

  /**
   * Get item at a specific index (returns null if not loaded)
   */
  function getItem(index: number): MediaItem | null {
    // Access cacheVersion to trigger reactivity
    void cacheVersion.value
    return itemsCache.value.get(index) || null
  }

  /**
   * Ensure an item at a specific index is loaded
   * @param index The item index
   * @param pageSize Page size to use (defaults to slideshow page size for smaller fetches)
   */
  async function ensureItemLoaded(index: number, pageSize: number = slideshowPageSize): Promise<void> {
    if (!Number.isFinite(index) || index < 0) {
      console.warn(`[useMediaList] Invalid index for ensureItemLoaded: ${index}`)
      return
    }

    // Already cached?
    if (itemsCache.value.has(index)) {
      return
    }

    // Load the page containing this index
    const pageNumber = Math.floor(index / pageSize)
    await loadPage(pageNumber, pageSize)
  }

  /**
   * Get all cached items in order
   */
  function getOrderedItems(): MediaItem[] {
    // Access cacheVersion for reactivity
    void cacheVersion.value

    const items: MediaItem[] = []
    const maxIndex = itemsCache.value.size > 0
      ? Math.max(...itemsCache.value.keys())
      : -1

    for (let i = 0; i <= maxIndex; i++) {
      const item = itemsCache.value.get(i)
      if (item) {
        items.push(item)
      }
    }

    return items
  }

  /**
   * Remove an item and shift subsequent items down to maintain contiguous indexing.
   * This is the primary removal method - always keeps cache indices contiguous.
   * @param id The item ID to remove
   * @returns The index where the item was removed, or -1 if not found
   */
  function removeItem(id: number): number {
    const cacheIndex = findIndex(id)
    if (cacheIndex < 0) {
      // Item not in sparse cache but still exists in this view -
      // decrement totalCount to keep it accurate
      totalCount.value = Math.max(0, totalCount.value - 1)
      notifyCacheChanged()
      return -1
    }

    // Build new cache with item removed and subsequent items shifted down
    const newCache = new Map<number, MediaItem>()
    for (const [index, item] of itemsCache.value.entries()) {
      if (index < cacheIndex) {
        newCache.set(index, item)
      } else if (index > cacheIndex) {
        newCache.set(index - 1, item)
      }
      // Skip the item being removed
    }

    itemsCache.value = newCache
    totalCount.value = Math.max(0, totalCount.value - 1)
    // Subsequent indices shifted down, so the page-load tracking no longer maps
    // to the cache. Invalidate it (see removeItems for the full rationale).
    loadedPages.value = new Set()
    notifyCacheChanged()

    return cacheIndex
  }

  /**
   * Find the index of an item by ID
   * @returns The index where the item was found, or -1 if not found
   */
  function findIndex(id: number): number {
    for (const [index, item] of itemsCache.value.entries()) {
      if (item && item.id === id) {
        return index
      }
    }
    return -1
  }

  /**
   * Remove multiple items and shift subsequent items down.
   * Processes removals from highest index to lowest to maintain correct shifting.
   * @param ids The item IDs to remove
   */
  function removeItems(ids: number[]): void {
    if (!ids || ids.length === 0) return

    const idsToRemove = new Set(ids)
    const oldCache = itemsCache.value
    const newCache = new Map<number, MediaItem>()
    let newIndex = 0
    let removedCount = 0

    // Single pass: iterate in index order, compact into new cache
    const maxIndex = oldCache.size > 0 ? Math.max(...oldCache.keys()) : -1
    for (let i = 0; i <= maxIndex; i++) {
      const item = oldCache.get(i)
      if (!item) continue
      if (idsToRemove.has(item.id)) {
        removedCount++
      } else {
        newCache.set(newIndex++, item)
      }
    }

    // Use idsToRemove.size (not removedCount) because with sparse/lazy-loaded
    // caches, not all items may be in the cache yet. The caller knows these IDs
    // belong to this view (e.g. from "select all"), so we trust the full count.
    const adjustedCount = Math.max(removedCount, idsToRemove.size)

    itemsCache.value = newCache
    totalCount.value = Math.max(0, totalCount.value - adjustedCount)
    // Surviving items were shifted down to keep indices contiguous, so the
    // page-load tracking ("pageNum:pageSize" -> loaded) no longer maps to the
    // cache. Clearing it forces the grid to re-fetch pages on the next scroll
    // instead of treating now-empty index ranges as "already loaded" — the
    // cause of the gap-toothed grid and permanently-spinning cells after a
    // large bulk delete. (prependItems/silentReload clear it for the same
    // reason.) itemsCache is kept so survivors stay visible during the refetch.
    loadedPages.value = new Set()
    notifyCacheChanged()
  }

  /**
   * Prepend items to the beginning (for realtime updates)
   * Shifts existing indices accordingly
   */
  function prependItems(items: MediaItem[]): void {
    if (!items || items.length === 0) return

    // Deduplicate
    const existingIds = new Set<number>()
    for (const item of itemsCache.value.values()) {
      if (item?.id) existingIds.add(item.id)
    }
    const uniqueItems = items.filter(item => item?.id && !existingIds.has(item.id))

    if (uniqueItems.length === 0) return

    const countToAdd = uniqueItems.length

    // Create new cache with shifted indices
    const newCache = new Map<number, MediaItem>()

    // Add new items at beginning
    uniqueItems.forEach((item, i) => {
      newCache.set(i, item)
    })

    // Shift existing items
    for (const [index, item] of itemsCache.value.entries()) {
      newCache.set(index + countToAdd, item)
    }

    itemsCache.value = newCache

    // Clear loaded pages (indices shifted)
    loadedPages.value = new Set([`0:${gridPageSize}`])

    // Update total count
    totalCount.value += countToAdd

    notifyCacheChanged()
  }

  /**
   * Update a cached item in place
   */
  function updateItem(id: number, updates: Partial<MediaItem>): void {
    const newCache = new Map(itemsCache.value)
    for (const [index, item] of newCache.entries()) {
      if (item && item.id === id) {
        newCache.set(index, { ...item, ...updates })
        break
      }
    }
    itemsCache.value = newCache
    notifyCacheChanged()
  }

  /**
   * Reset the cache (when filters change)
   */
  function reset(newFilterParams?: FetchMediaParams): void {
    itemsCache.value = new Map()
    loadedPages.value = new Set()
    loadingPages.value = new Map()
    removedIds.value = new Set()
    filterParams.value = newFilterParams || null
    notifyCacheChanged()
  }

  /**
   * Silent reload - fetches fresh data and updates only if changed.
   * Does not show loading state or cause visible UI flicker if data is unchanged.
   * @returns true if data was updated, false if unchanged
   */
  async function silentReload(): Promise<boolean> {
    try {
      const params = filterParams.value || buildFilterParams()
      const response = await fetchMedia({
        ...params,
        page: 1,
        page_size: 1
      })

      const newTotal = response.total
      const oldTotal = totalCount.value

      if (newTotal !== oldTotal) {
        // Total count changed - update it
        // The grid will watch totalCount and rebuild appropriately
        totalCount.value = newTotal

        // Clear loaded pages to force fresh data on next scroll
        // Keep itemsCache so grid can still show something while re-fetching
        loadedPages.value = new Set()

        notifyCacheChanged()
        return true
      }

      // Count is the same - check if first page items are different
      // This catches cases where items were replaced but count stayed same
      if (itemsCache.value.size > 0) {
        const firstPageResponse = await fetchMedia({
          ...params,
          page: 1,
          page_size: Math.min(20, gridPageSize) // Just check first few items
        })

        const firstCachedItem = itemsCache.value.get(0)
        const firstNewItem = firstPageResponse.items[0]

        if (firstCachedItem && firstNewItem && firstCachedItem.id !== firstNewItem.id) {
          // First item is different - data has changed, clear cache
          loadedPages.value = new Set()
          notifyCacheChanged()
          return true
        }
      }

      return false
    } catch (error) {
      console.error('[useMediaList] Silent reload failed:', error)
      return false
    }
  }

  /**
   * Initialize with filter params and optionally load first page
   */
  async function initialize(params: FetchMediaParams, loadFirstPage: boolean = true): Promise<void> {
    reset(params)
    if (loadFirstPage) {
      await loadPage(0)
    }
  }

  /**
   * Effective total count (same as totalCount since we shift on removal)
   */
  const effectiveTotal = computed(() => {
    void cacheVersion.value
    return totalCount.value
  })

  /**
   * Check if an item ID has been removed
   */
  function isRemoved(id: number): boolean {
    return removedIds.value.has(id)
  }

  return {
    // State (reactive)
    itemsCache,
    loadedPages,
    totalCount,
    removedIds,  // Kept for backward compatibility (always empty now)
    effectiveTotal,
    cacheVersion,
    filterParams,

    // Methods
    loadPage,
    getItem,
    ensureItemLoaded,
    getOrderedItems,
    removeItem,  // Now shifts indices (was soft-delete before)
    removeItems, // Now shifts indices (was soft-delete before)
    findIndex,
    prependItems,
    updateItem,
    reset,
    initialize,
    silentReload,
    isRemoved,
    notifyCacheChanged
  }
}

export type MediaList = ReturnType<typeof useMediaList>
