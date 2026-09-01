/**
 * Multi-device state for the renderer.
 *
 * The window is "on" exactly one device at a time, and that scope owns
 * everything in the window. The renderer does not talk to remote devices
 * itself — it asks main to point the proxy, and main reloads the window.
 * So this composable is thin on purpose: selection, the device list, and
 * the connection state main pushes to us.
 */
import { ref, computed, readonly } from 'vue'
import { desktop, isDesktop } from '../desktop'

const LOCAL_DEVICE = 'local'

// Global reactive state (shared across all components)
const activeDeviceId = ref(LOCAL_DEVICE)
const devices = ref([])
const connectionState = ref('connecting')
const initialized = ref(false)
// This install's own channel/sandbox, so "This computer" can carry the same
// qualifier as every other row rather than being the one ambiguous entry.
const selfChannel = ref(null)
const selfSandbox = ref(null)

let unsubscribe = null

/** Serving devices, which are the only ones that can be switched to. */
const availableDevices = computed(() => devices.value.filter((d) => d.serving))

/**
 * The chip is hidden entirely until the account has had a second device, so
 * single-machine users see zero footprint.
 */
const hasOtherDevices = computed(() => devices.value.length > 0)

const activeDevice = computed(() =>
  activeDeviceId.value === LOCAL_DEVICE
    ? null
    : devices.value.find((d) => d.deviceId === activeDeviceId.value) || null,
)

const isRemote = computed(() => activeDeviceId.value !== LOCAL_DEVICE)

const activeDeviceName = computed(() =>
  activeDevice.value ? activeDevice.value.name : 'This computer',
)

/** Quiet route fact for a device row: "local network", "Tailscale", or unreachable. */
function routeLabel(device) {
  if (!device?.serving) return 'unreachable'
  const kinds = new Set((device.routes || []).map((r) => r.kind))
  if (kinds.has('lan')) return 'local network'
  if (kinds.has('tailscale')) return 'Tailscale'
  return 'unreachable'
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

/** Local identity comes from this install's own backend, not the registry. */
async function loadSelf() {
  try {
    const { getApiBase } = await import('../apiConfig')
    const response = await fetch(`${getApiBase()}/multi-device/status`)
    if (!response.ok) return
    const status = await response.json()
    selfChannel.value = status.channel ?? null
    selfSandbox.value = status.sandbox ?? null
  } catch {
    // Non-fatal: the row simply renders without a qualifier.
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
    availableDevices,
    hasOtherDevices,
    activeDevice,
    activeDeviceName,
    isRemote,
    connectionState: readonly(connectionState),
    selfChannel: readonly(selfChannel),
    selfSandbox: readonly(selfSandbox),
    routeLabel,
    init,
    refresh,
    switchToDevice,
    useThisComputer,
    retry,
  }
}
