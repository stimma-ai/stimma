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
}

export const SERVER_RESTART_GRACE_MS = 10 * 60_000

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
