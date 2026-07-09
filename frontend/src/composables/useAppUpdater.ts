import axios from 'axios'
import { computed, ref, shallowRef } from 'vue'
import { getVersion } from '@tauri-apps/api/app'
import { isTauri, getApiBase } from '../apiConfig'
import { useTelemetry } from './useTelemetry'

const { track } = useTelemetry()

type LegacyUpdatePolicy = 'auto_minor_prompt_major' | 'auto_all'
// automatic: download + install in the background, apply on next launch.
// prompt_all: check + notify, user chooses when to install.
// manual: no scheduled checks; only the explicit "Check now" button.
type UpdatePolicy = 'automatic' | 'prompt_all' | 'manual'

const UPDATE_POLICIES: UpdatePolicy[] = ['automatic', 'prompt_all', 'manual']

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
  download: (onEvent?: (progress: any) => void) => Promise<void>
  install: () => Promise<void>
  downloadAndInstall: (onEvent?: (progress: any) => void) => Promise<void>
}

// How a staged update is applied. On macOS / Linux-AppImage the package is
// swapped in place and takes effect on the next launch, so we just relaunch.
// On Windows the NSIS installer must run with the app closed, so applying =
// running install() (which tears down + relaunches the app).
type ApplyAction = 'relaunch' | 'install'

// Coarse platform check. WebView2 (Windows) always reports "Windows" in the UA;
// WKWebView (macOS) and WebKitGTK (Linux) do not. Good enough to branch install
// behavior, and avoids pulling in @tauri-apps/plugin-os.
function isWindowsPlatform(): boolean {
  return typeof navigator !== 'undefined' && /Windows/i.test(navigator.userAgent)
}

const POLICY_PREF_KEY = 'app_updates_policy'
const SKIP_PREF_KEY = 'app_updates_skip_version'
const LAST_CHECK_PREF_KEY = 'app_updates_last_checked_at'

const policy = ref<UpdatePolicy>('automatic')
const loadedPrefs = ref(false)
const isChecking = ref(false)
const isDownloading = ref(false)
const lastCheckedAt = ref<string | null>(null)
const availableUpdate = shallowRef<TauriUpdate | null>(null)
const downloadedVersion = ref<string | null>(null)
// Set once an update has been downloaded in the background (automatic mode) and
// is waiting to be applied. On mac/linux it is already installed and only needs
// a relaunch; on Windows the installer still has to run (see pendingApply).
const stagedVersion = ref<string | null>(null)
const pendingApply = ref<ApplyAction | null>(null)
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

    const storedMode = storedPolicy?.mode
    if (storedMode && UPDATE_POLICIES.includes(storedMode as UpdatePolicy)) {
      policy.value = storedMode as UpdatePolicy
    } else if (storedMode) {
      // Migrate a legacy policy to the closest current one.
      const mapped: UpdatePolicy =
        storedMode === 'auto_all' || storedMode === 'auto_minor_prompt_major'
          ? 'automatic'
          : 'prompt_all'
      policy.value = mapped
      await setPreference(POLICY_PREF_KEY, { mode: mapped })
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
  const previous = policy.value
  policy.value = nextPolicy
  await setPreference(POLICY_PREF_KEY, { mode: nextPolicy })

  // Switching into a checking mode should take effect immediately rather than
  // waiting for the next scheduled tick / app restart.
  if (nextPolicy !== 'manual' && previous !== nextPolicy) {
    void checkForUpdates('auto')
  }
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
    // A newer build superseded whatever we had staged — discard it and re-stage
    // the new one (frees the old resource on Windows; re-installs over it on
    // mac/linux).
    if (stagedVersion.value && stagedVersion.value !== update.version) {
      await resetStaged()
    }
    // This exact version is already staged and waiting on a restart.
    if (stagedVersion.value === update.version) {
      return
    }

    availableUpdate.value = update

    // Automatic mode: stage the update. stageUpdate never tears down a running
    // session and never holds an installer in memory — see its per-platform notes.
    if (policy.value === 'automatic') {
      void stageUpdate()
    }
  } catch (error) {
    console.error('[updater] Failed checking for updates:', error)
  } finally {
    isChecking.value = false
  }
}

// Automatic mode: stage an available update without tearing down the running
// session. How we stage differs by platform, because the plugin buffers the
// whole package in process memory and can only install within the same process:
//   - macOS / Linux-AppImage: install() swaps the bundle in place and the
//     running process keeps old code until relaunch. We download + install now
//     (memory freed immediately) and apply on the next launch. Any relaunch
//     picks it up — see restartToApply / "Restart to finish".
//   - Windows: the NSIS installer must run with the app closed, and we refuse
//     to hold a ~hundreds-of-MB installer in RAM waiting for a restart. So we
//     do NOT pre-download; we just surface a one-click "Restart to update" and
//     download + install at that moment (see restartToApply). This also means
//     no repeated background downloads across launches.
async function stageUpdate(): Promise<void> {
  if (!availableUpdate.value || isDownloading.value || stagedVersion.value) return

  const update = availableUpdate.value
  const version = update.version

  if (isWindowsPlatform()) {
    // Nothing downloaded yet — keep the Update handle so restartToApply can
    // download + install it on demand.
    stagedVersion.value = version
    pendingApply.value = 'install'
    track('update_staged', { version, mode: 'automatic' })
    return
  }

  isDownloading.value = true
  try {
    await update.download()
    await update.install()
    stagedVersion.value = version
    pendingApply.value = 'relaunch'
    availableUpdate.value = null
    track('update_installed', { version, mode: 'automatic' })
    // Free the Rust-side resource; we no longer need the buffered package.
    try { await update.close() } catch { /* best-effort */ }
  } catch (error) {
    console.error('[updater] Background staging failed:', error)
  } finally {
    isDownloading.value = false
  }
}

// Drop a staged update (superseded or being replaced) and free its resource.
async function resetStaged(): Promise<void> {
  if (availableUpdate.value) {
    try { await availableUpdate.value.close() } catch { /* best-effort */ }
  }
  availableUpdate.value = null
  stagedVersion.value = null
  pendingApply.value = null
}

async function downloadAndInstallUpdate(): Promise<void> {
  if (!availableUpdate.value || isDownloading.value) return

  const version = availableUpdate.value.version
  isDownloading.value = true
  try {
    await availableUpdate.value.downloadAndInstall()
    track('update_installed', { version, mode: 'prompt' })
    await relaunchApp()
  } catch (error) {
    console.error('[updater] Download/install failed:', error)
    isDownloading.value = false
  }
}

// Apply a staged update. On Windows this is where the installer actually runs:
// we download + install now (bytes live only for the seconds of install), the
// app closes, and the passive installer swaps files and relaunches. On mac/linux
// the package is already installed, so we just relaunch into it.
async function restartToApply(): Promise<void> {
  if (!stagedVersion.value || isDownloading.value) return

  if (pendingApply.value === 'install' && availableUpdate.value) {
    const version = stagedVersion.value
    isDownloading.value = true
    try {
      await availableUpdate.value.downloadAndInstall()
      track('update_installed', { version, mode: 'automatic' })
    } catch (error) {
      // Leave the staged state intact so the button stays actionable.
      console.error('[updater] Download/install failed:', error)
      isDownloading.value = false
      return
    }
    // The passive installer relaunches; relaunch() is a fallback for the rare
    // path where downloadAndInstall() returns without exiting.
    await relaunchApp()
    return
  }

  await relaunchApp()
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
const pendingRestart = computed(() => stagedVersion.value !== null)

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
    stagedVersion,
    pendingRestart,
    pendingApply,
    loadPreferences,
    setUpdatePolicy,
    checkForUpdates,
    downloadAndInstallUpdate,
    restartToApply,
  }
}
