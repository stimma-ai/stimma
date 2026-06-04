/**
 * Telemetry composable — fire-and-forget event tracking via PostHog.
 *
 * Pre-init events are dropped (PostHog isn't ready yet); after init
 * everything goes straight to PostHog.
 */
import { capturePostHog } from './usePostHog'

export function useTelemetry() {
  function track(event, properties = {}) {
    capturePostHog(event, properties)
  }

  return { track }
}
