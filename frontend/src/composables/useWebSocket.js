import { ref, shallowRef } from 'vue'
import {
  mobileRecoveryEnabled,
  mobileTransportAdmitsSocket,
  mobileTransportEpoch,
  onMobileTransportAdmit,
  onMobileTransportReady,
  setMobileSocketReady,
} from './useMobileRecovery.js'
import { getCurrentProfileId } from './useProfile'
import { getWsBase, isInitialized as isApiInitialized } from '../apiConfig'
import { addToast, removeToast } from './useToasts'
import { createReconnectBackoff, LOCAL_RECONNECT, REMOTE_RECONNECT } from '../utils/reconnectBackoff.js'
import { realtimeScope } from './realtimeScope.js'
import { installRealtimeScope } from './useRealtimeTopic.js'

/**
 * Singleton WebSocket connection shared across all components
 * Handles connection, reconnection, and event broadcasting
 *
 * Reconnection: a local backend is retried every half second so the app
 * follows a restart at once. A remote server (phone shells, a desktop
 * pointed at another device, or a browser on another machine) backs off exponentially with jitter up to 30 s,
 * resetting after a stable connection, and retries at once when the network
 * comes back or the phone's native recovery reports the path ready. On the
 * phone shells no socket is attempted while native recovery says the path is
 * unusable; its ready signal opens the socket exactly once per recovery.
 *
 * Every open emits `websocket_reconnected` with `{ generation }` (first
 * connect included: the frontend may mount before the backend is ready).
 * Handlers that return a promise are the active screen's reads; handlers
 * registered with `{ optional: true }` (catalogs, status polls, artwork
 * retries) run after those settle on a remote connection, so a constrained
 * link spends itself on what is visible first.
 */

// Shared state (singleton) - exists outside the composable function
// Shallow: handlers compare the live socket by identity, which a reactive proxy would break.
const ws = shallowRef(null)
const connected = ref(false)
const reconnecting = ref(false)
const reconnectAttempts = ref(0)
const eventHandlers = new Map() // Map of event type -> array of handlers
const OPTIONAL_SUFFIX = ':optional'
/** Optional reconnect work waits for the active screen's reads, but never longer than this. */
const OPTIONAL_DEFER_MAX_MS = 3000
/** A remote socket silent for this long is asked to prove it is alive. */
const LIVENESS_IDLE_MS = 25_000
/** How long a remote upgrade may take before the attempt is abandoned. */
const CONNECT_TIMEOUT_MS = 10_000
/** How long a liveness ping may go unanswered before the socket is treated as dead (half-open). */
const LIVENESS_TIMEOUT_MS = 10_000

let reconnectTimeout = null
let isInitialized = false
let remoteServer = false
const backoff = createReconnectBackoff()
let reconnectGeneration = 0
let optionalTimer = null
let optionalToken = 0
let lastMessageAt = 0
let livenessTimer = null
let livenessDeadline = null

// Whether the socket's own address is another machine (a browser on a
// headless server, say). Loopback backends keep the quick local retry.
let remoteAddress = false
const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', '::1'])

export function isLoopbackSocketUrl(url) {
  try { return LOOPBACK_HOSTS.has(new URL(url).hostname) } catch { return false }
}

function isRemote() {
  return mobileRecoveryEnabled || remoteServer || remoteAddress
}

/** The desktop app reports whether its active server is another device. */
export function setRemoteServerConnection(remote) {
  remoteServer = Boolean(remote)
}

function isLive(socket) {
  return socket?.readyState === WebSocket.OPEN || socket?.readyState === WebSocket.CONNECTING
}

function clearReconnectTimer() {
  if (reconnectTimeout) {
    clearTimeout(reconnectTimeout)
    reconnectTimeout = null
  }
}

let connectWatchdog = null

function stopConnectWatchdog() {
  if (connectWatchdog) { clearTimeout(connectWatchdog); connectWatchdog = null }
}

function stopLiveness() {
  if (livenessTimer) { clearInterval(livenessTimer); livenessTimer = null }
  if (livenessDeadline) { clearTimeout(livenessDeadline); livenessDeadline = null }
}

export function useWebSocket() {

  /**
   * Connect to WebSocket server
   */
  function connect() {
    if (isLive(ws.value)) {
      return
    }

    // Wait for API config to be initialized (for Tauri port discovery)
    if (!isApiInitialized()) {
      console.log('[WebSocket] Waiting for API config initialization...')
      setTimeout(connect, 100)
      return
    }

    // The phone's native recovery owns the path; its ready signal connects.
    if (!mobileTransportAdmitsSocket()) {
      clearReconnectTimer()
      reconnecting.value = true
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
      // Declare the realtime capability and restore this window's scope
      // (profile, followed topics, preview policy) atomically with the
      // connection. Older servers ignore the query and send everything.
      wsUrl += (wsUrl.includes('?') ? '&' : '?') + realtimeScope.connectQuery(getCurrentProfileId())

      remoteAddress = !isLoopbackSocketUrl(wsUrl)
      console.log('[WebSocket] Connecting to:', wsUrl.split('?')[0])
      const socket = new WebSocket(wsUrl)
      socket.stimmaEpoch = mobileTransportEpoch()
      // A remote upgrade that neither opens nor fails (a half-open path) must not hold the slot forever.
      stopConnectWatchdog()
      if (isRemote()) {
        connectWatchdog = setTimeout(() => {
          connectWatchdog = null
          if (ws.value === socket && socket.readyState === WebSocket.CONNECTING) {
            console.warn('[WebSocket] Upgrade did not complete; retrying')
            abandon(socket)
          }
        }, CONNECT_TIMEOUT_MS)
      }
      ws.value = socket

      socket.onopen = () => {
        console.log('[WebSocket] Connected')
        stopConnectWatchdog()
        connected.value = true
        setMobileSocketReady(true)
        reconnecting.value = false
        reconnectAttempts.value = 0
        backoff.opened()
        lastMessageAt = Date.now()
        startLiveness(socket)

        // Clear any pending reconnect timeout
        clearReconnectTimer()

        realtimeScope.socketOpened(send)

        // Notify listeners so they can refresh state - on both first connect and reconnect.
        // On first launch the frontend may mount before the backend is ready, causing initial
        // data fetches to fail. Firing this on every connect ensures state gets populated.
        dispatchReconnect()
      }

      socket.onmessage = (event) => {
        lastMessageAt = Date.now()
        if (livenessDeadline) { clearTimeout(livenessDeadline); livenessDeadline = null }
        try {
          const message = JSON.parse(event.data)
          realtimeScope.handleServerMessage(message?.event, message?.data)
          handleMessage(message)
        } catch (error) {
          console.error('[WebSocket] Failed to parse message', {
            errorType: error?.name || 'Error',
            payloadChars: typeof event.data === 'string' ? event.data.length : null
          })
        }
      }

      socket.onerror = (error) => {
        console.error('[WebSocket] Error:', error)
      }

      socket.onclose = () => {
        console.log('[WebSocket] Disconnected')
        lost(socket)
      }
    } catch (error) {
      console.error('[WebSocket] Connection failed:', error)
      scheduleReconnect()
    }
  }

  /** A socket ended, by close event or because it stopped answering. */
  function lost(socket) {
    if (ws.value !== socket) return
    stopConnectWatchdog()
    backoff.closed()
    stopLiveness()
    connected.value = false
    setMobileSocketReady(false)
    ws.value = null
    realtimeScope.socketClosed()

    // Lost contact does not imply that remote jobs have stopped.
    handleMessage({ event: 'websocket_disconnected', data: {} })

    scheduleReconnect()
  }

  /**
   * Schedule the next attempt: quick for a local backend, backing off for a
   * remote server, and not at all while native recovery holds the path.
   */
  function scheduleReconnect() {
    if (reconnectTimeout) {
      return // Already scheduled
    }

    reconnecting.value = true
    reconnectAttempts.value++
    if (!mobileTransportAdmitsSocket()) return

    const delay = backoff.next(isRemote() ? REMOTE_RECONNECT : LOCAL_RECONNECT)
    console.log(`[WebSocket] Reconnecting in ${delay}ms (attempt ${reconnectAttempts.value})`)

    reconnectTimeout = setTimeout(() => {
      reconnectTimeout = null
      connect()
    }, delay)
  }

  /** The network or app came back: skip any remaining backoff. */
  function wake() {
    if (isLive(ws.value)) return
    clearReconnectTimer()
    backoff.reset()
    connect()
  }

  /**
   * A remote socket can stay OPEN with nothing behind it (a dropped NAT
   * mapping, a server that vanished without closing). When it has been
   * silent for a while, ping; no answer means it is dead.
   */
  function startLiveness(socket) {
    stopLiveness()
    if (!isRemote()) return
    livenessTimer = setInterval(() => {
      if (ws.value !== socket || socket.readyState !== WebSocket.OPEN || livenessDeadline) return
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
      if (Date.now() - lastMessageAt < LIVENESS_IDLE_MS) return
      send('ping', {})
      livenessDeadline = setTimeout(() => {
        livenessDeadline = null
        if (ws.value !== socket) return
        console.warn('[WebSocket] No answer to liveness ping; replacing the socket')
        abandon(socket)
      }, LIVENESS_TIMEOUT_MS)
    }, LIVENESS_IDLE_MS / 5)
  }

  /** Drop a dead socket without waiting for a close handshake that will never complete. */
  function abandon(socket) {
    socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null
    try { socket.close() } catch { /* Already gone. */ }
    lost(socket)
  }

  /**
   * Disconnect from WebSocket server
   */
  function disconnect() {
    clearReconnectTimer()
    stopConnectWatchdog()
    stopLiveness()

    if (ws.value) {
      const previous = ws.value
      ws.value = null
      // An intentional replacement must not let a delayed close event clear
      // the new socket or schedule a second reconnect after iOS resumes.
      previous.onopen = previous.onmessage = previous.onerror = previous.onclose = null
      previous.close()
    }
    realtimeScope.socketClosed()

    connected.value = false
    setMobileSocketReady(false)
    reconnecting.value = false
  }

  /**
   * One refresh sequence per open: the active screen first, optional work
   * after its reads settle (remote only), and nothing from a superseded open.
   */
  function dispatchReconnect(extra = {}) {
    const generation = ++reconnectGeneration
    const data = { ...extra, generation }
    const results = handleMessage({ event: 'websocket_reconnected', data })
    const token = ++optionalToken
    if (optionalTimer) { clearTimeout(optionalTimer); optionalTimer = null }
    const runOptional = () => {
      if (token !== optionalToken) return
      optionalToken++
      if (optionalTimer) { clearTimeout(optionalTimer); optionalTimer = null }
      handleMessage({ event: `websocket_reconnected${OPTIONAL_SUFFIX}`, data })
      window.dispatchEvent(new Event('stimma:media-reconnected'))
    }
    const reads = results.filter(result => typeof result?.then === 'function')
    if (!isRemote() || reads.length === 0) { runOptional(); return }
    optionalTimer = setTimeout(runOptional, OPTIONAL_DEFER_MAX_MS)
    Promise.allSettled(reads).then(runOptional)
  }

  /**
   * Handle incoming WebSocket message
   */
  function handleMessage(message) {
    const { event, data } = message

    if (!event) {
      console.warn('[WebSocket] Received message without event type', {
        dataKeys: data && typeof data === 'object' ? Object.keys(data) : []
      })
      return []
    }

    // Filter by profile_id if present - this prevents cross-profile event pollution
    // Events from a different profile should be ignored (e.g., chat_id=1 in profile A
    // vs chat_id=1 in profile B are different chats in different databases)
    if (data && data.profile_id) {
      const currentProfile = getCurrentProfileId()
      if (data.profile_id !== currentProfile) {
        // Ignore events from other profiles
        console.debug(`[WebSocket] Dropping ${event} - profile mismatch (${data.profile_id} !== ${currentProfile})`)
        return []
      }
    }

    // Call all registered handlers for this event type
    const handlers = eventHandlers.get(event) || []

    // Log generation job events for debugging
    if (event.startsWith('generation_job_')) {
      console.log(`[WebSocket] ${event}: ${handlers.length} handler(s), job_id=${data?.job?.id}, generator_instance_id=${data?.generator_instance_id}`)
    }

    return [...handlers].map(handler => {
      try {
        const result = handler(data)
        // A failed refresh keeps what is already shown; it must not surface as an unhandled rejection.
        if (typeof result?.then === 'function') return result.catch(error => console.error(`[WebSocket] Handler for '${event}' failed:`, error))
        return result
      } catch (error) {
        console.error(`[WebSocket] Error in handler for event '${event}':`, error)
        return undefined
      }
    })
  }

  /**
   * Subscribe to a specific event type
   * @param {string} event - Event type to listen for
   * @param {function} handler - Callback function to handle the event
   * @param {{ optional?: boolean }} [options] - For `websocket_reconnected`:
   *   optional work runs after the active screen's reads on a remote connection.
   * @returns {function} Unsubscribe function
   */
  function on(event, handler, options = {}) {
    const key = options.optional && event === 'websocket_reconnected' ? `${event}${OPTIONAL_SUFFIX}` : event
    if (!eventHandlers.has(key)) {
      eventHandlers.set(key, [])
    }

    eventHandlers.get(key).push(handler)

    // Return unsubscribe function
    return () => {
      const handlers = eventHandlers.get(key)
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
    for (const key of [event, `${event}${OPTIONAL_SUFFIX}`]) {
      const handlers = eventHandlers.get(key)
      if (handlers) {
        const index = handlers.indexOf(handler)
        if (index > -1) {
          handlers.splice(index, 1)
        }
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
    installRealtimeScope()
    // Once the server filters for a newly selected profile, reconcile what
    // was read for it while the old profile's filter was still in force,
    // through the same ordered refresh as a reconnect (screen first, then
    // optional work).
    realtimeScope.onProfileConfirmed(() => dispatchReconnect({ reason: 'profile_scope' }))
    connect()
    console.log('[WebSocket] Singleton instance initialized')

    // Native recovery finished: replace a socket from before the disruption
    // (WebKit can report a suspended socket as OPEN) or open one now.
    // onopen performs the normal data resynchronization.
    stopTransportReady = onMobileTransportReady(epoch => {
      backoff.reset()
      const socket = ws.value
      // A socket opened during this recovery's check (open or still opening) is already the replacement.
      if (isLive(socket) && socket.stimmaEpoch >= epoch) return
      const wasConnected = connected.value
      disconnect()
      // The replaced socket may have missed events; consumers treat this like any gap.
      if (wasConnected) handleMessage({ event: 'websocket_disconnected', data: {} })
      connect()
    })
    // Off the phone shells there is no recovery machine; a transport-resumed
    // event (an embedding shell resuming its transport) still replaces the socket.
    if (!mobileRecoveryEnabled && typeof window !== 'undefined') {
      window.addEventListener('stimma:transport-resumed', replaceAfterResume)
    }
    // Admitted again without a recovery to announce (e.g. an older shell's
    // connection state): reconnect a dropped socket, keep a live one.
    stopTransportAdmit = onMobileTransportAdmit(() => { if (!isLive(ws.value) && !reconnectTimeout) connect() })
    if (typeof window !== 'undefined') {
      window.addEventListener('online', wake)
      // A desktop browser or laptop waking from sleep; the phone shells use native recovery.
      if (!mobileRecoveryEnabled && typeof document !== 'undefined') {
        document.addEventListener('visibilitychange', onVisible)
      }
      window.addEventListener('profile-will-change', cancelOptional)
    }

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
              const { desktop } = await import('../desktop')
              await desktop.openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders')
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
    send,
    wake,
    /** The socket was replaced without a close event: events from the gap may be missing. */
    notifyGap: () => handleMessage({ event: 'websocket_disconnected', data: {} }),
  }
}

let stopTransportReady = () => {}

function replaceAfterResume() {
  const socket = useWebSocket()
  const wasConnected = socket.connected.value
  socket.disconnect()
  if (wasConnected) socket.notifyGap()
  socket.wake()
}
let stopTransportAdmit = () => {}

function onVisible() {
  if (document.visibilityState === 'visible') useWebSocket().wake()
}

function wake() {
  useWebSocket().wake()
}

/** Optional reconnect work for the previous profile is obsolete. */
function cancelOptional() {
  optionalToken++
  if (optionalTimer) { clearTimeout(optionalTimer); optionalTimer = null }
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
    stopTransportReady()
    window.removeEventListener('stimma:transport-resumed', replaceAfterResume)
    stopTransportAdmit()
    window.removeEventListener('online', wake)
    document.removeEventListener('visibilitychange', onVisible)
    window.removeEventListener('profile-will-change', cancelOptional)
    // Save handlers for the next module version
    data.eventHandlers = eventHandlers

    // Close WebSocket but don't clear handlers - they'll be restored
    if (ws.value) {
      ws.value.close()
    }
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout)
    }
    stopLiveness()
    isInitialized = false
  })
}
