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
  } = {},
) {
  const startedAt = Date.now()
  let attempt = 0

  while (true) {
    attempt += 1
    try {
      const response = await fetchImpl(`${backendOrigin}/`)
      if (response.ok) return response
    } catch {
      // Connection failures are expected until the sidecar finishes startup.
    }

    onWaiting?.({
      attempt,
      elapsedMs: Date.now() - startedAt,
    })
    await sleepImpl(retryDelayMs)
  }
}
