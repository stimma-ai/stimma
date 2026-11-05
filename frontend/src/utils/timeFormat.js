/**
 * Utility functions for formatting time durations and remaining time
 */

/**
 * Format a past timestamp relative to now (e.g., "5m ago", "3h ago").
 * Falls back to a locale date beyond a week.
 *
 * @param {string|null} dateStr - ISO timestamp
 * @returns {string} Relative time string, or '' for falsy input
 */
/**
 * Epoch ms for a server timestamp. The backend writes naive UTC
 * ("2026-09-05T19:39:00.938589"); without a suffix Date.parse would read it
 * as local time and skew ordering by the UTC offset.
 */
export function parseServerTime(value) {
  if (!value) return 0
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`
  const ms = Date.parse(iso)
  return Number.isNaN(ms) ? 0 : ms
}

export function formatRelativeTime(dateStr) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  if (Number.isNaN(date.getTime())) return ''
  const diffMs = Date.now() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return 'Just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  return formatDate(date)
}

/**
 * The compact relative form for list rows ("now", "5m", "3h", "2d"), falling
 * back to formatDate beyond a week.
 */
export function formatRelativeShort(dateStr) {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  if (Number.isNaN(date.getTime())) return ''
  const diffMs = Date.now() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return 'now'
  if (diffMins < 60) return `${diffMins}m`
  if (diffHours < 24) return `${diffHours}h`
  if (diffDays < 7) return `${diffDays}d`
  return formatDate(date)
}

/**
 * THE app date format: "Aug 13" in the current year, "Aug 13, 2026" otherwise.
 * Pass `{ year: 'always' }` where the year must always show (detail panels,
 * account and sharing facts). Never the numeric locale form ("8/13/2026").
 *
 * @param {string|number|Date|null} value
 * @param {{ year?: 'auto'|'always' }} [options]
 * @returns {string} '' for a falsy or invalid value
 */
export function formatDate(value, { year = 'auto' } = {}) {
  if (!value) return ''
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const opts = { month: 'short', day: 'numeric' }
  if (year === 'always' || date.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric'
  return date.toLocaleDateString(undefined, opts)
}

/**
 * Format an estimated number of seconds for compact progress UI.
 *
 * @param {number|string|null} seconds
 * @returns {string} Compact ETA such as "12s", "3m", or "2h"
 */
export function formatEta(seconds) {
  const totalSeconds = Math.max(0, Math.ceil(Number(seconds) || 0))
  if (totalSeconds < 60) return `${totalSeconds}s`

  const totalMinutes = Math.ceil(totalSeconds / 60)
  if (totalMinutes < 60) return `${totalMinutes}m`
  return `${Math.ceil(totalMinutes / 60)}h`
}

/**
 * Format remaining time for auto-delete badge display
 * Uses thresholds: < 60min = minutes, < 72h = hours, >= 72h = days
 *
 * @param {string|null} autoDeleteAt - ISO timestamp when item will be deleted (UTC)
 * @returns {string|null} Formatted time string (e.g., "13m", "4h", "3d") or null
 */
export function formatRemainingTime(autoDeleteAt) {
  if (!autoDeleteAt) {
    return null
  }

  const now = new Date()
  // Ensure the timestamp is treated as UTC
  // If it's just a timestamp without 'Z', add it
  let utcTimestamp = autoDeleteAt
  if (!utcTimestamp.endsWith('Z') && !utcTimestamp.includes('+')) {
    utcTimestamp += 'Z'
  }
  const deleteTime = new Date(utcTimestamp)
  const remainingMs = deleteTime.getTime() - now.getTime()

  // Already expired - show 0m to bridge the gap before deletion
  if (remainingMs <= 0) {
    return '0m'
  }

  const remainingMinutes = Math.max(1, Math.ceil(remainingMs / (1000 * 60)))
  const remainingHours = Math.max(1, Math.ceil(remainingMs / (1000 * 60 * 60)))
  const remainingDays = Math.max(1, Math.ceil(remainingMs / (1000 * 60 * 60 * 24)))

  // < 60 minutes: show minutes
  if (remainingMinutes < 60) {
    return `${remainingMinutes}m`
  }

  // < 72 hours: show hours
  if (remainingHours < 72) {
    return `${remainingHours}h`
  }

  // >= 72 hours: show days
  return `${remainingDays}d`
}

/**
 * Check if an item is expired based on auto_delete_at timestamp
 *
 * @param {string|null} autoDeleteAt - ISO timestamp when item will be deleted
 * @returns {boolean} True if expired, false otherwise
 */
export function isExpired(autoDeleteAt) {
  if (!autoDeleteAt) {
    return false
  }

  const now = new Date()
  let utcTimestamp = autoDeleteAt
  if (!utcTimestamp.endsWith('Z') && !utcTimestamp.includes('+')) {
    utcTimestamp += 'Z'
  }
  const deleteTime = new Date(utcTimestamp)
  return deleteTime <= now
}

/**
 * Get color class for remaining time badge based on urgency
 *
 * @param {string|null} autoDeleteAt - ISO timestamp when item will be deleted
 * @returns {string} Tailwind color classes for the badge
 */
export function getRemainingTimeColor(autoDeleteAt) {
  if (!autoDeleteAt) {
    return 'bg-gray-500/80'
  }

  const now = new Date()
  let utcTimestamp = autoDeleteAt
  if (!utcTimestamp.endsWith('Z') && !utcTimestamp.includes('+')) {
    utcTimestamp += 'Z'
  }
  const deleteTime = new Date(utcTimestamp)
  const remainingMs = deleteTime - now
  const remainingHours = Math.floor(remainingMs / (1000 * 60 * 60))

  // Less than 1 hour: red (urgent)
  if (remainingHours < 1) {
    return 'bg-red-500/80'
  }

  // Less than 6 hours: orange (warning)
  if (remainingHours < 6) {
    return 'bg-orange-500/80'
  }

  // Less than 24 hours: yellow
  if (remainingHours < 24) {
    return 'bg-yellow-500/80'
  }

  // 24+ hours: gray (not urgent)
  return 'bg-gray-500/80'
}
