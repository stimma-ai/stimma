import { reactive, watch } from 'vue'
import { useTabNavigation } from './useTabNavigation'

/**
 * Composable for managing slideshow state across views
 *
 * Provides:
 * - Reactive slideshow state
 * - Enter/exit slideshow functions
 * - Shared slideshow visibility (via useTabNavigation)
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
   * Enter slideshow mode with given parameters
   *
   * @param {Object} params - Slideshow parameters
   * @param {number} params.totalCount - Total number of items in slideshow
   * @param {number} params.startIndex - Starting index (0-based)
   * @param {Object} [params.mediaList] - Shared media list (preferred)
   * @param {Function} [params.pageProvider] - Async function (pageNumber, pageSize) => items[]
   * @param {boolean} [params.randomized=false] - Whether slideshow is randomized
   * @param {number|null} [params.randomSeed=null] - Random seed for stable randomization
   */
  function enterSlideshow(params) {
    const startIndex = params.startIndex

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
   */
  function exitSlideshow() {
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
        // Browser went back
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

    // Convenience properties for template binding
    isActive: () => slideshowState.active
  }
}
