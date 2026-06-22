/**
 * Cloud account composable for fetching user info.
 *
 * Provides account tier, balance, and other cloud-specific data.
 *
 * Note: Account info is now fetched from the backend which is the source of truth.
 * The backend persists auth state and fetches tier info from stimma.cloud.
 */
import { ref, readonly } from 'vue'
import { useSettingsApi } from './useSettingsApi'

// Default fallback URL
const DEFAULT_CLOUD_BASE_URL = 'https://stimma.ai'

// Global reactive state (shared across all components)
const cloudBaseUrl = ref(DEFAULT_CLOUD_BASE_URL)
const cloudUser = ref(null)
const isCloudLoading = ref(false)
const cloudError = ref(null)

function normalizeAccountError(response, body) {
  const detail = body?.detail
  if (detail && typeof detail === 'object') {
    return {
      code: detail.code || `http_${response.status}`,
      message: detail.message || `Failed to fetch account: ${response.status}`,
      status: response.status,
    }
  }
  if (typeof detail === 'string') {
    return {
      code: `http_${response.status}`,
      message: detail,
      status: response.status,
    }
  }
  return {
    code: `http_${response.status}`,
    message: `Failed to fetch account: ${response.status}`,
    status: response.status,
  }
}

async function readAccountError(response) {
  try {
    const body = await response.json()
    return normalizeAccountError(response, body)
  } catch (e) {
    return normalizeAccountError(response, null)
  }
}

function notifyAuthRequired(error) {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('stimma-auth-required', { detail: error }))
  }
}

/**
 * Get the cloud base URL from settings (fetches if not already set).
 */
async function ensureCloudBaseUrl() {
  // If already set to something other than default, use it
  if (cloudBaseUrl.value !== DEFAULT_CLOUD_BASE_URL) {
    return cloudBaseUrl.value
  }

  // Try to fetch from settings
  try {
    const { fetchSettings } = useSettingsApi()
    const settings = await fetchSettings()
    if (settings.cloud_base_url) {
      cloudBaseUrl.value = settings.cloud_base_url
    }
  } catch (e) {
    // Use default on error
  }
  return cloudBaseUrl.value
}

/**
 * Set the cloud base URL (called by App.vue after loading settings).
 * This allows avoiding an extra settings fetch when the app already has settings.
 */
export function setCloudBaseUrl(url) {
  if (url) {
    cloudBaseUrl.value = url
  }
}

/**
 * Fetch user info via backend proxy which calls stimma.cloud.
 */
export async function fetchCloudAccount() {
  isCloudLoading.value = true
  cloudError.value = null

  try {
    const response = await fetch('/api/auth/account')

    if (!response.ok) {
      const error = await readAccountError(response)
      cloudError.value = error
      if (response.status === 401) {
        cloudUser.value = null
        notifyAuthRequired(error)
        return null
      }
      return null
    }

    const data = await response.json()

    // Handle both old (balanceCents) and new (credits) field names
    cloudUser.value = {
      ...data,
      credits: data.credits ?? data.balanceCents ?? 0,
    }
    return cloudUser.value
  } catch (error) {
    console.error('Failed to fetch cloud account:', error)
    cloudError.value = {
      code: 'cloud_unreachable',
      message: "Couldn't reach Stimma Cloud. Check your connection and try again.",
    }
    return null
  } finally {
    isCloudLoading.value = false
  }
}

/**
 * Format balance for display as dollar amount.
 * Returns null if cents is not available (so UI can show placeholder).
 */
export function formatBalance(cents) {
  if (cents == null) return null
  return `$${(cents / 100).toFixed(2)}`
}

// Alias for backwards compatibility
export const formatCredits = formatBalance

/**
 * Get the display name for the user's plan.
 * Uses tierDisplayName from server if available, otherwise capitalizes tier.
 */
export function getPlanDisplayName(cloudUser) {
  if (!cloudUser) return 'Unknown'
  // Prefer server-provided display name
  if (cloudUser.tierDisplayName) return cloudUser.tierDisplayName
  // Fallback to capitalized tier value
  const tier = cloudUser.tier
  if (!tier) return 'Unknown'
  return tier.charAt(0).toUpperCase() + tier.slice(1)
}

/**
 * Composable hook for cloud account state and methods.
 */
export function useCloudAccount() {
  return {
    // State (readonly to prevent accidental mutation)
    cloudBaseUrl: readonly(cloudBaseUrl),
    cloudUser: readonly(cloudUser),
    isCloudLoading: readonly(isCloudLoading),
    cloudError,

    // Actions
    fetchCloudAccount,
    ensureCloudBaseUrl,

    // Helpers
    formatBalance,
    formatCredits,
    getPlanDisplayName,
  }
}
