import axios from 'axios'
import { computed, ref, shallowRef } from 'vue'
import { getVersion } from '@tauri-apps/api/app'
import { isTauri, getApiBase } from '../apiConfig'
import { useTelemetry } from './useTelemetry'

const { track } = useTelemetry()

type LegacyUpdatePolicy = 'auto_minor_prompt_major' | 'auto_all'
type UpdatePolicy = 'prompt_all'

interface StoredPolicy {
  mode?: UpdatePolicy | LegacyUpdatePolicy
}

interface StoredSkipVersion {
  version?: string
}

interface TauriUpdate {
  version: string
  body?: string
  date?: string
  downloadAndInstall: (onEvent?: (progress: any) => void) => Promise<void>
}

const POLICY_PREF_KEY = 'app_updates_policy'
const SKIP_PREF_KEY = 'app_updates_skip_version'
const LAST_CHECK_PREF_KEY = 'app_updates_last_checked_at'

const policy = ref<UpdatePolicy>('prompt_all')
const loadedPrefs = ref(false)
const isChecking = ref(false)
const isDownloading = ref(false)
const lastCheckedAt = ref<string | null>(null)
const availableUpdate = shallowRef<TauriUpdate | null>(null)
const downloadedVersion = ref<string | null>(null)
const currentVersion = ref('0.0.0')

async function getPreference<T>(key: string): Promise<T | null> {
  try {
    const response = await axios.get(`${getApiBase()}/preferences/${key}`)
    return response.data?.value ?? null
  } catch (error: any) {
    if (error?.response?.status === 404) return null
    throw error
  }
}

async function setPreference(key: string, value: Record<string, any>): Promise<void> {
  await axios.put(`${getApiBase()}/preferences/${key}`, value)
}

async function loadPreferences(): Promise<void> {
  if (!isTauri() || loadedPrefs.value) return
  try {
    currentVersion.value = await getVersion()
  } catch {
    currentVersion.value = '0.0.0'
  }

  try {
    const [storedPolicy, storedSkip, storedLastChecked] = await Promise.all([
      getPreference<StoredPolicy>(POLICY_PREF_KEY),
      getPreference<StoredSkipVersion>(SKIP_PREF_KEY),
      getPreference<{ checked_at?: string }>(LAST_CHECK_PREF_KEY)
    ])

    if (storedPolicy?.mode === 'prompt_all') {
      policy.value = storedPolicy.mode
    } else if (storedPolicy?.mode) {
      policy.value = 'prompt_all'
      await setPreference(POLICY_PREF_KEY, { mode: 'prompt_all' })
    }
    if (storedSkip?.version) {
      downloadedVersion.value = storedSkip.version
    }
    if (storedLastChecked?.checked_at) {
      lastCheckedAt.value = storedLastChecked.checked_at
    }
  } catch (error) {
    console.error('[updater] Failed to load preferences:', error)
  } finally {
    loadedPrefs.value = true
  }
}

async function setUpdatePolicy(nextPolicy: UpdatePolicy): Promise<void> {
  policy.value = nextPolicy
  await setPreference(POLICY_PREF_KEY, { mode: nextPolicy })
}

async function saveLastCheckedAt(): Promise<void> {
  const checkedAt = new Date().toISOString()
  lastCheckedAt.value = checkedAt
  await setPreference(LAST_CHECK_PREF_KEY, { checked_at: checkedAt })
}

async function checkForUpdates(trigger: 'manual' | 'auto' = 'auto'): Promise<void> {
  if (!isTauri()) return
  await loadPreferences()
  if (isChecking.value) return

  isChecking.value = true
  try {
    const updater = await import('@tauri-apps/plugin-updater')
    const update = (await updater.check()) as TauriUpdate | null
    await saveLastCheckedAt()

    track('update_checked', { trigger })

    if (!update) {
      availableUpdate.value = null
      return
    }

    track('update_available', { version: update.version })

    if (downloadedVersion.value && downloadedVersion.value === update.version) {
      return
    }

    availableUpdate.value = update
  } catch (error) {
    console.error('[updater] Failed checking for updates:', error)
  } finally {
    isChecking.value = false
  }
}

async function downloadAndInstallUpdate(): Promise<void> {
  if (!availableUpdate.value || isDownloading.value) return

  const version = availableUpdate.value.version
  isDownloading.value = true
  try {
    await availableUpdate.value.downloadAndInstall()
    track('update_installed', { version })
    await relaunchApp()
  } catch (error) {
    console.error('[updater] Download/install failed:', error)
    isDownloading.value = false
  }
}

async function relaunchApp(): Promise<void> {
  try {
    const { relaunch } = await import('@tauri-apps/plugin-process')
    await relaunch()
  } catch (error) {
    console.error('[updater] Failed to relaunch app:', error)
  }
}

const channel = computed(() => (import.meta.env.VITE_STIMMA_RELEASE_CHANNEL || 'sandbox').toLowerCase())
const updateEndpoint = computed(() => import.meta.env.VITE_STIMMA_UPDATE_ENDPOINT || '')
const updatesEnabled = computed(() => isTauri() && Boolean(updateEndpoint.value))
const hasUpdate = computed(() => availableUpdate.value !== null)

export function useAppUpdater() {
  return {
    policy,
    channel,
    updateEndpoint,
    updatesEnabled,
    loadedPrefs,
    isChecking,
    isDownloading,
    currentVersion,
    lastCheckedAt,
    availableUpdate,
    hasUpdate,
    loadPreferences,
    setUpdatePolicy,
    checkForUpdates,
    downloadAndInstallUpdate,
  }
}
