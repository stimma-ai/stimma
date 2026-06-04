/**
 * Composable for sharing media to Stimma Cloud.
 *
 * Provides reactive state and methods for the share flow,
 * including pre-share moderation checks and NSFW override.
 */
import { ref, readonly } from 'vue'

const isSharing = ref(false)
const shareResult = ref(null) // { shortcode, url, status }
const shareError = ref(null)

const isPreChecking = ref(false)
const preCheckResult = ref(null) // { blocked, decision, nsfw, reason }
const nsfwOverride = ref(false) // User's voluntary NSFW toggle
const identityRequired = ref(false)
const isSettingUpIdentity = ref(false)

export function useShare() {
  async function preCheckMedia(mediaId, { title, description } = {}) {
    isPreChecking.value = true
    preCheckResult.value = null

    try {
      const response = await fetch('/api/share/pre-check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ media_id: mediaId, title, description }),
      })

      const data = await response.json()
      preCheckResult.value = data

      // If cloud says NSFW, force the toggle on (user cannot reverse)
      if (data.nsfw) {
        nsfwOverride.value = true
      }

      return data
    } catch {
      // On pre-check failure, allow sharing (moderation runs at share time)
      preCheckResult.value = null
    } finally {
      isPreChecking.value = false
    }
  }

  async function shareMedia(mediaId, { title, description } = {}) {
    isSharing.value = true
    shareResult.value = null
    shareError.value = null

    try {
      const response = await fetch('/api/share', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          media_id: mediaId,
          title,
          description,
          nsfw_override: nsfwOverride.value,
        }),
      })

      const data = await response.json()

      if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to share')
      }

      shareResult.value = {
        shortcode: data.shortcode,
        url: data.url,
        status: data.status,
      }

      return shareResult.value
    } catch (error) {
      shareError.value = error.message
      throw error
    } finally {
      isSharing.value = false
    }
  }

  async function checkShareStatus() {
    try {
      const response = await fetch('/api/share/status')
      const data = await response.json()
      identityRequired.value = data.identity_required || false
      return data
    } catch {
      return { can_share: false, reason: 'Unable to check share status' }
    }
  }

  async function checkUsername(username) {
    try {
      const response = await fetch(`/api/share/check-username?username=${encodeURIComponent(username)}`)
      return await response.json()
    } catch {
      return { available: false, username, error: 'Unable to check username' }
    }
  }

  async function setupIdentity(username) {
    isSettingUpIdentity.value = true
    try {
      const response = await fetch('/api/share/setup-identity', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username }),
      })
      const data = await response.json()
      if (data.success) {
        identityRequired.value = false
      }
      return data
    } catch {
      return { success: false, error: 'Unable to set up identity' }
    } finally {
      isSettingUpIdentity.value = false
    }
  }

  function resetShare() {
    shareResult.value = null
    shareError.value = null
    preCheckResult.value = null
    isPreChecking.value = false
    nsfwOverride.value = false
    identityRequired.value = false
  }

  return {
    isSharing: readonly(isSharing),
    shareResult: readonly(shareResult),
    shareError: readonly(shareError),
    isPreChecking: readonly(isPreChecking),
    preCheckResult: readonly(preCheckResult),
    identityRequired: readonly(identityRequired),
    isSettingUpIdentity: readonly(isSettingUpIdentity),
    nsfwOverride,
    shareMedia,
    preCheckMedia,
    checkShareStatus,
    checkUsername,
    setupIdentity,
    resetShare,
  }
}
