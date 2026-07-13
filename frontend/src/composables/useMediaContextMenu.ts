import { ref, readonly } from 'vue'

export interface MediaContextMenuState {
  visible: boolean
  x: number
  y: number
  bottomY?: number        // If set, anchor menu bottom to this y-coordinate instead of top
  mediaId?: number
  assetId?: number
  fileHash?: string
  mediaIds?: number[]     // All target IDs (for multi-selection)
  assetIds?: number[]     // Stable browser/organization identities
  selectedItems?: any[]   // Full item objects (for Send to Tool)
  inBoard?: boolean       // Whether viewing a board section
  boardSectionId?: number // The current board section ID if viewing a board section
  inProject?: boolean     // Whether viewing a project
  projectId?: number      // The current project ID if viewing a project
}

// Singleton state for the context menu
const state = ref<MediaContextMenuState>({
  visible: false,
  x: 0,
  y: 0
})

export function useMediaContextMenu() {
  /**
   * Show the context menu for a media item.
   * Only requires mediaId - the menu component fetches additional info (isVideo, etc.)
   */
  function show(options: {
    event: MouseEvent
    mediaId?: number
    assetId?: number
    fileHash?: string
    mediaIds?: number[]
    assetIds?: number[]
    selectedItems?: any[]
    inBoard?: boolean
    boardSectionId?: number
    inProject?: boolean
    projectId?: number
  }) {
    const { event, mediaId, assetId, fileHash, mediaIds, assetIds, selectedItems, inBoard, boardSectionId, inProject, projectId } = options

    // Prevent default browser context menu
    event.preventDefault()
    event.stopPropagation()

    // Store raw click coordinates - the component measures actual size and adjusts
    let x = event.clientX
    let y = event.clientY

    state.value = {
      visible: true,
      x,
      y,
      mediaId,
      assetId,
      fileHash,
      mediaIds: mediaIds || (mediaId ? [mediaId] : []),
      assetIds: assetIds || (assetId ? [assetId] : []),
      selectedItems: selectedItems || [],
      inBoard: inBoard || false,
      boardSectionId,
      inProject: inProject || false,
      projectId
    }
  }

  function hide() {
    state.value = {
      ...state.value,
      visible: false
    }
  }

  /**
   * Show the context menu at specific coordinates (programmatic trigger).
   * Used by the action bar's [...] button to show context menu above it.
   *
   * When bottomY is provided, the menu's bottom edge will be anchored to that
   * y-coordinate instead of positioning from the top.
   */
  function showAt(options: {
    x: number
    y?: number
    bottomY?: number
    mediaId?: number
    assetId?: number
    fileHash?: string
    mediaIds?: number[]
    assetIds?: number[]
    selectedItems?: any[]
    inBoard?: boolean
    boardSectionId?: number
    inProject?: boolean
    projectId?: number
  }) {
    const { x, y, bottomY, mediaId, assetId, fileHash, mediaIds, assetIds, selectedItems, inBoard, boardSectionId, inProject, projectId } = options

    state.value = {
      visible: true,
      x,
      y: y || 0,
      bottomY,
      mediaId,
      assetId,
      fileHash,
      mediaIds: mediaIds || (mediaId ? [mediaId] : []),
      assetIds: assetIds || (assetId ? [assetId] : []),
      selectedItems: selectedItems || [],
      inBoard: inBoard || false,
      boardSectionId,
      inProject: inProject || false,
      projectId
    }
  }

  function toggle(options: Parameters<typeof show>[0]) {
    if (state.value.visible && state.value.mediaId === options.mediaId) {
      hide()
    } else {
      show(options)
    }
  }

  return {
    state: readonly(state),
    show,
    showAt,
    hide,
    toggle
  }
}
