/**
 * Composable for handling file drag-out in Tauri.
 *
 * In Tauri, native file drag-out requires using the drag plugin
 * with actual file system paths.
 */

import { ref } from 'vue'
import { useMediaApi } from './useMediaApi'
import { getApiBase, isTauri as checkIsTauri, initApiConfig } from '../apiConfig'
import { getCurrentDbGuid } from './useProfile'

// Module-level state
const isTauri = ref(false)
let tauriInvoke: any = null
let TauriChannel: any = null
let initPromise: Promise<void> | null = null
let initComplete = false

/**
 * Initialize Tauri detection and load drag plugin.
 * Uses the same detection method as apiConfig.js for reliability.
 */
async function initTauri(): Promise<void> {
  if (initComplete) return
  if (initPromise) return initPromise

  initPromise = (async () => {
    try {
      // Wait for API config to be ready first (this ensures Tauri IPC is available)
      await initApiConfig()

      // Use the reliable sync check from apiConfig
      if (!checkIsTauri()) {
        console.log('[useTauriDrag] Not in Tauri environment')
        isTauri.value = false
        initComplete = true
        return
      }

      // We're in Tauri - load the APIs
      const { invoke, Channel } = await import('@tauri-apps/api/core')
      tauriInvoke = invoke
      TauriChannel = Channel
      isTauri.value = true
      console.log('[useTauriDrag] Tauri drag initialized successfully')
    } catch (e) {
      console.log('[useTauriDrag] Tauri init failed:', e)
      isTauri.value = false
    } finally {
      initComplete = true
    }
  })()

  return initPromise
}

/**
 * Fetch thumbnail path from backend for drag preview
 */
async function getThumbnailPath(mediaId: number): Promise<string | null> {
  try {
    const dbGuid = getCurrentDbGuid()
    if (!dbGuid) return null

    const response = await fetch(`${getApiBase()}/db/${dbGuid}/media/${mediaId}/thumbnail-path?size=128`)
    if (!response.ok) return null

    const data = await response.json()
    return data.path || null
  } catch (e) {
    console.error('[useTauriDrag] Failed to get thumbnail path:', e)
    return null
  }
}

/**
 * Start a native drag operation with file paths
 */
async function startNativeDrag(items: string[], previewPath?: string): Promise<void> {
  if (!tauriInvoke || !TauriChannel) {
    throw new Error('Tauri not initialized')
  }

  console.log('[useTauriDrag] Starting drag with items:', items, 'preview:', previewPath)
  const onEventChannel = new TauriChannel()
  onEventChannel.onmessage = (event: any) => {
    console.log('[useTauriDrag] Drag event:', event)
  }

  await tauriInvoke('plugin:drag|start_drag', {
    item: items,
    image: previewPath || items[0],
    onEvent: onEventChannel,
  })
}

// Initialize on module load (non-blocking)
initTauri()

// Cache for media file paths (mediaId -> file_path)
const filePathCache = new Map<number, string>()

// Cache for resolved drag-preview thumbnail paths (mediaId -> fs path).
// Populated lazily in the background so the native drag itself never has to
// wait on a thumbnail fetch (see handleDragStart).
const thumbnailPathCache = new Map<number, string>()

// Cache for drag-out snapshot paths (mediaId -> fs path of a copy with
// A1111/Stimma metadata embedded). Backend produces these on demand and
// caches them on disk keyed by file_hash + metadata_hash; we additionally
// cache the resolved path client-side to skip the round-trip on repeat drags.
const snapshotPathCache = new Map<number, string>()

/**
 * Resolve (and cache) the filesystem path to a metadata-embedded snapshot
 * for a given media item.
 *
 * Pipeline (hybrid): backend prepares the A1111 string + Stimma JSON (and,
 * for JPEG, the EXIF block via piexif.dump). The Rust `embed_metadata`
 * command then splices those into the source file at byte level (no pixel
 * decode/re-encode). Returns null on any failure — caller falls back to the
 * original file path.
 */
async function getExportableSnapshotPath(mediaId: number): Promise<string | null> {
  if (snapshotPathCache.has(mediaId)) return snapshotPathCache.get(mediaId)!
  if (!tauriInvoke) return null
  try {
    const dbGuid = getCurrentDbGuid()
    if (!dbGuid) return null
    const response = await fetch(
      `${getApiBase()}/db/${dbGuid}/media/${mediaId}/exportable-snapshot`,
      { method: 'POST' }
    )
    if (!response.ok) return null
    const payload = await response.json()
    if (!payload?.source_path) return null
    if (payload.format === 'passthrough') {
      // Nothing to embed — drag the original.
      snapshotPathCache.set(mediaId, payload.source_path)
      return payload.source_path
    }
    const path = await tauriInvoke('embed_metadata', { req: payload })
    if (typeof path === 'string' && path.length > 0) {
      snapshotPathCache.set(mediaId, path)
      return path
    }
  } catch (e) {
    console.error('[useTauriDrag] Failed to resolve exportable snapshot:', e)
  }
  return null
}

export function useTauriDrag() {
  const { getMediaItem } = useMediaApi()

  /**
   * Get the file path for a media item (with caching)
   */
  async function getFilePath(mediaId: number): Promise<string | null> {
    // Check cache first
    if (filePathCache.has(mediaId)) {
      return filePathCache.get(mediaId)!
    }

    try {
      const media = await getMediaItem(mediaId)
      if (media?.file_path) {
        filePathCache.set(mediaId, media.file_path)
        return media.file_path
      }
    } catch (e) {
      console.error('[useTauriDrag] Failed to get media item:', e)
    }
    return null
  }

  /**
   * Handle drag start for a media item.
   * In Tauri, this will initiate a native file drag.
   * In browser, it falls back to setting data transfer.
   *
   * @param event - The drag event
   * @param mediaId - The media ID to drag
   * @param filePath - Optional pre-fetched file path (avoids async lookup)
   */
  async function handleDragStart(
    event: DragEvent,
    mediaId: number,
    filePath?: string
  ): Promise<void> {
    // Ensure Tauri is initialized before checking
    await initTauri()

    // If in Tauri with file path available, use native file drag exclusively
    // This must happen synchronously before any await to properly prevent browser drag
    console.log('[useTauriDrag] handleDragStart called:', { isTauri: isTauri.value, hasTauriInvoke: !!tauriInvoke, filePath })
    if (isTauri.value && tauriInvoke && filePath) {
      // Prevent browser drag immediately (must be sync)
      event.preventDefault()

      // Start the native drag synchronously within this gesture. The macOS
      // drag plugin ends up in -beginDraggingSessionWithItems:event:source:,
      // which AppKit only permits from inside the originating mouse event. If
      // we first await a network/IPC round-trip (the snapshot embed), the
      // mouse gesture is over by the time we call it and AppKit aborts with an
      // uncaught NSInternalInconsistencyException — a hard native crash (the
      // macOS "app quit unexpectedly" reporter). So we drag whatever path is
      // ready *right now* and never await before start_drag.
      //
      // To still ship the metadata-embedded snapshot (A1111 + Stimma chunks),
      // it's resolved ahead of time: prewarmDragSnapshot() populates the cache
      // when the item is displayed, so by drag time the cached snapshot is
      // usually already here. Cold misses fall back to the raw file (drag still
      // works; it just lacks embedded metadata until the warm completes).
      const cachedPreview = thumbnailPathCache.get(mediaId)
      const cachedSnapshot = snapshotPathCache.get(mediaId)
      const dragPath = cachedSnapshot || filePath

      startNativeDrag([dragPath], cachedPreview).catch((e) => {
        console.error('[useTauriDrag] Native drag failed:', e)
      })

      // Warm the embedded snapshot + tidy small-thumbnail preview in the
      // background so the next drag of this item carries metadata and shows
      // the compact chip instead of the full file.
      if (!cachedSnapshot) {
        getExportableSnapshotPath(mediaId).catch(() => {})
      }
      if (!cachedPreview) {
        getThumbnailPath(mediaId)
          .then((p) => { if (p) thumbnailPathCache.set(mediaId, p) })
          .catch(() => {})
      }
      return
    }
    console.log('[useTauriDrag] Falling back to browser drag')

    // If in Tauri but no file path, try to get it (async - browser drag may start)
    if (isTauri.value && tauriInvoke && !filePath) {
      // Set internal data for in-app drag-drop as fallback
      event.dataTransfer?.setData('application/x-media-id', String(mediaId))
      if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'copy'
      }

      try {
        const path = await getFilePath(mediaId)
        if (path) {
          // Can't preventDefault after async - native drag won't work perfectly
          // but at least in-app drag works via dataTransfer
          console.log('[useTauriDrag] File path retrieved async, native drag may not work')
        }
      } catch (e) {
        console.error('[useTauriDrag] Failed to get file path:', e)
      }
      return
    }

    // Browser mode - use dataTransfer for in-app drag-drop
    event.dataTransfer?.setData('application/x-media-id', String(mediaId))
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'copy'
    }
  }

  /**
   * Handle drag start for multiple media items.
   */
  async function handleMultiDragStart(
    event: DragEvent,
    mediaIds: number[],
    filePaths?: string[]
  ): Promise<void> {
    // Ensure Tauri is initialized before checking
    await initTauri()

    // If in Tauri with file paths available, use native file drag exclusively
    if (isTauri.value && tauriInvoke && filePaths && filePaths.length > 0) {
      // Prevent browser drag immediately (must be sync)
      event.preventDefault()

      // Same constraint as handleDragStart: the native drag must begin
      // synchronously within this gesture, so we never await snapshot embedding
      // or thumbnail fetches before start_drag (doing so ends the mouse gesture
      // and crashes the macOS drag plugin). Use whatever snapshots are already
      // cached, falling back to the raw file path per item.
      const resolvedPaths = mediaIds.map((id, i) => snapshotPathCache.get(id) || filePaths[i])
      const cachedPreview = thumbnailPathCache.get(mediaIds[0])

      startNativeDrag(resolvedPaths, cachedPreview).catch((e) => {
        console.error('[useTauriDrag] Multi-file native drag failed:', e)
      })

      // Warm embedded snapshots + preview in the background for next time.
      mediaIds.forEach((id) => {
        if (!snapshotPathCache.has(id)) getExportableSnapshotPath(id).catch(() => {})
      })
      if (!cachedPreview) {
        getThumbnailPath(mediaIds[0])
          .then((p) => { if (p) thumbnailPathCache.set(mediaIds[0], p) })
          .catch(() => {})
      }
      return
    }

    // Browser mode or Tauri without pre-fetched paths - use dataTransfer
    event.dataTransfer?.setData('application/x-media-ids', JSON.stringify(mediaIds))
    if (event.dataTransfer) {
      event.dataTransfer.effectAllowed = 'copy'
    }

    // In Tauri without paths, try to get them async (browser drag already started)
    if (isTauri.value && tauriInvoke && !filePaths) {
      try {
        const pathPromises = mediaIds.map(id => getFilePath(id))
        const results = await Promise.all(pathPromises)
        const paths = results.filter((p): p is string => p !== null)
        if (paths.length > 0) {
          console.log('[useTauriDrag] Paths retrieved async, native drag may not work')
        }
      } catch (e) {
        console.error('[useTauriDrag] Failed to get file paths:', e)
      }
    }
  }

  /**
   * Pre-cache a file path for faster drag initiation
   */
  function cacheFilePath(mediaId: number, filePath: string) {
    filePathCache.set(mediaId, filePath)
  }

  /**
   * Resolve the metadata-embedded snapshot (and compact drag preview) for an
   * item ahead of any drag, so the actual dragstart can start the native drag
   * synchronously from cache without awaiting a round-trip (which crashes the
   * macOS drag plugin — see handleDragStart). Call this when an item becomes
   * the likely drag target, e.g. when shown in the slideshow. No-op outside
   * Tauri and safe to call repeatedly (cached after the first resolve).
   */
  async function prewarmDragSnapshot(mediaId: number): Promise<void> {
    await initTauri()
    if (!isTauri.value || !tauriInvoke) return
    if (!snapshotPathCache.has(mediaId)) {
      getExportableSnapshotPath(mediaId).catch(() => {})
    }
    if (!thumbnailPathCache.has(mediaId)) {
      getThumbnailPath(mediaId)
        .then((p) => { if (p) thumbnailPathCache.set(mediaId, p) })
        .catch(() => {})
    }
  }

  return {
    isTauri,
    handleDragStart,
    handleMultiDragStart,
    cacheFilePath,
    getFilePath,
    prewarmDragSnapshot
  }
}
