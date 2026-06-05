import { reactive, readonly } from 'vue'
import { useMediaApi } from './useMediaApi'

/**
 * Composable for managing image comparison state
 *
 * Provides:
 * - Reactive compare state
 * - Enter/exit compare functions
 * - Swap images function
 * - Slider position management
 */
export function useCompare() {
  const { getMediaItem } = useMediaApi()

  // Compare state
  const compareState = reactive({
    active: false,
    leftMediaId: null,
    rightMediaId: null,
    leftItem: null,      // Full media item with generation_metadata
    rightItem: null,
    sliderPosition: 50,  // 0-100%
    loading: false,
    error: null,
    returnTo: null       // 'slideshow' if we should return there on exit
  })

  /**
   * Enter compare mode with two media items
   *
   * @param {Object} params - Compare parameters
   * @param {number} params.leftMediaId - Left image media ID
   * @param {number} params.rightMediaId - Right image media ID
   * @param {string} [params.returnTo] - Where to return on exit ('slideshow' or null)
   */
  async function enterCompare({ leftMediaId, rightMediaId, returnTo = null }) {
    console.log('[useCompare] enterCompare called with:', { leftMediaId, rightMediaId, returnTo })
    if (!leftMediaId || !rightMediaId) {
      console.error('[useCompare] Both leftMediaId and rightMediaId are required')
      return
    }

    console.log('[useCompare] Setting compareState.active = true')
    compareState.active = true
    compareState.leftMediaId = leftMediaId
    compareState.rightMediaId = rightMediaId
    compareState.sliderPosition = 50
    compareState.loading = true
    compareState.error = null
    compareState.returnTo = returnTo

    try {
      // Fetch full media items in parallel
      const [leftItem, rightItem] = await Promise.all([
        getMediaItem(leftMediaId),
        getMediaItem(rightMediaId)
      ])

      compareState.leftItem = leftItem
      compareState.rightItem = rightItem
    } catch (err) {
      console.error('[useCompare] Failed to load media items:', err)
      compareState.error = 'Failed to load images for comparison'
    } finally {
      compareState.loading = false
    }
  }

  /**
   * Exit compare mode
   * @returns {string|null} Where to return to ('slideshow' or null)
   */
  function exitCompare() {
    const returnTo = compareState.returnTo
    compareState.active = false
    compareState.leftMediaId = null
    compareState.rightMediaId = null
    compareState.leftItem = null
    compareState.rightItem = null
    compareState.sliderPosition = 50
    compareState.loading = false
    compareState.error = null
    compareState.returnTo = null
    return returnTo
  }

  /**
   * Swap left and right images
   */
  function swapImages() {
    const tempId = compareState.leftMediaId
    const tempItem = compareState.leftItem

    compareState.leftMediaId = compareState.rightMediaId
    compareState.leftItem = compareState.rightItem
    compareState.rightMediaId = tempId
    compareState.rightItem = tempItem

    // Invert slider position so visual comparison stays consistent
    compareState.sliderPosition = 100 - compareState.sliderPosition
  }

  /**
   * Update slider position
   * @param {number} position - Position 0-100
   */
  function setSliderPosition(position) {
    compareState.sliderPosition = Math.max(0, Math.min(100, position))
  }

  return {
    compareState: readonly(compareState),
    enterCompare,
    exitCompare,
    swapImages,
    setSliderPosition,

    // Convenience property for template binding
    isActive: () => compareState.active
  }
}
