import { ref } from 'vue'
import { getCurrentProfileId } from './useProfile'
import { getWsBase, isInitialized as isApiInitialized } from '../apiConfig'
import { addToast, removeToast } from './useToasts'

/**
 * Singleton WebSocket connection shared across all components
 * Handles connection, reconnection, and event broadcasting
 */

// Shared state (singleton) - exists outside the composable function
const ws = ref(null)
const connected = ref(false)
const reconnecting = ref(false)
const reconnectAttempts = ref(0)
const reconnectDelay = 500 // Fixed 0.5 second reconnect interval (local app, fast retry)
const eventHandlers = new Map() // Map of event type -> array of handlers

let reconnectTimeout = null
let isInitialized = false

export function useWebSocket() {

  /**
   * Connect to WebSocket server
   */
  function connect() {
    if (ws.value?.readyState === WebSocket.OPEN || ws.value?.readyState === WebSocket.CONNECTING) {
      return
    }

    // Wait for API config to be initialized (for Tauri port discovery)
    if (!isApiInitialized()) {
      console.log('[WebSocket] Waiting for API config initialization...')
      setTimeout(connect, 100)
      return
    }

    try {
      // Get WebSocket URL from apiConfig
      // In dev mode: '/ws' (uses window.location)
      // In Tauri mode: 'ws://127.0.0.1:PORT/ws'
      let wsUrl = getWsBase()
      if (wsUrl.startsWith('/')) {
        // Relative URL - convert to absolute using window.location
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        const host = window.location.host
        wsUrl = `${protocol}//${host}${wsUrl}`
      }

      console.log('[WebSocket] Connecting to:', wsUrl)
      ws.value = new WebSocket(wsUrl)

      ws.value.onopen = () => {
        console.log('[WebSocket] Connected')
        connected.value = true
        reconnecting.value = false
        reconnectAttempts.value = 0

        // Clear any pending reconnect timeout
        if (reconnectTimeout) {
          clearTimeout(reconnectTimeout)
          reconnectTimeout = null
        }

        // Notify listeners so they can refresh state - on both first connect and reconnect.
        // On first launch the frontend may mount before the backend is ready, causing initial
        // data fetches to fail. Firing this on every connect ensures state gets populated.
        handleMessage({ event: 'websocket_reconnected', data: {} })
      }

      ws.value.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data)
          handleMessage(message)
        } catch (error) {
          console.error('[WebSocket] Failed to parse message:', error, event.data)
        }
      }

      ws.value.onerror = (error) => {
        console.error('[WebSocket] Error:', error)
      }

      ws.value.onclose = () => {
        console.log('[WebSocket] Disconnected')
        connected.value = false
        ws.value = null

        // Notify listeners immediately - backend is gone, jobs are dead
        handleMessage({ event: 'websocket_disconnected', data: {} })

        // Auto-reconnect with fixed interval
        scheduleReconnect()
      }
    } catch (error) {
      console.error('[WebSocket] Connection failed:', error)
      scheduleReconnect()
    }
  }

  /**
   * Schedule reconnection with fixed interval
   */
  function scheduleReconnect() {
    if (reconnectTimeout) {
      return // Already scheduled
    }

    reconnecting.value = true
    reconnectAttempts.value++

    console.log(`[WebSocket] Reconnecting in ${reconnectDelay}ms (attempt ${reconnectAttempts.value})`)

    reconnectTimeout = setTimeout(() => {
      reconnectTimeout = null
      connect()
    }, reconnectDelay)
  }

  /**
   * Disconnect from WebSocket server
   */
  function disconnect() {
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout)
      reconnectTimeout = null
    }

    if (ws.value) {
      ws.value.close()
      ws.value = null
    }

    connected.value = false
    reconnecting.value = false
  }

  /**
   * Handle incoming WebSocket message
   */
  function handleMessage(message) {
    const { event, data } = message

    if (!event) {
      console.warn('[WebSocket] Received message without event type:', message)
      return
    }

    // Filter by profile_id if present - this prevents cross-profile event pollution
    // Events from a different profile should be ignored (e.g., chat_id=1 in profile A
    // vs chat_id=1 in profile B are different chats in different databases)
    if (data && data.profile_id) {
      const currentProfile = getCurrentProfileId()
      if (data.profile_id !== currentProfile) {
        // Ignore events from other profiles
        console.debug(`[WebSocket] Dropping ${event} - profile mismatch (${data.profile_id} !== ${currentProfile})`)
        return
      }
    }

    // Call all registered handlers for this event type
    const handlers = eventHandlers.get(event) || []

    // Log generation job events for debugging
    if (event.startsWith('generation_job_')) {
      console.log(`[WebSocket] ${event}: ${handlers.length} handler(s), job_id=${data?.job?.id}, generator_instance_id=${data?.generator_instance_id}`)
    }

    handlers.forEach(handler => {
      try {
        handler(data)
      } catch (error) {
        console.error(`[WebSocket] Error in handler for event '${event}':`, error)
      }
    })
  }

  /**
   * Subscribe to a specific event type
   * @param {string} event - Event type to listen for
   * @param {function} handler - Callback function to handle the event
   * @returns {function} Unsubscribe function
   */
  function on(event, handler) {
    if (!eventHandlers.has(event)) {
      eventHandlers.set(event, [])
    }

    eventHandlers.get(event).push(handler)

    // Return unsubscribe function
    return () => {
      const handlers = eventHandlers.get(event)
      if (handlers) {
        const index = handlers.indexOf(handler)
        if (index > -1) {
          handlers.splice(index, 1)
        }
      }
    }
  }

  /**
   * Remove an event listener
   * @param {string} event - Event type
   * @param {function} handler - Handler to remove
   */
  function off(event, handler) {
    const handlers = eventHandlers.get(event)
    if (handlers) {
      const index = handlers.indexOf(handler)
      if (index > -1) {
        handlers.splice(index, 1)
      }
    }
  }

  /**
   * Send a message to the server
   */
  function send(event, data) {
    if (!ws.value || ws.value.readyState !== WebSocket.OPEN) {
      console.warn('[WebSocket] Cannot send message, not connected')
      return false
    }

    try {
      ws.value.send(JSON.stringify({ event, data }))
      return true
    } catch (error) {
      console.error('[WebSocket] Failed to send message:', error)
      return false
    }
  }

  // Auto-connect only once (singleton pattern)
  if (!isInitialized) {
    isInitialized = true
    connect()
    console.log('[WebSocket] Singleton instance initialized')

    // Register global handler for toast notifications from backend
    on('toast_notification', (data) => {
      const { message, type = 'info', duration = 4000 } = data
      if (message) {
        addToast(message, type, duration)
      }
    })

    // Register global handler for macOS TCC file-permission denials. The
    // backend rate-limits the event; we also keep at most one toast alive.
    let macosPermToastId = null
    on('macos_permission_denied', (data) => {
      if (macosPermToastId !== null) {
        removeToast(macosPermToastId)
      }
      const where = data.folder ? `your ${data.folder} folder` : 'some of your files'
      macosPermToastId = addToast(
        `macOS is blocking Stimma's access to ${where}. In System Settings → Privacy & Security → Files & Folders, toggle Stimma's access off and on, then restart Stimma.`,
        'warning',
        0,
        {
          label: 'Open Settings',
          onClick: async () => {
            try {
              const { open } = await import('@tauri-apps/plugin-shell')
              await open('x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders')
            } catch (error) {
              console.error('[WebSocket] Failed to open System Settings:', error)
            }
          }
        }
      )
    })

    // Register global handler for markers_updated (config hot-reload)
    on('markers_updated', async () => {
      console.log('[WebSocket] Received markers_updated, dispatching markers-changed event')
      // Dispatch browser event so all components can refetch markers
      window.dispatchEvent(new CustomEvent('markers-changed'))
    })

    // Register global handler for profiles_updated (config hot-reload)
    on('profiles_updated', () => {
      console.log('[WebSocket] Received profiles_updated, dispatching profiles-changed event')
      window.dispatchEvent(new CustomEvent('profiles-changed'))
    })

    // Register global handler for tools_updated (config hot-reload)
    on('tools_updated', () => {
      console.log('[WebSocket] Received tools_updated, dispatching tools-changed event')
      window.dispatchEvent(new CustomEvent('tools-changed'))
    })
  }

  // Return the shared singleton state and methods
  return {
    connected,
    reconnecting,
    reconnectAttempts,
    connect,
    disconnect,
    on,
    off,
    send
  }
}

// HMR handling - preserve handlers across module reload
if (import.meta.hot) {
  // Restore handlers from previous module if available
  if (import.meta.hot.data?.eventHandlers) {
    import.meta.hot.data.eventHandlers.forEach((handlers, event) => {
      eventHandlers.set(event, handlers)
    })
    console.log('[WebSocket] HMR: Restored', eventHandlers.size, 'event handler groups')
  }

  import.meta.hot.dispose((data) => {
    // Save handlers for the next module version
    data.eventHandlers = eventHandlers

    // Close WebSocket but don't clear handlers - they'll be restored
    if (ws.value) {
      ws.value.close()
    }
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout)
    }
    isInitialized = false
  })
}
