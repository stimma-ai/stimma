/**
 * Account-events propagation (frontend half of the cloud push channel).
 *
 * The backend holds a persistent WebSocket to Stimma Cloud and, on any
 * account change (tier, subscription, balance), re-fetches account state and
 * broadcasts over the app websocket:
 *  - `account_updated`   — fresh account payload; refresh dependent state
 *  - `subscription_activated` — unsubscribed -> subscribed transition
 *
 * Refreshes here are data-only and quiet: shared reactive stores update in
 * place, no view reloads.
 */
import { ref, readonly } from 'vue'
import { useWebSocket } from './useWebSocket'
import { applyCloudAccount } from './useCloudAccount'
import { refreshAvailableModels } from './useAvailableModels'
import { useReadiness } from './useReadiness'
import { isTauri } from '../apiConfig'

const celebration = ref(null) // { tier, tierDisplayName } | null

let initialized = false

export function initAccountEvents() {
  if (initialized) return
  initialized = true

  const { on } = useWebSocket()

  on('account_updated', async (data) => {
    applyCloudAccount(data)
    refreshAvailableModels()
    await useReadiness().refreshReadiness()
  })

  on('subscription_activated', async (data) => {
    celebration.value = {
      tier: data?.tier || null,
      tierDisplayName: data?.tierDisplayName || null,
    }
    await foregroundAppWindow()
  })
}

async function foregroundAppWindow() {
  if (!isTauri()) return
  try {
    const { getCurrentWindow } = await import('@tauri-apps/api/window')
    const win = getCurrentWindow()
    await win.show()
    await win.unminimize()
    await win.setFocus()
  } catch (e) {
    console.warn('[useAccountEvents] failed to foreground window:', e)
  }
}

function dismissCelebration() {
  celebration.value = null
}

export function useSubscriptionCelebration() {
  return {
    celebration: readonly(celebration),
    dismissCelebration,
  }
}
