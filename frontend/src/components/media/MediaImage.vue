<template>
  <!--
    Media library image component.
    Wraps AppImage with media-specific functionality:
    - URL computation from mediaId/fileHash
    - Drag-drop as source (for in-app transfers)
    - Context menu integration (enabled by default when mediaId is provided)
  -->
  <AppImage
    :src="imageSrc"
    :alt="alt"
    :contain="contain"
    :container-class="containerClass"
    :img-class="imgClass"
    :loading="loading"
    :draggable="draggable"
    @click="$emit('click', $event)"
    @load="$emit('load', $event)"
    @error="$emit('error', $event)"
    @dragstart="handleDragStart"
    @dragend="onDragEnd"
    @contextmenu="handleContextMenu"
  >
    <slot />
  </AppImage>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import AppImage from './AppImage.vue'
import { useMediaApi } from '../../composables/useMediaApi'
import { useMediaContextMenu } from '../../composables/useMediaContextMenu'
import { useTauriDrag } from '../../composables/useTauriDrag'
import { createDragPreview, handleDragEnd } from '../../composables/useDragPreview'

const contextMenu = useMediaContextMenu()
const { isTauri, handleDragStart: tauriHandleDragStart } = useTauriDrag()

interface Props {
  /** Media ID from database (use this OR fileHash) */
  mediaId?: number
  /** File hash (use this OR mediaId) */
  fileHash?: string
  /** File path for native drag in Tauri (optional, improves drag-to-desktop) */
  filePath?: string
  /** Display thumbnail (true) or full file (false). Default: true */
  thumbnail?: boolean
  /** Thumbnail size hint (128, 256, etc). Only used when thumbnail=true */
  thumbnailSize?: number
  /** Thumbnail generation mode. 'crop' is square-cropped, 'fit' preserves source aspect ratio. */
  thumbnailMode?: 'crop' | 'fit'
  /** Alt text for image */
  alt?: string
  /** Use object-contain (fit whole image). Default is object-cover (fill, may crop). */
  contain?: boolean
  /** Additional classes for the container div */
  containerClass?: string
  /** Additional classes for the img element */
  imgClass?: string
  /** Loading attribute for lazy loading */
  loading?: 'lazy' | 'eager'
  /** Whether the image is draggable. Default: true */
  draggable?: boolean | 'true' | 'false'
  /**
   * Enable built-in context menu. Default: true when mediaId is provided.
   * Set to false to handle contextmenu event yourself.
   */
  enableContextMenu?: boolean
  /** File format (e.g., 'png', 'mp4', 'stimmagrid.json') for drag compatibility */
  fileFormat?: string
  /** Whether this is a video file */
  isVideo?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  thumbnail: true,
  thumbnailMode: 'crop',
  alt: '',
  contain: false,
  containerClass: '',
  imgClass: '',
  loading: 'lazy',
  draggable: true,
  enableContextMenu: true  // Enabled by default - context menu fetches item info itself
})

const emit = defineEmits<{
  (e: 'click', event: MouseEvent): void
  (e: 'load', event: Event): void
  (e: 'error', event: Event): void
  (e: 'dragstart', event: DragEvent): void
  (e: 'contextmenu', payload: { event: MouseEvent; mediaId?: number; fileHash?: string }): void
}>()

const { getThumbnailUrl, getMediaFileUrl } = useMediaApi()

// Compute image source URL
// Prefer fileHash for URLs (hash-based URLs are the standard, more cache-friendly)
// Fall back to mediaId if hash not provided
const imageSrc = computed(() => {
  const identifier = props.fileHash ?? props.mediaId
  if (!identifier) return undefined

  if (props.thumbnail) {
    return getThumbnailUrl(identifier, props.thumbnailSize, { mode: props.thumbnailMode })
  }
  return getMediaFileUrl(identifier)
})

async function handleDragStart(event: DragEvent) {
  if (!event.dataTransfer) return

  // Hold ⌥ (Option) to drag the real file out to Finder/desktop (native
  // Tauri drag). A plain drag is an in-app transfer (HTML5) that drop zones
  // can read via application/x-media-id. The two are mutually exclusive on
  // WKWebView, so the modifier picks the lane up front instead of trying to
  // do both on one gesture.
  if (isTauri.value && event.altKey && props.mediaId && props.filePath) {
    await tauriHandleDragStart(event, props.mediaId, props.filePath)
    emit('dragstart', event)
    return
  }

  // Create a smaller drag preview image
  const identifier = props.mediaId ?? props.fileHash
  if (identifier) {
    const thumbnailUrl = getThumbnailUrl(identifier, 128)
    createDragPreview(event, thumbnailUrl, props.mediaId, props.fileFormat, props.isVideo)
  }

  // Also set file hash for in-app drag-drop
  if (props.fileHash) {
    event.dataTransfer.setData('application/x-file-hash', props.fileHash)
  }

  emit('dragstart', event)
}

function onDragEnd() {
  handleDragEnd()
}

function handleContextMenu(event: MouseEvent) {
  // If context menu is enabled and we have a mediaId, show the menu
  // The menu component fetches all needed item info (isVideo, isTrashed, etc.)
  if (props.enableContextMenu && props.mediaId) {
    contextMenu.show({
      event,
      mediaId: props.mediaId,
      fileHash: props.fileHash
    })
    return
  }

  // Otherwise emit event for parent to handle
  emit('contextmenu', {
    event,
    mediaId: props.mediaId,
    fileHash: props.fileHash
  })
}
</script>
