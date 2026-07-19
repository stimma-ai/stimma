export const CANARY_UPDATE_CHECK_INTERVAL_MS = 15 * 60 * 1000
export const DEFAULT_UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000

export function updateCheckIntervalMs(channel: string): number {
  return channel.toLowerCase() === 'canary'
    ? CANARY_UPDATE_CHECK_INTERVAL_MS
    : DEFAULT_UPDATE_CHECK_INTERVAL_MS
}
