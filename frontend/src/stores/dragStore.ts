/**
 * Global drag state store.
 * Tracks media being dragged for sidebar tool compatibility feedback.
 *
 * Uses Vue's reactive API for global state without Pinia dependency.
 */

import { ref, computed } from 'vue'
import { getMediaType, type MediaType } from '../utils/mediaTypes'

interface DraggedMediaInfo {
  mediaId: number
  fileFormat: string
  isVideo: boolean
}

// Global reactive state
const draggedMedia = ref<DraggedMediaInfo | null>(null)

/**
 * Get the current dragged media info.
 */
export const draggedMediaInfo = computed(() => draggedMedia.value)

/**
 * Get the media type of the dragged item.
 * Returns null if no drag in progress.
 */
export const draggedMediaType = computed((): MediaType | null => {
  if (!draggedMedia.value) return null
  return getMediaType({ file_format: draggedMedia.value.fileFormat })
})

/**
 * Check if the dragged item is a grid.
 */
export const isDraggingGrid = computed(() => {
  return draggedMedia.value?.fileFormat?.toLowerCase() === 'stimmagrid.json'
})

/**
 * Check if the dragged item is a video.
 */
export const isDraggingVideo = computed(() => {
  if (!draggedMedia.value) return false
  const format = draggedMedia.value.fileFormat?.toLowerCase() || ''
  const videoFormats = ['mp4', 'webm', 'mov', 'avi', 'mkv', 'ogg']
  return videoFormats.includes(format) || draggedMedia.value.isVideo
})

/**
 * Set the current dragged media.
 * Call this from dragstart handlers.
 */
export function setDraggedMedia(info: DraggedMediaInfo) {
  draggedMedia.value = info
}

/**
 * Clear the current dragged media.
 * Call this from dragend handlers.
 */
export function clearDraggedMedia() {
  draggedMedia.value = null
}

/**
 * Hook for use in Vue components.
 * Returns all drag state and methods.
 */
export function useDragStore() {
  return {
    draggedMediaInfo,
    draggedMediaType,
    isDraggingGrid,
    isDraggingVideo,
    setDraggedMedia,
    clearDraggedMedia
  }
}
