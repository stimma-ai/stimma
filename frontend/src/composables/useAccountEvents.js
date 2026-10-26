/**
 * Account-events propagation (frontend half of the cloud push channel).
 *
 * The backend holds a persistent WebSocket to Stimma Cloud and, on any
 * account change (balance, tier), re-fetches account state and broadcasts
 * over the app websocket:
 *  - `account_updated` — fresh account payload; refresh dependent state
 *  - `balance_added`   — zero -> positive balance transition
 *
 * Refreshes here are data-only and quiet: shared reactive stores update in
 * place, no view reloads.
 */
import { ref, readonly } from 'vue'
import { useWebSocket } from './useWebSocket'
import { applyCloudAccount, fetchCloudAccount, getCloudUser } from './useCloudAccount'
import { refreshAvailableModels } from './useAvailableModels'
import { useReadiness } from './useReadiness'
import { isDesktop } from '../apiConfig'

const celebration = ref(null) // { credits } | null

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

  // Account changes pushed while the socket was down were missed; read the
  // current state once it is back. Optional: after the active screen. Only an
  // account already known is refreshed, so a signed-out app is not asked to sign in.
  on('websocket_reconnected', async () => {
    if (!getCloudUser()) return
    await fetchCloudAccount()
    refreshAvailableModels()
    await useReadiness().refreshReadiness()
  }, { optional: true })

  on('balance_added', async (data) => {
    celebration.value = {
      credits: data?.credits ?? null,
    }
    await foregroundAppWindow()
  })
}

async function foregroundAppWindow() {
  if (!isDesktop()) return
  try {
    const { desktop } = await import('../desktop')
    await desktop.focusCurrentWindow()
  } catch (e) {
    console.warn('[useAccountEvents] failed to foreground window:', e)
  }
}

function dismissCelebration() {
  celebration.value = null
}

export function useBalanceCelebration() {
  return {
    celebration: readonly(celebration),
    dismissCelebration,
  }
}
