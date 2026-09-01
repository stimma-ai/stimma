const DEFAULT_RETRY_DELAY_MS = 500
const LONG_STARTUP_THRESHOLD_MS = 15_000

export function getStartupWaitMessage(elapsedMs) {
  if (elapsedMs < LONG_STARTUP_THRESHOLD_MS) return null

  return 'Upgrading your library. Large libraries may take several minutes.'
}

const sleep = (delayMs) => new Promise(resolve => setTimeout(resolve, delayMs))

/**
 * Wait until the sidecar finishes initialization.
 *
 * Receiving the port means the native supervisor started successfully, but
 * the backend can still be applying a transactional, one-time data migration.
 * That work has no honest fixed upper bound, so readiness must not be turned
 * into a startup failure merely because a profile is large.
 */
export async function waitForBackendHealth(
  backendOrigin,
  {
    fetchImpl = globalThis.fetch,
    sleepImpl = sleep,
    retryDelayMs = DEFAULT_RETRY_DELAY_MS,
    onWaiting = null,
    shouldAbort = null,
  } = {},
) {
  const startedAt = Date.now()
  let attempt = 0

  while (true) {
    // "Starting up" and "unreachable" both look like a failing health check,
    // but they call for opposite behaviour: the first must wait indefinitely
    // (a migration has no honest upper bound), the second must stop waiting
    // so the app can mount and SAY it is unreachable. Only the caller can
    // tell them apart, so it decides.
    if (shouldAbort?.()) return null

    attempt += 1
    try {
      const response = await fetchImpl(`${backendOrigin}/`)
      if (response.ok) return response
    } catch {
      // Connection failures are expected until the sidecar finishes startup.
    }

    if (shouldAbort?.()) return null

    onWaiting?.({
      attempt,
      elapsedMs: Date.now() - startedAt,
    })
    await sleepImpl(retryDelayMs)
  }
}
