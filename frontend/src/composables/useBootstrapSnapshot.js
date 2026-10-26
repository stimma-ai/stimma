/**
 * The startup snapshots every bootstrap consumer shares, so the app asks the
 * server for its profile roster and settings once instead of once per
 * component.
 *
 * Two scopes with different privacy:
 * - The profile roster (`GET /profiles`) is per server. It is the metadata a
 *   locked window may see before unlock: names, `has_pin`, idle limits.
 * - Settings (`GET /settings`) are per server and profile and protected by
 *   the profile's PIN. They are kept in memory only, never served to another
 *   profile, and dropped on lock, profile switch, server switch and config
 *   reload. A request refused while locked is never stored.
 */
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import { createScopedSnapshot } from '../utils/scopedSnapshot.js'

// The shared roster request is bounded and aborted on expiry, so a request
// lost to a dead connection cannot keep every later reader waiting on it;
// the next reader starts a new one.
const PROFILES_REQUEST_TIMEOUT_MS = 10_000

const profiles = createScopedSnapshot(async (_scope, signal) => {
  const response = await fetch(`${getApiBase()}/profiles`, { signal })
  if (!response.ok) throw new Error(`Failed to load profiles: ${response.status}`)
  return response.json()
}, { timeoutMs: PROFILES_REQUEST_TIMEOUT_MS })

// The server refused this profile's settings (PIN required or wrong, unknown
// profile): whatever was read before is no longer authorized.
const REFUSED = new Set([400, 401, 403, 404])

const settings = createScopedSnapshot(async () => {
  const response = await axios.get(`${getApiBase()}/settings`)
  return response.data
}, { evictOnError: error => REFUSED.has(error?.response?.status) })

// Installed by useProfile (which owns profile identity and the PIN cache):
// may this window read `profileId`'s protected settings right now? It must
// apply PIN expiry synchronously, because idle timers can be suspended past
// the deadline (sleep, background) and a stored copy must not outlive it.
let settingsAccess = () => true

export function configureSettingsAccess(check) {
  settingsAccess = check
}

const serverScope = () => getApiBase()
const settingsScope = profileId => `${getApiBase()}\n${profileId ?? ''}`

/** The profile roster: `{ profiles: [...] }`. `fresh` always asks the server. */
export function readProfiles({ fresh = false, maxAgeMs } = {}) {
  return fresh ? profiles.refresh(serverScope()) : profiles.read(serverScope(), { maxAgeMs })
}

/** Settings for `profileId` (requests carry the current profile's headers). */
export function readSettings(profileId, { fresh = false, maxAgeMs } = {}) {
  const scope = settingsScope(profileId)
  let allowed
  try {
    allowed = settingsAccess(profileId)
  } catch (error) {
    return Promise.reject(error)
  }
  // Not authorized right now: neither a stored copy nor a request started
  // before is usable. Ask the server, which decides (and normally refuses).
  if (!allowed) {
    settings.invalidate(other => other !== scope)
    return settings.refresh(scope)
  }
  return fresh ? settings.refresh(scope) : settings.read(scope, { maxAgeMs })
}

export function peekProfilesSnapshot() {
  return profiles.peek(serverScope())
}

export function peekSettingsSnapshot(profileId) {
  if (profileId !== undefined) return settings.peek(settingsScope(profileId))
  // Any profile's settings: lets tests prove nothing protected survived a lock.
  const [scope] = settings.scopes()
  return scope === undefined ? null : settings.peek(scope)
}

/** Drop protected settings, optionally keeping one profile's. */
export function invalidateSettingsSnapshots(keepProfileId) {
  const keep = keepProfileId == null ? null : settingsScope(keepProfileId)
  settings.invalidate(scope => scope === keep)
}

export function invalidateBootstrapSnapshots() {
  profiles.invalidate()
  settings.invalidate()
}

if (typeof window !== 'undefined') {
  // PIN-protected content never outlives a lock or belongs to another profile.
  window.addEventListener('pin-auto-locked', () => invalidateSettingsSnapshots())
  window.addEventListener('profile-will-change', () => invalidateSettingsSnapshots())
  // Config hot-reload: settings may have changed with the roster.
  window.addEventListener('profiles-changed', () => invalidateSettingsSnapshots())
  // A different server is a different scope entirely.
  window.addEventListener('stimma:workspace-changing', invalidateBootstrapSnapshots)
}
