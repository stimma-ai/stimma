/**
 * Reads the failure statuses the native shells' local proxy answers with
 * (mobile/contract/proxy-failures.json; the Electron proxy uses the same
 * 502/503 meanings). A connection problem must never be shown as a bad PIN or
 * an expired sign-in, while a genuine 401/403 keeps its existing handling.
 */

/**
 * Set by the Android proxy on responses it generated itself, carrying the
 * failure category. Classification needs only the status; the header lets
 * diagnostics tell a proxy 502 from one the server returned.
 */
export const PROXY_FAILURE_HEADER = 'X-Stimma-Proxy-Failure'

export type ConnectionFailure = 'unreachable' | 'unavailable' | 'timeout'

type ResponseLike = { status: number }

const CONNECTION_FAILURES: Record<number, ConnectionFailure> = {
  502: 'unreachable', // The server could not be reached or dropped the connection.
  503: 'unavailable', // No active server, or the connection is being restored.
  504: 'timeout', // The server did not answer in time.
}

/** The connection problem a response reports, or null when it is an ordinary server answer. */
export function connectionFailure(response: ResponseLike): ConnectionFailure | null {
  return CONNECTION_FAILURES[response.status] ?? null
}

/** Error text for a failed PIN verification response. */
export function pinVerificationError(response: ResponseLike, detail: unknown, deviceName = 'the server'): string {
  const failure = connectionFailure(response)
  if (failure === 'timeout') return `No response from ${deviceName}`
  if (failure) return `Lost connection to ${deviceName}`
  return typeof detail === 'string' && detail ? detail : 'Invalid PIN'
}
