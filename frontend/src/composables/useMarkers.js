import { reportActionError } from './useToasts'
import { ref, computed } from 'vue'
import { useMediaApi } from './useMediaApi'
import { useWebSocket } from './useWebSocket'

// Shared singleton state for markers
const availableMarkers = ref([])
const mediaMarkers = ref({}) // { [mediaId]: Marker[] }
const isInitialized = ref(false)
const isInitializing = ref(false)

// WebSocket unsubscribers (registered per init)
let wsUnsubscribers = []

// Bumped on a profile switch; reads begun before it are for the old profile.
let generation = 0
// The generation whose catalog was read; behind `generation` until a read lands
// (a PIN-locked profile's read fails until unlock, and init reads again).
let catalogGeneration = -1
let readMarkerCatalog = null

async function refreshAvailableMarkers() {
  const readFor = generation
  const markers = await readMarkerCatalog()
  if (readFor !== generation) return
  availableMarkers.value = markers
  catalogGeneration = readFor
}

if (typeof window !== 'undefined') {
  window.addEventListener('profile-changed', () => {
    generation++
    mediaMarkers.value = {}
    availableMarkers.value = []
    if (readMarkerCatalog && (isInitialized.value || isInitializing.value)) {
      refreshAvailableMarkers().catch(err => console.error('Failed to load markers:', err))
    }
  })
}

// Note: markers_updated WebSocket handler in useWebSocket.js dispatches 'markers-changed'
// browser events which we listen for in init() to refresh availableMarkers

/**
 * Composable for managing markers on media items.
 * Uses shared singleton state so all components see the same marker data.
 * Subscribes to WebSocket events for real-time updates.
 */
export function useMarkers() {
  const { getMarkers, addMarkerToMedia, removeMarkerFromMedia } = useMediaApi()
  const { on: onWebSocketEvent } = useWebSocket()
  readMarkerCatalog ??= getMarkers

  // Initialize markers system (called once, shared across all uses)
  async function init() {
    if (isInitialized.value && !isInitializing.value && catalogGeneration !== generation) {
      isInitializing.value = true
      try {
        await refreshAvailableMarkers()
      } catch (err) {
        console.error('Failed to load markers:', err)
      } finally {
        isInitializing.value = false
      }
      return
    }
    if (isInitialized.value || isInitializing.value) return
    isInitializing.value = true

    try {
      // Load available markers
      await refreshAvailableMarkers()

      // Subscribe to WebSocket events for real-time marker changes
      if (wsUnsubscribers.length === 0) {
        // Individual media marker updates
        wsUnsubscribers.push(onWebSocketEvent('media_updated', (data) => {
          const { media_id, fields, media } = data
          if (!media_id || !media) return

          // Update markers if that's what changed
          if (fields.includes('markers')) {
            mediaMarkers.value = {
              ...mediaMarkers.value,
              [media_id]: media.markers || []
            }
          }
        }))

        // Bulk auto-marker sync (from folder settings change)
        // Clear cache and notify views to refresh visible markers
        wsUnsubscribers.push(onWebSocketEvent('auto_markers_synced', (data) => {
          console.log('[useMarkers] Auto-markers synced, clearing cache', data)
          mediaMarkers.value = {}
          // Dispatch event so views can reload markers for visible items
          window.dispatchEvent(new CustomEvent('auto-markers-synced'))
        }))
      }

      // Listen for marker definition changes (icon, color, name edits)
      window.addEventListener('markers-changed', () => {
        refreshAvailableMarkers().catch(err => console.error('Failed to load markers:', err))
      })

      isInitialized.value = true
    } catch (err) {
      console.error('Failed to initialize markers:', err)
    } finally {
      isInitializing.value = false
    }
  }

  // Load markers for specific media IDs (batch)
  async function loadMarkersForMedia(mediaIds) {
    if (!mediaIds || mediaIds.length === 0) return

    // Filter out media IDs we already have markers for
    const missingIds = mediaIds.filter(id => !(id in mediaMarkers.value))
    if (missingIds.length === 0) return

    const readFor = generation
    try {
      const response = await fetch('/api/media/markers/batch-get', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(missingIds)
      })
      if (response.ok) {
        const markersByMedia = await response.json()
        if (readFor !== generation) return
        mediaMarkers.value = {
          ...mediaMarkers.value,
          ...markersByMedia
        }
      }
    } catch (err) {
      console.error('Failed to load markers for media:', err)
    }
  }

  // Get markers for a specific media item (reactive)
  function getMarkersForMedia(mediaId) {
    return computed(() => mediaMarkers.value[mediaId] || [])
  }

  // Check if media has a specific marker
  function hasMarker(mediaId, markerId) {
    const markers = mediaMarkers.value[mediaId] || []
    return markers.some(m => m.id === markerId)
  }

  // Toggle a marker on a media item
  async function toggleMarker(mediaId, marker) {
    const has = hasMarker(mediaId, marker.id)
    const currentMarkers = mediaMarkers.value[mediaId] || []
    const madeFor = generation

    try {
      if (has) {
        await removeMarkerFromMedia(mediaId, marker.id)
        if (madeFor !== generation) return
        mediaMarkers.value = {
          ...mediaMarkers.value,
          [mediaId]: currentMarkers.filter(m => m.id !== marker.id)
        }
      } else {
        await addMarkerToMedia(mediaId, marker.id)
        if (madeFor !== generation) return
        mediaMarkers.value = {
          ...mediaMarkers.value,
          [mediaId]: [...currentMarkers, marker]
        }
      }
    } catch (err) {
      reportActionError("Couldn't update marker.", err)
    }
  }

  // Set markers for a media item (used when loading from API response)
  function setMarkersForMedia(mediaId, markers) {
    mediaMarkers.value = {
      ...mediaMarkers.value,
      [mediaId]: markers || []
    }
  }

  return {
    // State (reactive)
    availableMarkers,
    mediaMarkers,
    isInitialized,

    // Methods
    init,
    loadMarkersForMedia,
    getMarkersForMedia,
    hasMarker,
    toggleMarker,
    setMarkersForMedia
  }
}
