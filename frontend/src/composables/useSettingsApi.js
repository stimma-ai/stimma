/**
 * Settings API composable for managing application settings.
 */
import axios from 'axios'
import { getApiBase } from '../apiConfig'

function getAPIBase() {
  return getApiBase()
}

export function useSettingsApi() {
  /**
   * Fetch all settings for the UI.
   * Returns profile-scoped settings for the current profile and global settings.
   */
  async function fetchSettings() {
    const response = await axios.get(`${getAPIBase()}/settings`)
    return response.data
  }

  /**
   * Fetch available heroicons for the marker icon picker.
   */
  async function fetchHeroicons() {
    const response = await axios.get(`${getAPIBase()}/settings/heroicons`)
    return response.data
  }

  /**
   * Update folders for the current profile.
   * @param {Array} folders - Array of folder configurations
   */
  async function updateFolders(folders, relocation = null) {
    const payload = { folders }
    if (relocation) payload.relocation = relocation
    const response = await axios.patch(`${getAPIBase()}/settings/folders`, payload)
    return response.data
  }

  /**
   * Update markers for the current profile.
   * @param {Array} markers - Array of marker configurations
   */
  async function updateMarkers(markers) {
    const response = await axios.patch(`${getAPIBase()}/settings/markers`, { markers })
    return response.data
  }

  /**
   * Update wildcards for the current profile.
   * @param {Array} wildcards - Array of wildcard configurations {name, values}
   */
  async function updateWildcards(wildcards) {
    const response = await axios.patch(`${getAPIBase()}/settings/wildcards`, { wildcards })
    return response.data
  }

  /**
   * Update prompt segments for the current profile.
   * @param {Array} promptSegments - Array of prompt segment configurations {name, content}
   */
  async function updatePromptSegments(promptSegments) {
    const response = await axios.patch(`${getAPIBase()}/settings/prompt-segments`, { prompt_segments: promptSegments })
    return response.data
  }

  /**
   * Update a tool provider (API key, enabled, etc).
   * @param {string} providerId - The provider ID
   * @param {object} data - Update data (api_key, enabled)
   */
  async function updateToolProvider(providerId, data) {
    const response = await axios.patch(`${getAPIBase()}/settings/tool-providers/${providerId}`, data)
    return response.data
  }

  /**
   * Create a new tool provider (stdio or websocket).
   * @param {object} providerConfig - Provider configuration
   */
  async function createToolProvider(providerConfig) {
    const response = await axios.post(`${getAPIBase()}/settings/tool-providers`, providerConfig)
    return response.data
  }

  /**
   * Delete a tool provider.
   * @param {string} providerId - The provider ID to delete
   */
  async function deleteToolProvider(providerId) {
    const response = await axios.delete(`${getAPIBase()}/settings/tool-providers/${providerId}`)
    return response.data
  }

  /**
   * Update background work settings.
   * @param {object} data - Settings for face_detection, clip, and/or captioning
   */
  async function updateBackgroundWork(data) {
    const response = await axios.patch(`${getAPIBase()}/settings/background-work`, data)
    return response.data
  }

  /**
   * Update LLM settings for a specific role.
   * @param {string} role - The LLM role (agent, agent-fast)
   * @param {object} data - Update data (source, provider, model, api_key, endpoint_url, endpoint_api_key)
   */
  async function updateLlmSettings(role, data) {
    const response = await axios.patch(`${getAPIBase()}/settings/llms/${role}`, data)
    return response.data
  }

  /**
   * Fetch cloud LLM availability and usage status.
   */
  async function fetchCloudLlmStatus() {
    const response = await axios.get(`${getAPIBase()}/cloud/llm/status`)
    return response.data
  }

  /**
   * Create a new profile.
   * @param {string} name - Display name for the profile
   */
  async function createProfile(name) {
    const response = await axios.post(`${getAPIBase()}/settings/profiles`, { name })
    return response.data
  }

  /**
   * Delete a profile.
   * @param {string} profileId - The profile ID to delete
   */
  async function deleteProfile(profileId) {
    const response = await axios.delete(`${getAPIBase()}/settings/profiles/${profileId}`)
    return response.data
  }

  /**
   * Rename a profile.
   * @param {string} profileId - The profile ID to rename
   * @param {string} newName - The new display name
   */
  async function renameProfile(profileId, newName) {
    const response = await axios.patch(`${getAPIBase()}/settings/profiles/${profileId}`, { name: newName })
    return response.data
  }

  /**
   * Trigger a folder rescan.
   */
  async function rescanFolders() {
    const response = await axios.post(`${getAPIBase()}/rescan`)
    return response.data
  }

  /** Run a read-only foreign-key analysis for the current profile. */
  async function analyzeDatabaseMaintenance() {
    const response = await axios.get(`${getAPIBase()}/settings/database/maintenance/analyze`)
    return response.data
  }

  /** Explicitly repair safe foreign-key debris for the current profile. */
  async function cleanupDatabaseMaintenance() {
    const response = await axios.post(`${getAPIBase()}/settings/database/maintenance/cleanup`, { confirm: true })
    return response.data
  }

  /**
   * Update developer mode setting.
   * @param {boolean} enabled - Whether developer mode should be enabled
   */
  async function updateDeveloperMode(enabled) {
    const response = await axios.patch(`${getAPIBase()}/settings/developer-mode`, { enabled })
    return response.data
  }

  /**
   * Dev-only: force FFmpeg to appear missing (or restore real detection).
   * @param {boolean} enabled - Whether to force FFmpeg/ffprobe to appear missing
   */
  async function updateDebugForceFfmpegMissing(enabled) {
    const response = await axios.patch(`${getAPIBase()}/settings/debug-force-ffmpeg-missing`, { enabled })
    return response.data
  }

  /**
   * Force an immediate FFmpeg availability recheck and broadcast the result.
   */
  async function recheckFfmpeg() {
    const response = await axios.post(`${getAPIBase()}/processing/recheck-ffmpeg`)
    return response.data
  }

  /**
   * Update theme setting.
   * @param {string} theme - Theme preference (light, dark, system)
   */
  async function updateTheme(theme) {
    const response = await axios.patch(`${getAPIBase()}/settings/theme`, { theme })
    return response.data
  }

  /**
   * Fetch request latency percentile metrics from admin diagnostics.
   * @param {Object} params - Query params ({ sort_by, limit })
   */
  async function fetchRequestMetrics(params = {}) {
    const response = await axios.get(`${getAPIBase()}/admin/request-metrics`, { params })
    return response.data
  }

  /**
   * Reset in-memory request metrics windows.
   */
  async function resetRequestMetrics() {
    const response = await axios.post(`${getAPIBase()}/admin/request-metrics/reset`)
    return response.data
  }

  return {
    fetchSettings,
    fetchHeroicons,
    updateFolders,
    updateMarkers,
    updateWildcards,
    updatePromptSegments,
    updateToolProvider,
    createToolProvider,
    deleteToolProvider,
    updateBackgroundWork,
    updateLlmSettings,
    fetchCloudLlmStatus,
    createProfile,
    deleteProfile,
    renameProfile,
    rescanFolders,
    analyzeDatabaseMaintenance,
    cleanupDatabaseMaintenance,
    updateDeveloperMode,
    updateDebugForceFfmpegMissing,
    recheckFfmpeg,
    updateTheme,
    fetchRequestMetrics,
    resetRequestMetrics,
  }
}
