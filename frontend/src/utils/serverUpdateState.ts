export interface ServerOperation {
  deviceId: string
  name: string
  action: 'update' | 'restart'
  startedAt: number
  fromVersion: string | null
  targetVersion: string | null
  fromStartedAt?: number
  sawTransition: boolean
  updateMachine: boolean
  machineTarget: string | null
  serverFinished?: boolean
  /** The client follow-up's most recent request for its own update check. */
  machineCheckRequestedAt?: number
  /** The client's last completed check time when that request was made. */
  machineCheckBaseline?: string | null
  machineCheckAttempts?: number
}

export const SERVER_RESTART_GRACE_MS = 10 * 60_000

/**
 * An unconfirmed server operation stops being shown after the grace period.
 * Once the server stage has finished, the client follow-up is not on that
 * clock (the client may have been suspended through it); it ends through
 * machineFollowUpStep instead.
 */
export function serverOperationExpired(operation: ServerOperation, now: number): boolean {
  return !operation.serverFinished && now - operation.startedAt > SERVER_RESTART_GRACE_MS
}

/** Retry a client check that ended without completing (for example offline). */
export const MACHINE_CHECK_RETRY_MS = 60_000
export const MACHINE_CHECK_ATTEMPTS = 3

export interface ClientUpdaterState {
  currentVersion: string
  /** An update is available or staged. */
  available: boolean
  /** A check or download is running here or in the window that owns the updater. */
  busy: boolean
  /** When the client's last check completed; it advances only on completion. */
  lastCheckedAt: string | null
}

/**
 * The next step of "Update all" once the server has finished. Intent survives
 * while a check or download runs, however long; the follow-up ends only when
 * the update starts, a completed check finds nothing, or checks keep failing.
 */
export function machineFollowUpStep(operation: ServerOperation, client: ClientUpdaterState, now: number):
  'done' | 'wait' | 'install' | 'check' | 'give-up' {
  if (operation.machineTarget && client.currentVersion === operation.machineTarget) return 'done'
  if (client.busy) return 'wait'
  if (client.available) return 'install'
  if (operation.machineCheckRequestedAt === undefined) return 'check'
  if (client.lastCheckedAt !== (operation.machineCheckBaseline ?? null)) return 'done'
  if (now - operation.machineCheckRequestedAt < MACHINE_CHECK_RETRY_MS) return 'wait'
  return (operation.machineCheckAttempts ?? 0) >= MACHINE_CHECK_ATTEMPTS ? 'give-up' : 'check'
}

/** Only server-reported state confirms completion; a disconnect is not failure. */
export function serverOperationResult(operation: ServerOperation, server: {
  status: string; version?: string | null; serverStartedAt?: number
}): 'pending' | 'complete' | 'unchanged' {
  if (server.status !== 'ready') return 'pending'
  if (operation.action === 'update') {
    // The feed can advance between checking and clicking Update.
    if (server.version && server.version !== operation.fromVersion) return 'complete'
    if (operation.sawTransition && server.version === operation.fromVersion) return 'unchanged'
  } else if ((operation.fromStartedAt && server.serverStartedAt && operation.fromStartedAt !== server.serverStartedAt)
    || operation.sawTransition) return 'complete'
  return 'pending'
}
