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
  /** When the server stage was confirmed; the client follow-up runs from here. */
  serverFinishedAt?: number
}

export const SERVER_RESTART_GRACE_MS = 10 * 60_000

/**
 * An operation stops being shown once its current stage has outlasted the
 * grace period. The client follow-up of "Update all" gets its own window from
 * when the server stage was confirmed, so a late confirmation (for example
 * after the app was suspended) still runs it.
 */
export function serverOperationExpired(operation: ServerOperation, now: number): boolean {
  return now - (operation.serverFinishedAt ?? operation.startedAt) > SERVER_RESTART_GRACE_MS
}

/**
 * How long a hidden, expired operation keeps the client polling for the
 * server answer that resolves it. Past this it waits for an ordinary refresh.
 */
export const SERVER_RECONCILE_LIMIT_MS = 60 * 60_000

/** An operation still worth polling for, whether or not it is shown. */
export function serverOperationTracked(operation: ServerOperation, now: number): boolean {
  return now - (operation.serverFinishedAt ?? operation.startedAt) < SERVER_RECONCILE_LIMIT_MS
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
