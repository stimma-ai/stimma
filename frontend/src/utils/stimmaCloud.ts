/**
 * Stimma Cloud branding utilities
 *
 * Centralized helpers for identifying and styling Stimma Cloud content.
 */

export const STIMMA_CLOUD_PROVIDER_ID = 'stimma-cloud'
export const STIMMA_TOOL_PROVIDER_DISPLAY_NAME = 'Stimma'

type ToolProviderIdentity = {
  provider_id?: string | null
  provider_name?: string | null
}

const LEGACY_STIMMA_TOOL_PROVIDER_NAME = 'Stimma Cloud'

/**
 * Check if a tool/provider is from Stimma Cloud
 */
export function isStimmaCloudTool(tool: ToolProviderIdentity | null | undefined): boolean {
  return tool?.provider_id === STIMMA_CLOUD_PROVIDER_ID || (
    !tool?.provider_id
    && (tool?.provider_name === STIMMA_TOOL_PROVIDER_DISPLAY_NAME
      || tool?.provider_name === LEGACY_STIMMA_TOOL_PROVIDER_NAME)
  )
}

/**
 * Return the canonical user-facing name for a tool provider. The name fallback
 * keeps persisted tool metadata and old approval messages from resurfacing the
 * former Stimma Cloud provider label.
 */
export function toolProviderDisplayName(
  provider: ToolProviderIdentity | null | undefined,
  fallback = 'Provider',
): string {
  if (
    provider?.provider_id === STIMMA_CLOUD_PROVIDER_ID
    || provider?.provider_name === LEGACY_STIMMA_TOOL_PROVIDER_NAME
  ) {
    return STIMMA_TOOL_PROVIDER_DISPLAY_NAME
  }
  return provider?.provider_name || provider?.provider_id || fallback
}
