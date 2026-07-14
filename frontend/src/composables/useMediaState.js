import { ref } from 'vue'
import { useMediaApi } from './useMediaApi'
import { useWebSocket } from './useWebSocket'
import { getCurrentProfileId } from './useProfile'

// Shared singleton state for media state (auto_delete_at, deleted_at, file_format)
const mediaState = ref({}) // { [mediaId]: { auto_delete_at, deleted_at, file_format } }
const isInitialized = ref(false)

// WebSocket unsubscribers
let wsUnsubscribers = []

/**
 * Composable for tracking media state (auto_delete_at, deleted_at).
 * Uses shared singleton state so all components see the same data.
 * Subscribes to WebSocket events for real-time updates.
 */
export function useMediaState() {
  const { getMediaItem } = useMediaApi()
  const { on: onWebSocketEvent } = useWebSocket()

  // Initialize WebSocket subscriptions (called once, shared across all uses)
  function init() {
    if (isInitialized.value) return
    isInitialized.value = true

    // Subscribe to media_deleted event
    wsUnsubscribers.push(
      onWebSocketEvent('media_deleted', (data) => {
        const { media_id } = data
        if (!media_id) return

        // Mark as trashed
        mediaState.value = {
          ...mediaState.value,
          [media_id]: {
            ...mediaState.value[media_id],
            deleted_at: new Date().toISOString()
          }
        }
      })
    )

    // Subscribe to media_bulk_deleted event
    wsUnsubscribers.push(
      onWebSocketEvent('media_bulk_deleted', (data) => {
        const { media_ids } = data
        if (!media_ids) return

        const updates = {}
        for (const media_id of media_ids) {
          updates[media_id] = {
            ...mediaState.value[media_id],
            deleted_at: new Date().toISOString()
          }
        }
        mediaState.value = { ...mediaState.value, ...updates }
      })
    )

    // Subscribe to media_restored event
    wsUnsubscribers.push(
      onWebSocketEvent('media_restored', (data) => {
        const { media_id } = data
        if (!media_id) return

        // Clear deleted_at
        mediaState.value = {
          ...mediaState.value,
          [media_id]: {
            ...mediaState.value[media_id],
            deleted_at: null
          }
        }
      })
    )

    // Subscribe to media_updated event (could include auto_delete_at changes)
    wsUnsubscribers.push(
      onWebSocketEvent('media_updated', (data) => {
        const { media_id, media } = data
        if (!media_id || !media) return

        mediaState.value = {
          ...mediaState.value,
          [media_id]: {
            ...mediaState.value[media_id],
            auto_delete_at: media.auto_delete_at,
            deleted_at: media.deleted_at,
            asset_id: media.asset_id ?? mediaState.value[media_id]?.asset_id
          }
        }
      })
    )

    // Subscribe to auto_delete_removed event (when items are collected/tagged/marked)
    wsUnsubscribers.push(
      onWebSocketEvent('auto_delete_removed', (data) => {
        const { media_id } = data
        if (!media_id) return

        // Clear auto_delete_at
        mediaState.value = {
          ...mediaState.value,
          [media_id]: {
            ...mediaState.value[media_id],
            auto_delete_at: null
          }
        }
      })
    )

    const clearRemovedAssetDeadline = (data) => {
      const currentProfile = getCurrentProfileId()
      if (data.profile_id && data.profile_id !== currentProfile) return
      const assetIds = new Set(
        data.asset_ids || (data.asset_id ? [data.asset_id] : [])
      )
      if (!assetIds.size) return
      const updates = {}
      for (const [mediaId, state] of Object.entries(mediaState.value)) {
        if (assetIds.has(state?.asset_id)) {
          updates[mediaId] = { ...state, auto_delete_at: null }
        }
      }
      if (Object.keys(updates).length) {
        mediaState.value = { ...mediaState.value, ...updates }
      }
    }
    wsUnsubscribers.push(onWebSocketEvent('asset_deleted', clearRemovedAssetDeadline))
    wsUnsubscribers.push(onWebSocketEvent('assets_trashed', clearRemovedAssetDeadline))
    wsUnsubscribers.push(onWebSocketEvent('asset_identity_deleted', clearRemovedAssetDeadline))
  }

  // Load state for specific media IDs (batch)
  async function loadStateForMedia(mediaIds) {
    if (!mediaIds || mediaIds.length === 0) return

    // Filter out media IDs we already have state for
    const missingIds = mediaIds.filter(id => !(id in mediaState.value))
    if (missingIds.length === 0) return

    // Fetch each media item (could optimize with batch endpoint later)
    const updates = {}
    await Promise.all(
      missingIds.map(async (mediaId) => {
        try {
          const media = await getMediaItem(mediaId, { includeTrashed: true })
          updates[mediaId] = {
            auto_delete_at: media.auto_delete_at,
            deleted_at: media.deleted_at,
            file_format: media.file_format,
            asset_id: media.asset_id
          }
        } catch (error) {
          console.error(`Error fetching media state for ${mediaId}:`, error)
        }
      })
    )

    mediaState.value = { ...mediaState.value, ...updates }
  }

  // Get state for a specific media item
  function getStateForMedia(mediaId) {
    return mediaState.value[mediaId] || null
  }

  // Update state for a media item (used when loading from API response)
  function setStateForMedia(mediaId, state) {
    mediaState.value = {
      ...mediaState.value,
      [mediaId]: state
    }
  }

  return {
    // State (reactive)
    mediaState,
    isInitialized,

    // Methods
    init,
    loadStateForMedia,
    getStateForMedia,
    setStateForMedia
  }
}
