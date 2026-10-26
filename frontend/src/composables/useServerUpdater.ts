import { computed, ref, watch } from 'vue'
import { getApiBase } from '../apiConfig'
import { makeInstallKey } from '../utils/installKey'
import { SERVER_RESTART_GRACE_MS, serverOperationExpired, serverOperationResult, serverOperationTracked, type ServerOperation } from '../utils/serverUpdateState'
import { COMMAND_BURST_MS, createStatusPoller, type StatusPoller } from '../utils/serverStatusPoller'
import { SERVER_UPDATE_CHECK_STARTED } from '../utils/serverUpdateCheck'
import { THIS_MACHINE_LABEL, useMultiDevice } from './useMultiDevice'
import { useAppUpdater } from './useAppUpdater'
import { usePrivacyLockdown } from './usePrivacyLockdown'
import { useWebSocket } from './useWebSocket'

interface ServerStatus {
  headless: boolean
  version: string | null
  availableVersion: string | null
  status: string
  bootstrapVersion: string
  latestBootstrapVersion?: string
  bootstrapUpdateRequired?: boolean
  bootstrapUpdateAvailable?: boolean
  serverStartedAt?: number
  updateWindow?: string
  timezone?: string
  error?: string | null
}

const KEY = makeInstallKey('server_update_operation')
const server = ref<ServerStatus | null>(null)
const operation = ref<ServerOperation | null>(null)
const error = ref('')
const now = ref(Date.now())
let started = false
let polling = false
let checkingMachine = false
let poller: StatusPoller | null = null
let commandBurstUntil = 0
let stopWatches: Array<() => void> = []
const device = useMultiDevice()
const app = useAppUpdater()
const { privacyLockdownActive } = usePrivacyLockdown()
// An expired operation is hidden but kept until a status response reconciles
// it, so a server that finished while this client was suspended still counts.
const pending = computed(() => operation.value?.deviceId === device.activeDeviceId.value
  && !serverOperationExpired(operation.value, now.value) ? operation.value : null)
const connected = computed(() => device.connectionState.value === 'ready')
const visibleServer = computed(() => connected.value ? server.value : null)
const restartExpected = computed(() => Boolean(pending.value && !pending.value.serverFinished
  && now.value - pending.value.startedAt < SERVER_RESTART_GRACE_MS))
const restartTakingLonger = computed(() => Boolean(pending.value && now.value - pending.value.startedAt > 3 * 60_000))
const machineLabel = THIS_MACHINE_LABEL.replace('This ', 'this ')
const machineAvailable = computed(() => !privacyLockdownActive.value && (app.hasUpdate.value || app.pendingRestart.value))
const serverAvailable = computed(() => !privacyLockdownActive.value && Boolean(visibleServer.value?.availableVersion
  && visibleServer.value.availableVersion !== visibleServer.value.version))
const baseRequired = computed(() => Boolean(visibleServer.value?.bootstrapUpdateRequired))
const baseAvailable = computed(() => Boolean(visibleServer.value?.bootstrapUpdateAvailable))
const serverBusy = computed(() => Boolean(pending.value || (visibleServer.value && !['ready', 'error', 'waiting_for_idle'].includes(visibleServer.value.status))))
const busy = computed(() => serverBusy.value || app.isDownloading.value)
const installableCount = computed(() => Number(machineAvailable.value) + Number(serverAvailable.value && !baseRequired.value))
const updateCount = computed(() => Number(machineAvailable.value) + Number(serverAvailable.value) + Number(baseAvailable.value || baseRequired.value))
const serverName = computed(() => pending.value?.name || device.activeDeviceName.value || 'Stimma Server')
const statusLabel = computed(() => {
  if (pending.value?.serverFinished) return `Updating ${machineLabel}…`
  if (!connected.value && restartExpected.value) return `Restarting ${serverName.value}…`
  const status = visibleServer.value?.status
  if (pending.value && status === 'ready') return `${pending.value.action === 'restart' ? 'Restarting' : 'Updating'} ${serverName.value}…`
  return ({ checking: 'Checking for updates…', downloading: 'Downloading update…', restarting: 'Restarting…', starting: 'Starting…',
    waiting_for_idle: 'Scheduled update waiting for idle time', ready: 'Running', error: 'Running' } as Record<string, string>)[status || '']
    || (pending.value ? `Updating ${serverName.value}…` : 'Running')
})

function persist() {
  try {
    if (operation.value) sessionStorage.setItem(KEY, JSON.stringify(operation.value))
    else sessionStorage.removeItem(KEY)
  } catch { /* The live operation still works if browser storage is unavailable. */ }
}
function clearOperation() { operation.value = null; persist() }

async function updateMachine() {
  if (privacyLockdownActive.value || app.isDownloading.value) return
  if (app.pendingRestart.value) await app.restartToApply()
  else if (app.hasUpdate.value) await app.downloadAndInstallUpdate()
}

async function resumeMachine(op: ServerOperation) {
  if (!app.loadedPrefs.value || app.isDownloading.value || app.isChecking.value || checkingMachine) return
  if (app.currentVersion.value === op.machineTarget) { clearOperation(); return }
  if (machineAvailable.value) { clearOperation(); await updateMachine(); return }
  checkingMachine = true
  try { await app.checkForUpdates('manual') } finally { checkingMachine = false }
}

/** Resolves false when the server could not be reached, so polling can back off. */
async function refresh(): Promise<boolean | undefined> {
  now.value = Date.now()
  if (polling || !connected.value || privacyLockdownActive.value) return
  polling = true
  const id = device.activeDeviceId.value
  let answered = false
  try {
    const response = await fetch(`${getApiBase()}/headless/status`, { signal: AbortSignal.timeout(10_000) })
    if (id !== device.activeDeviceId.value) return
    if (response.status === 404) { server.value = null; return }
    if (!response.ok) return false
    const data: ServerStatus = await response.json()
    if (id !== device.activeDeviceId.value) return
    answered = true
    server.value = data.headless ? data : null
    // Reconcile even an expired operation: the server may have finished it
    // while this client was suspended.
    const op = operation.value?.deviceId === id ? operation.value : null
    if (!op || !data.headless) return
    if (op.serverFinished) { await resumeMachine(op); return }
    if (!['ready', 'error'].includes(data.status)) { op.sawTransition = true; persist(); return }
    if (data.status === 'error') {
      // A real supervisor error is actionable. A network interruption is not.
      error.value = data.error || ''
      clearOperation()
      return
    }
    const result = serverOperationResult(op, data)
    if (result === 'complete') {
      if (op.updateMachine) { op.serverFinished = true; op.serverFinishedAt = Date.now(); persist(); await resumeMachine(op) }
      else clearOperation()
    } else if (result === 'unchanged') clearOperation() // The ordinary update pill remains available.
  } catch {
    // Status is unavailable during restarts; keep the operation across reconnects.
    return false
  }
  finally {
    polling = false
    // Give up only after the server answered; a failed request (app still
    // resuming, network down) proves nothing about how the operation ended.
    now.value = Date.now()
    if (answered && operation.value?.deviceId === id && serverOperationExpired(operation.value, now.value)) clearOperation()
  }
}

async function act(action: 'check' | 'update' | 'restart', updateLocal = false) {
  if (!connected.value || !server.value?.headless || serverBusy.value || privacyLockdownActive.value) return
  if (action === 'update' && baseRequired.value) return
  error.value = ''
  const id = device.activeDeviceId.value
  startCommandBurst()
  if (action !== 'check') {
    operation.value = { deviceId: id, name: device.activeDeviceName.value, action, startedAt: Date.now(),
      fromVersion: server.value.version, targetVersion: server.value.availableVersion,
      fromStartedAt: server.value.serverStartedAt, sawTransition: false, updateMachine: updateLocal,
      machineTarget: app.stagedVersion.value || app.availableVersion.value }
    persist()
  }
  try {
    const response = await fetch(`${getApiBase()}/headless/${action}`, { method: 'POST', signal: AbortSignal.timeout(15_000) })
    const data = await response.json()
    if (id !== device.activeDeviceId.value) return
    if (!response.ok) { error.value = data.detail || 'Could not start the server operation'; clearOperation(); return }
    if (data.headless) server.value = data
    wakeStatus()
  } catch {
    // The request may have succeeded before the connection closed. Do not
    // automatically submit another update or restart to a different server.
    if (action === 'check') error.value = 'Could not check for updates'
  }
}

async function updateAll() {
  if (busy.value) return
  if (serverAvailable.value && !baseRequired.value) await act('update', machineAvailable.value)
  else if (machineAvailable.value) await updateMachine()
}

export function startServerUpdater() {
  if (started) return
  started = true
  try {
    const saved = JSON.parse(sessionStorage.getItem(KEY) || 'null')
    if (saved && ['update', 'restart'].includes(saved.action) && typeof saved.deviceId === 'string'
      && typeof saved.startedAt === 'number') operation.value = saved // Hidden if expired until reconciled.
    else sessionStorage.removeItem(KEY)
  } catch { /* Ignore invalid session state. */ }
  // Poll quickly only while an operation is in flight; otherwise rely on
  // reconnects, foreground returns, and explicit checks, with a slow backstop.
  // Background and offline pause only that idle polling: an operation in
  // flight keeps being tracked (if the OS freezes the page instead, the
  // operation is reconciled on the first server answer after resume).
  let visible = document.visibilityState !== 'hidden'
  let appActive = true
  const statusPoller = poller = createStatusPoller({
    refresh,
    isActive: () => serverBusy.value || tracking() || Date.now() < commandBurstUntil,
    foreground: visible,
    online: navigator.onLine !== false,
  })
  const onVisibility = () => { visible = document.visibilityState !== 'hidden'; statusPoller.setForeground(visible && appActive) }
  const onAppActive = (event: Event) => { appActive = (event as CustomEvent).detail !== false; statusPoller.setForeground(visible && appActive) }
  const onOnline = () => statusPoller.setOnline(true)
  const onOffline = () => statusPoller.setOnline(false)
  const onCheckStarted = () => { startCommandBurst(); statusPoller.wake() }
  document.addEventListener('visibilitychange', onVisibility)
  window.addEventListener('stimma:app-active', onAppActive)
  window.addEventListener('online', onOnline)
  window.addEventListener('offline', onOffline)
  window.addEventListener(SERVER_UPDATE_CHECK_STARTED, onCheckStarted)
  stopWatches.push(() => {
    document.removeEventListener('visibilitychange', onVisibility)
    window.removeEventListener('stimma:app-active', onAppActive)
    window.removeEventListener('online', onOnline)
    window.removeEventListener('offline', onOffline)
    window.removeEventListener(SERVER_UPDATE_CHECK_STARTED, onCheckStarted)
  })
  // A server restart drops and re-opens the app socket on every client.
  stopWatches.push(useWebSocket().on('websocket_reconnected', () => statusPoller.wake()))
  stopWatches.push(watch([serverBusy, operation], () => statusPoller.reschedule()))
  stopWatches.push(watch(device.activeDeviceId, () => { server.value = null; error.value = ''; statusPoller.wake() }))
  stopWatches.push(watch(device.connectionState, state => {
    if (pending.value && state !== 'ready') { pending.value.sawTransition = true; persist() }
    if (state === 'ready') statusPoller.wake()
  }))
  statusPoller.wake()
}

/**
 * Tracking is separate from what is shown: an operation hidden past its grace
 * window still polls until a server answer resolves it, so a client that was
 * cut off (or frozen) through the end of an update still runs its follow-up.
 */
function tracking() {
  const op = operation.value
  return Boolean(op && op.deviceId === device.activeDeviceId.value && serverOperationTracked(op, Date.now()))
}

function startCommandBurst() {
  commandBurstUntil = Date.now() + COMMAND_BURST_MS
  poller?.reschedule()
}

function wakeStatus() {
  if (poller) poller.wake()
  else void refresh()
}

export function stopServerUpdater() {
  poller?.stop()
  poller = null
  stopWatches.forEach(stop => stop())
  stopWatches = []
  started = false
}

export function useServerUpdater() {
  return { server: visibleServer, pending, error, connected, serverName, machineLabel, machineAvailable,
    serverAvailable, baseRequired, baseAvailable, serverBusy, busy, installableCount, updateCount,
    restartExpected, restartTakingLonger, statusLabel, refresh: wakeStatus, act, updateMachine, updateAll }
}
