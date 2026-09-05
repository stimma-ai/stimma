import { computed, ref, watch } from 'vue'
import { getApiBase } from '../apiConfig'
import { makeInstallKey } from '../utils/installKey'
import { SERVER_RESTART_GRACE_MS, serverOperationResult, type ServerOperation } from '../utils/serverUpdateState'
import { THIS_MACHINE_LABEL, useMultiDevice } from './useMultiDevice'
import { useAppUpdater } from './useAppUpdater'
import { usePrivacyLockdown } from './usePrivacyLockdown'

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
let pollTimer: ReturnType<typeof setInterval> | undefined
let stopWatches: Array<() => void> = []
const device = useMultiDevice()
const app = useAppUpdater()
const { privacyLockdownActive } = usePrivacyLockdown()
const pending = computed(() => operation.value?.deviceId === device.activeDeviceId.value ? operation.value : null)
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

async function refresh() {
  now.value = Date.now()
  if (pending.value && now.value - pending.value.startedAt > SERVER_RESTART_GRACE_MS) clearOperation()
  if (polling || !connected.value || privacyLockdownActive.value) return
  polling = true
  const id = device.activeDeviceId.value
  try {
    const response = await fetch(`${getApiBase()}/headless/status`, { signal: AbortSignal.timeout(10_000) })
    if (id !== device.activeDeviceId.value) return
    if (response.status === 404) { server.value = null; return }
    if (!response.ok) return
    const data: ServerStatus = await response.json()
    if (id !== device.activeDeviceId.value) return
    server.value = data.headless ? data : null
    const op = pending.value
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
      if (op.updateMachine) { op.serverFinished = true; persist(); await resumeMachine(op) }
      else clearOperation()
    } else if (result === 'unchanged') clearOperation() // The ordinary update pill remains available.
  } catch { /* Status is unavailable during restarts; keep the operation across reconnects. */ }
  finally { polling = false }
}

async function act(action: 'check' | 'update' | 'restart', updateLocal = false) {
  if (!connected.value || !server.value?.headless || serverBusy.value || privacyLockdownActive.value) return
  if (action === 'update' && baseRequired.value) return
  error.value = ''
  const id = device.activeDeviceId.value
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
    void refresh()
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
      && typeof saved.startedAt === 'number' && Date.now() - saved.startedAt < SERVER_RESTART_GRACE_MS) operation.value = saved
    else sessionStorage.removeItem(KEY)
  } catch { /* Ignore invalid session state. */ }
  stopWatches.push(watch(device.activeDeviceId, () => { server.value = null; error.value = ''; void refresh() }))
  stopWatches.push(watch(device.connectionState, state => {
    if (pending.value && state !== 'ready') { pending.value.sawTransition = true; persist() }
    if (state === 'ready') void refresh()
  }))
  pollTimer = setInterval(() => { void refresh() }, 3000)
  void refresh()
}

export function stopServerUpdater() {
  clearInterval(pollTimer)
  stopWatches.forEach(stop => stop())
  stopWatches = []
  started = false
}

export function useServerUpdater() {
  return { server: visibleServer, pending, error, connected, serverName, machineLabel, machineAvailable,
    serverAvailable, baseRequired, baseAvailable, serverBusy, busy, installableCount, updateCount,
    restartExpected, restartTakingLonger, statusLabel, refresh, act, updateMachine, updateAll }
}
