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
  /** When the client follow-up first checked for its own update. */
  machineCheckedAt?: number
}

export const SERVER_RESTART_GRACE_MS = 10 * 60_000

/** How long the client follow-up waits for its own update check to find something. */
export const MACHINE_FOLLOW_UP_MS = 2 * 60_000

/**
 * An unconfirmed server operation stops being shown after the grace period.
 * Once the server stage has finished, the client follow-up is not on that
 * clock (the client may have been suspended through it): it ends when the
 * client update starts, or a while after the client's own check found nothing.
 */
export function serverOperationExpired(operation: ServerOperation, now: number): boolean {
  if (operation.serverFinished) {
    return operation.machineCheckedAt !== undefined && now - operation.machineCheckedAt > MACHINE_FOLLOW_UP_MS
  }
  return now - operation.startedAt > SERVER_RESTART_GRACE_MS
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
