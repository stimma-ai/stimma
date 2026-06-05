import { computed, ref, readonly } from 'vue'
import { getCurrentProfileId } from './useProfile'
import { makeProfileKey } from '../utils/storageKeys'

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

function getStableProfileKey(): string {
  return makeProfileKey(STORAGE_PART)
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
  try {
    const key = getStableProfileKey()
    const normalized = normalizeDuration(duration)
    localStorage.setItem(key, normalized)
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
    const stableValue = localStorage.getItem(stableKey)
    if (stableValue !== null) {
      const normalized = normalizeDuration(stableValue)
      autoDeleteDurationState.value = normalized
      return
    }

    // Migrate from legacy modifier/account-scoped keys if present.
    const legacyKey = findLegacyKey(profileId)
    if (legacyKey) {
      const legacyValue = localStorage.getItem(legacyKey)
      const normalized = normalizeDuration(legacyValue)
      autoDeleteDurationState.value = normalized
      localStorage.setItem(stableKey, normalized)
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

loadDuration()

if (typeof window !== 'undefined') {
  window.addEventListener('profile-changed', loadDuration)
}

export function useToolAutoDeleteDuration() {
  return {
    autoDeleteDuration,
    autoDeleteDurationReadonly: readonly(autoDeleteDurationState),
    setAutoDeleteDuration,
    reload: loadDuration
  }
}

export { setAutoDeleteDuration as setToolAutoDeleteDuration }
