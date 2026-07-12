/**
 * Global drag state store.
 * Tracks media being dragged for sidebar tool compatibility feedback.
 *
 * Uses Vue's reactive API for global state without Pinia dependency.
 */

import axios from 'axios'
import { ref, computed } from 'vue'
import { getMediaType, type MediaType } from '../utils/mediaTypes'

interface DraggedMediaInfo {
  mediaId: number
  fileFormat: string
  isVideo: boolean
  mediaIds?: number[]
  items?: Array<{
    id: number
    file_format?: string
    is_video?: boolean
    is_audio?: boolean
  }>
  loading?: boolean
}

// Global reactive state
const draggedMedia = ref<DraggedMediaInfo | null>(null)

/**
 * Get the current dragged media info.
 */
export const draggedMediaInfo = computed(() => draggedMedia.value)

/** Full selection records used by the shared handoff planner. */
export const draggedMediaItems = computed(() => draggedMedia.value?.items || [])

export const draggedMediaCount = computed(() =>
  draggedMedia.value?.mediaIds?.length || (draggedMedia.value ? 1 : 0)
)

/**
 * Get the media type of the dragged item.
 * Returns null if no drag in progress.
 */
export const draggedMediaType = computed((): MediaType | null => {
  if (!draggedMedia.value) return null
  const first = draggedMedia.value.items?.[0]
  if (first?.is_audio) return 'audio'
  if (first?.is_video) return 'video'
  if (first?.file_format) return getMediaType({ file_format: first.file_format })
  // isVideo is authoritative when the source couldn't supply a real file
  // extension (e.g. dragging from a completed-job tile or a library-backed
  // reference item) — falling through to fileFormat-based detection would
  // silently default those drags to 'image' (getMediaType's fallback) and
  // make video-only tools look incompatible.
  if (draggedMedia.value.isVideo) return 'video'
  return draggedMedia.value.fileFormat
    ? getMediaType({ file_format: draggedMedia.value.fileFormat })
    : null
})

/**
 * Check if the dragged item is a grid.
 */
export const isDraggingGrid = computed(() => {
  return draggedMedia.value?.items?.some(item => item.file_format?.toLowerCase() === 'stimmagrid.json')
    || draggedMedia.value?.fileFormat?.toLowerCase() === 'stimmagrid.json'
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
  const mediaIds = info.mediaIds?.length ? info.mediaIds : [info.mediaId]
  const first = {
    id: info.mediaId,
    file_format: info.fileFormat || undefined,
    is_video: info.isVideo || undefined,
  }
  draggedMedia.value = {
    ...info,
    mediaIds,
    items: info.items?.length ? info.items : [first],
    loading: true,
  }

  // IDs are the canonical transfer contract. Hydrate from the API so sidebar
  // capability never depends on whether a particular source happened to pass
  // file-format flags to its drag-preview helper.
  const activeIds = mediaIds.join(',')
  void Promise.all(mediaIds.map(id => axios.get(`/api/media/${id}`).then(response => response.data)))
    .then(items => {
      if (draggedMedia.value?.mediaIds?.join(',') !== activeIds) return
      draggedMedia.value = { ...draggedMedia.value, items, loading: false }
    })
    .catch(() => {
      if (draggedMedia.value?.mediaIds?.join(',') !== activeIds) return
      draggedMedia.value = { ...draggedMedia.value, loading: false }
    })
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
    draggedMediaItems,
    draggedMediaCount,
    draggedMediaType,
    isDraggingGrid,
    isDraggingVideo,
    setDraggedMedia,
    clearDraggedMedia
  }
}
