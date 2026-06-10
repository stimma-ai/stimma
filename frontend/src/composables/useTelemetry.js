/**
 * Telemetry composable — fire-and-forget event tracking via the sidecar.
 *
 * Frontend events flow through the backend's telemetry client
 * (POST /api/telemetry/track), which owns consent gating, pre-consent
 * buffering, batching, and the official-build no-op. Failures are
 * swallowed — telemetry must never affect the app.
 */
import { getApiBase } from '../apiConfig'

export function useTelemetry() {
  function track(event, properties = {}, category = undefined) {
    try {
      const body = { event, properties }
      if (category) body.category = category
      fetch(`${getApiBase()}/telemetry/track`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).catch(() => {})
    } catch {
      // fire-and-forget
    }
  }

  return { track }
}
