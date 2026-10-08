import { ref, readonly, shallowRef, computed, watch, onMounted, onActivated, onDeactivated, onBeforeUnmount } from 'vue'

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
  projectId?: number | null // The caller's project; null = explicit top level, omitted = active project
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
    projectId?: number | null
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
    projectId?: number | null
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

// --- Hosts ------------------------------------------------------------------
//
// Several views mount <MediaContextMenu> (grids, tool views, slideshow, chat),
// and kept-alive views keep theirs mounted. The menu state is a singleton, so
// only one host may render it: the most recently mounted or activated one that
// is still active. Every other host renders nothing, so menus can't stack up in
// the document. Events from the menu (refresh, permanent-delete) go to every
// host, so each parent view still hears about changes it may need to show.

type HostEventName = 'refresh' | 'permanent-delete'

const hostStack = ref<symbol[]>([])
let hostEventSeq = 0
const hostEvent = shallowRef<{ seq: number; name: HostEventName; args: unknown[] } | null>(null)

export function useMediaContextMenuHost(onEvent: (name: HostEventName, ...args: unknown[]) => void) {
  const id = Symbol('mediaContextMenuHost')
  const claim = () => { hostStack.value = [...hostStack.value.filter(host => host !== id), id] }
  const release = () => { hostStack.value = hostStack.value.filter(host => host !== id) }
  onMounted(claim)
  onActivated(claim)
  onDeactivated(release)
  onBeforeUnmount(release)
  watch(hostEvent, (event) => { if (event) onEvent(event.name, ...event.args) })
  const isRenderer = computed(() => hostStack.value[hostStack.value.length - 1] === id)
  return { isRenderer }
}

export function broadcastMediaContextMenuEvent(name: HostEventName, ...args: unknown[]) {
  hostEvent.value = { seq: ++hostEventSeq, name, args }
}
