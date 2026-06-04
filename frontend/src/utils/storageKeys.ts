/**
 * Centralized localStorage key generation utility.
 *
 * Uses the database GUID to ensure keys are globally unique across reinstalls,
 * profile changes, and database resets. This prevents stale data from being
 * loaded when IDs (like tool_id) are reused in a new database.
 *
 * Also uses app modifier (e.g., "dev") to separate dev/prod localStorage.
 *
 * Key format: stimma_{modifier?}_{dbGuid}_{...parts}
 */
import { getCurrentDbGuid, getCurrentProfileId } from '../composables/useProfile'
import { getAppModifier } from '../appConfig'

/**
 * Get the base prefix for all storage keys.
 * Returns "stimma" for prod, "stimma_dev" for dev environment, etc.
 */
function getBasePrefix(): string {
  const modifier = getAppModifier()
  return modifier ? `stimma_${modifier}` : 'stimma'
}

/**
 * Create a localStorage key that includes the current database GUID.
 *
 * Use this for keys that reference database IDs (tool_id, media_id, etc.)
 * to ensure old data doesn't resurface after database reset/reinstall.
 *
 * @param parts - Key parts to join (e.g., 'tool', toolId, 'state')
 * @returns Namespaced key like 'stimma_abc123db_tool_5_state'
 */
export function makeStorageKey(...parts: (string | number)[]): string {
  const prefix = getBasePrefix()
  const dbGuid = getCurrentDbGuid()
  if (!dbGuid) {
    // Fallback to profile ID if db_guid not yet loaded (shouldn't happen in practice)
    const profileId = getCurrentProfileId()
    return `${prefix}_${profileId}_${parts.join('_')}`
  }
  return `${prefix}_${dbGuid}_${parts.join('_')}`
}

/**
 * Create a profile-scoped key (uses profile ID, not db_guid).
 *
 * Use this for settings that should persist across database resets
 * but be separate per profile (e.g., UI preferences, filter states).
 *
 * @param parts - Key parts to join
 * @returns Namespaced key like 'stimma_myprofile_slideshow_settings'
 */
export function makeProfileKey(...parts: (string | number)[]): string {
  const prefix = getBasePrefix()
  const profileId = getCurrentProfileId()
  return `${prefix}_${profileId}_${parts.join('_')}`
}

/**
 * Create a global key (not profile-specific).
 *
 * Use sparingly - only for truly global settings like theme preference.
 *
 * @param parts - Key parts to join
 * @returns Namespaced key like 'stimma_global_theme'
 */
export function makeGlobalKey(...parts: (string | number)[]): string {
  const prefix = getBasePrefix()
  return `${prefix}_global_${parts.join('_')}`
}

/**
 * Create a tool-specific DB-scoped key (includes db_guid).
 *
 * Use for transient data referencing DB entities (masks, pending generations, video images).
 */
export function makeToolDbKey(fullToolId: string, ...parts: (string | number)[]): string {
  const safeToolId = fullToolId.replace(/:/g, '_')
  return makeStorageKey('tool', safeToolId, ...parts)
}

/**
 * Create a tool-specific profile-scoped key (includes profile ID).
 *
 * Use for persistent user preferences (tool state, presets, collapsed groups).
 */
export function makeToolProfileKey(fullToolId: string, ...parts: (string | number)[]): string {
  const safeToolId = fullToolId.replace(/:/g, '_')
  return makeProfileKey('tool', safeToolId, ...parts)
}
