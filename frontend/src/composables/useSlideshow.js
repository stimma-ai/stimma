import { reactive, watch } from 'vue'
import { useTabNavigation } from './useTabNavigation'
import { makeProfileKey } from '../utils/storageKeys'

/**
 * Composable for managing slideshow state across views
 *
 * Provides:
 * - Reactive slideshow state
 * - Enter/exit slideshow functions
 * - Shared slideshow visibility (via useTabNavigation)
 * - Context persistence across navigation (saves/restores current media ID)
 * - Automatic cleanup
 *
 * @param {Object} options - Configuration options
 * @param {string} options.tabName - The tab name from TAB_NAMES to watch for back button sync
 * @returns {Object} Slideshow state and functions
 */
export function useSlideshow(options = {}) {
  const { tabName } = options

  // Get navigation system integration (if tab name provided)
  const navigation = tabName ? useTabNavigation() : null

  // Storage key for this specific tab
  const storageKey = tabName ? `${makeProfileKey('slideshow_context')}_${tabName}` : null

  // Slideshow state
  const slideshowState = reactive({
    active: false,
    totalCount: 0,
    startIndex: 0,
    currentMediaId: null, // Track current media ID for persistence
    mediaList: null,    // Shared media list (preferred over pageProvider)
    pageProvider: null, // Fallback for views without shared mediaList
    randomized: false,
    randomSeed: null
  })

  /**
   * Save slideshow context to sessionStorage
   */
  function saveContext() {
    if (!storageKey || !slideshowState.currentMediaId) return
    try {
      const context = {
        mediaId: slideshowState.currentMediaId,
        savedAt: Date.now()
      }
      sessionStorage.setItem(storageKey, JSON.stringify(context))
    } catch (e) {
      console.warn('[useSlideshow] Failed to save context:', e)
    }
  }

  /**
   * Load slideshow context from sessionStorage
   * @returns {{ mediaId: number, savedAt: number } | null}
   */
  function loadContext() {
    if (!storageKey) return null
    try {
      const stored = sessionStorage.getItem(storageKey)
      if (!stored) return null
      const context = JSON.parse(stored)
      // Context expires after 1 hour (user probably moved on)
      const ONE_HOUR = 60 * 60 * 1000
      if (Date.now() - context.savedAt > ONE_HOUR) {
        sessionStorage.removeItem(storageKey)
        return null
      }
      return context
    } catch (e) {
      console.warn('[useSlideshow] Failed to load context:', e)
      return null
    }
  }

  /**
   * Clear saved context
   */
  function clearContext() {
    if (!storageKey) return
    try {
      sessionStorage.removeItem(storageKey)
    } catch (e) {
      // Ignore
    }
  }

  /**
   * Enter slideshow mode with given parameters
   *
   * @param {Object} params - Slideshow parameters
   * @param {number} params.totalCount - Total number of items in slideshow
   * @param {number} params.startIndex - Starting index (0-based)
   * @param {Object} [params.mediaList] - Shared media list (preferred)
   * @param {Function} [params.pageProvider] - Async function (pageNumber, pageSize) => items[]
   * @param {boolean} [params.randomized=false] - Whether slideshow is randomized
   * @param {number|null} [params.randomSeed=null] - Random seed for stable randomization
   * @param {boolean} [params.restoreContext=false] - Whether to try restoring saved position
   */
  function enterSlideshow(params) {
    let startIndex = params.startIndex

    // Try to restore saved context if requested and mediaList is available
    if (params.restoreContext && params.mediaList) {
      const savedContext = loadContext()
      if (savedContext?.mediaId) {
        const restoredIndex = params.mediaList.findIndex(savedContext.mediaId)
        if (restoredIndex >= 0) {
          console.log(`[useSlideshow] Restored position for media ${savedContext.mediaId} at index ${restoredIndex}`)
          startIndex = restoredIndex
        } else {
          console.log(`[useSlideshow] Saved media ${savedContext.mediaId} no longer in list, using provided startIndex`)
        }
      }
    }

    slideshowState.active = true
    slideshowState.totalCount = params.totalCount
    slideshowState.startIndex = startIndex
    slideshowState.currentMediaId = null // Will be set by SlideshowMode when item loads
    slideshowState.mediaList = params.mediaList || null
    slideshowState.pageProvider = params.pageProvider || null
    slideshowState.randomized = params.randomized || false
    slideshowState.randomSeed = params.randomSeed || null

    // Notify the shared app chrome state (if integrated)
    if (navigation) {
      navigation.enterSlideshowMode()
    }
  }

  /**
   * Exit slideshow mode and return to grid view
   * @param {Object} [options] - Exit options
   * @param {boolean} [options.saveContext=true] - Whether to save current position for later restoration
   */
  function exitSlideshow(options = {}) {
    const { saveContext: shouldSave = true } = options

    // Save context before clearing state (if we have a valid media ID)
    if (shouldSave) {
      saveContext()
    }

    slideshowState.active = false
    slideshowState.totalCount = 0
    slideshowState.startIndex = 0
    slideshowState.currentMediaId = null
    slideshowState.mediaList = null
    slideshowState.pageProvider = null
    slideshowState.randomized = false
    slideshowState.randomSeed = null

    // Notify the shared app chrome state (if integrated)
    if (navigation) {
      navigation.exitSlideshowMode()
    }
  }

  /**
   * Update the current media ID (called by SlideshowMode when navigating)
   */
  function updateCurrentMediaId(mediaId) {
    slideshowState.currentMediaId = mediaId
  }

  // Watch for browser back button - sync slideshow state with global navigation
  if (navigation && tabName) {
    watch(() => navigation.slideshowActive.value, (newValue) => {
      // Only respond if we're on the correct tab
      if (navigation.activeTab.value !== tabName) return

      // Sync local slideshow state with global navigation state
      if (!newValue && slideshowState.active) {
        // Browser went back - save context before clearing state
        saveContext()
        slideshowState.active = false
        slideshowState.totalCount = 0
        slideshowState.startIndex = 0
        slideshowState.currentMediaId = null
        slideshowState.mediaList = null
        slideshowState.pageProvider = null
        slideshowState.randomized = false
        slideshowState.randomSeed = null
      }
    })
  }

  return {
    slideshowState,
    enterSlideshow,
    exitSlideshow,
    updateCurrentMediaId,
    clearContext,

    // Convenience properties for template binding
    isActive: () => slideshowState.active
  }
}
