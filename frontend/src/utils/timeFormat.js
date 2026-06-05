/**
 * Utility functions for formatting time durations and remaining time
 */

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

  const remainingMinutes = Math.round(remainingMs / (1000 * 60))
  const remainingHours = Math.round(remainingMs / (1000 * 60 * 60))
  const remainingDays = Math.round(remainingMs / (1000 * 60 * 60 * 24))

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
