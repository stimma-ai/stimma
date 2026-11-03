import { computed, ref, readonly } from 'vue'
import { getCurrentProfileId } from './useProfile'
import { makeProfileKey } from '../utils/storageKeys'
import { syncedStorage } from '../utils/workspaceStore'

const STORAGE_PART = 'tool_auto_delete_duration'
const DEFAULT_DURATION = 'never'
const VALID_DURATIONS = new Set([
  'never',
  '1m',
  '5m',
  '30m',
  '1h',
  '2h',
  '4h',
  '6h',
  '8h',
  '12h',
  '24h',
  '3d',
  '7d',
  '30d',
  '90d',
])

function normalizeDuration(duration: unknown): string {
  if (typeof duration !== 'string') return DEFAULT_DURATION
  return VALID_DURATIONS.has(duration) ? duration : DEFAULT_DURATION
}

const autoDeleteDurationState = ref<string>(DEFAULT_DURATION)

// Storage key the in-memory value was loaded from. Null until a load has run.
// The key depends on the current profile and on the bundle/sandbox prefix,
// neither of which is resolved at module-import time: in the desktop app the
// window's pinned profile arrives from the Rust window registry after boot,
// and that path sets the profile without dispatching 'profile-changed'. So the
// value is loaded lazily and reloaded whenever the resolved key changes.
let loadedKey: string | null = null

function getStableProfileKey(): string {
  return makeProfileKey(STORAGE_PART)
}

function ensureLoaded(): void {
  if (loadedKey !== null && loadedKey === getStableProfileKey()) return
  loadDuration()
}

function findLegacyKey(profileId: string): string | null {
  const suffix = `_${profileId}_${STORAGE_PART}`
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (!key) continue
    if (key.startsWith('stimma') && key.endsWith(suffix)) {
      return key
    }
  }
  return null
}

function saveDuration(duration: string): void {
  // Without a resolved profile the key would be scoped to `null` and no real
  // profile would ever read it back.
  if (!getCurrentProfileId()) return
  try {
    const key = getStableProfileKey()
    const normalized = normalizeDuration(duration)
    syncedStorage.setItem(key, normalized)
    loadedKey = key
  } catch (err) {
    console.error('Failed to save tool auto-delete duration:', err)
  }
}

function setAutoDeleteDuration(duration: string): void {
  const normalized = normalizeDuration(duration)
  autoDeleteDurationState.value = normalized
  saveDuration(normalized)
}

function loadDuration(): void {
  try {
    const profileId = getCurrentProfileId()
    const stableKey = getStableProfileKey()
    loadedKey = stableKey
    const stableValue = syncedStorage.getItem(stableKey)
    if (stableValue !== null) {
      const normalized = normalizeDuration(stableValue)
      autoDeleteDurationState.value = normalized
      return
    }

    // Migrate from legacy modifier/account-scoped keys if present.
    const legacyKey = findLegacyKey(profileId)
    if (legacyKey) {
      const legacyValue = syncedStorage.getItem(legacyKey)
      const normalized = normalizeDuration(legacyValue)
      autoDeleteDurationState.value = normalized
      syncedStorage.setItem(stableKey, normalized)
      return
    }

    autoDeleteDurationState.value = DEFAULT_DURATION
  } catch (err) {
    console.error('Failed to load tool auto-delete duration:', err)
    autoDeleteDurationState.value = DEFAULT_DURATION
  }
}

const autoDeleteDuration = computed<string>({
  get: () => autoDeleteDurationState.value,
  set: (value) => {
    setAutoDeleteDuration(value)
  }
})

if (typeof window !== 'undefined') {
  window.addEventListener('profile-changed', loadDuration)
  // The bundle/sandbox prefix is only correct once settings land.
  window.addEventListener('settings-loaded', ensureLoaded)
}

export function useToolAutoDeleteDuration() {
  ensureLoaded()
  return {
    autoDeleteDuration,
    autoDeleteDurationReadonly: readonly(autoDeleteDurationState),
    setAutoDeleteDuration,
    reload: loadDuration
  }
}

export { setAutoDeleteDuration as setToolAutoDeleteDuration }
