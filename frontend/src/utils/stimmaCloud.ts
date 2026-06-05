/**
 * Stimma Cloud branding utilities
 *
 * Centralized helpers for identifying and styling Stimma Cloud content.
 */

export const STIMMA_CLOUD_PROVIDER_ID = 'stimma-cloud'

/**
 * Check if a tool/provider is from Stimma Cloud
 */
export function isStimmaCloudTool(tool: { provider_id?: string } | null | undefined): boolean {
  return tool?.provider_id === STIMMA_CLOUD_PROVIDER_ID
}
