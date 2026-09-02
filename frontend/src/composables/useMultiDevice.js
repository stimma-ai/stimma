/**
 * Multi-device state for the renderer.
 *
 * The window is "on" exactly one device at a time, and that scope owns
 * everything in the window. The renderer does not talk to remote devices
 * itself — it asks main to point the proxy, and main reloads the window.
 * So this composable is thin on purpose: selection, the roster, and the
 * connection state main pushes to us.
 *
 * The roster only ever contains computers that were OFFERED (serving turned
 * on). Reading it does not require offering this one, so a laptop that never
 * serves can still drive the studio machine.
 */
import { ref, computed, readonly } from 'vue'
import { desktop, isDesktop } from '../desktop'
import { useWebSocket } from './useWebSocket'

const LOCAL_DEVICE = 'local'

// Global reactive state (shared across all components)
const activeDeviceId = ref(LOCAL_DEVICE)
const devices = ref([])
const connectionState = ref('connecting')
const initialized = ref(false)
// This install's own identity, so "This computer" carries the same
// qualifiers as every other row rather than being the one ambiguous entry.
const selfName = ref(null)
const selfChannel = ref(null)
const selfSandbox = ref(null)

let unsubscribe = null

/**
 * Up right now, per the account's push channel — not inferred from a
 * timestamp. An older backend that omits the field is assumed reachable
 * rather than silently hidden.
 */
function isOnline(device) {
  return device?.online !== false
}

const onlineDevices = computed(() => devices.value.filter(isOnline))
const offlineDevices = computed(() => devices.value.filter((d) => !isOnline(d)))

/**
 * The chip is hidden entirely until the account has offered a second
 * computer, so single-machine users see zero footprint.
 */
const hasOtherDevices = computed(() => devices.value.length > 0)

const activeDevice = computed(() =>
  activeDeviceId.value === LOCAL_DEVICE
    ? null
    : devices.value.find((d) => d.deviceId === activeDeviceId.value) || null,
)

const isRemote = computed(() => activeDeviceId.value !== LOCAL_DEVICE)

const activeDeviceName = computed(() =>
  activeDevice.value ? activeDevice.value.name : selfName.value || 'This computer',
)

/** "just now" / "3 h ago" — only shown for computers that are not up. */
function lastSeenLabel(device) {
  const iso = device?.lastSeenAt
  if (!iso) return 'not seen yet'
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (!Number.isFinite(minutes)) return 'not seen yet'
  if (minutes < 2) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

async function syncState() {
  const state = await desktop.mdGetState()
  activeDeviceId.value = state.activeDeviceId
  devices.value = state.devices || []
  connectionState.value = state.connectionState
}

async function init() {
  if (initialized.value) return
  initialized.value = true

  if (!isDesktop()) {
    connectionState.value = 'ready'
    return
  }

  try {
    await syncState()
    unsubscribe = desktop.mdOnConnectionState((next) => {
      connectionState.value = next
    })
    // Roster changes arrive as a nudge over the app websocket, which the
    // backend raises from the account's cloud channel. Re-reading through
    // Electron keeps main's cache and this list the same list.
    useWebSocket().on('multi_device_changed', () => {
      void refresh()
    })
    // Both go over the network; never block first paint on them.
    void refresh()
    void loadSelf()
  } catch (e) {
    console.warn('[MultiDevice] init failed:', e)
    connectionState.value = 'ready'
  }
}

async function refresh() {
  if (!isDesktop()) return
  try {
    devices.value = (await desktop.mdRefreshDevices()) || []
  } catch (e) {
    console.warn('[MultiDevice] refresh failed:', e)
  }
}

/**
 * Who THIS computer is — asked of main, not of the API base.
 *
 * The API base points at the active device, so reading identity from it would
 * label the "This computer" row with the name of the machine you are driving.
 */
async function loadSelf() {
  try {
    const status = await desktop.mdLocalStatus()
    selfName.value = status?.deviceName ?? null
    selfChannel.value = status?.channel ?? null
    selfSandbox.value = status?.sandbox ?? null
  } catch {
    // Non-fatal: the row simply renders without a name or qualifier.
  }
}

/**
 * Switch the whole window to a device. Main reloads on success, so this
 * usually does not return in a way the caller sees.
 */
async function switchToDevice(deviceId) {
  if (deviceId === activeDeviceId.value) return
  connectionState.value = 'connecting'
  activeDeviceId.value = deviceId
  try {
    connectionState.value = await desktop.mdSetActiveDevice(deviceId)
  } catch (e) {
    console.warn('[MultiDevice] switch failed:', e)
    connectionState.value = 'unreachable'
  }
}

/** Explicit escape hatch from the unreachable screen — never automatic. */
async function useThisComputer() {
  connectionState.value = 'connecting'
  activeDeviceId.value = LOCAL_DEVICE
  try {
    connectionState.value = await desktop.mdUseThisComputer()
  } catch {
    connectionState.value = 'unreachable'
  }
}

async function retry() {
  connectionState.value = 'connecting'
  try {
    connectionState.value = await desktop.mdRetry()
  } catch {
    connectionState.value = 'unreachable'
  }
}

export function useMultiDevice() {
  return {
    LOCAL_DEVICE,
    activeDeviceId: readonly(activeDeviceId),
    devices: readonly(devices),
    onlineDevices,
    offlineDevices,
    hasOtherDevices,
    activeDevice,
    activeDeviceName,
    isRemote,
    connectionState: readonly(connectionState),
    selfName: readonly(selfName),
    selfChannel: readonly(selfChannel),
    selfSandbox: readonly(selfSandbox),
    isOnline,
    lastSeenLabel,
    init,
    refresh,
    loadSelf,
    switchToDevice,
    useThisComputer,
    retry,
  }
}
