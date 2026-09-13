import { ref } from 'vue'
import { mobilePlatform, mobileNative } from '../desktop/mobileNative.ts'
import { createRecoveryWindow } from '../utils/recoveryWindow.js'

export const mobileRecoveryEnabled = Boolean(mobilePlatform())
export const mobileRecoveryVisible = ref(false)
let httpReady = true, socketReady = true, suspended = false
let resumeEpoch = 0
const requests = createRecoveryWindow()
const presentation = createRecoveryWindow({ changed: state => { mobileRecoveryVisible.value = state.visible } })
function update() {
  if (suspended) return
  requests.setReady(httpReady)
  presentation.setReady(httpReady && socketReady)
}
export function setMobileSocketReady(ready) {
  if (!mobileRecoveryEnabled) return
  socketReady = ready
  update()
}
export function waitForMobileTransport(signal) {
  return mobileRecoveryEnabled ? requests.wait(signal) : Promise.resolve()
}

if (mobileRecoveryEnabled) {
  const suspend = () => {
    if (suspended) return
    resumeEpoch++
    suspended = true; httpReady = false; socketReady = false
    requests.suspend(); presentation.suspend()
  }
  const resume = async () => {
    if (!suspended || document.visibilityState === 'hidden') return
    suspended = false
    const epoch = ++resumeEpoch
    requests.resume(); presentation.resume()
    // Older shells and live dev connections also use this UI package. Read
    // their real HTTP state; native recovery events finish slower connections.
    try {
      const state = await mobileNative('getState')
      if (suspended || epoch !== resumeEpoch) return
      httpReady = state.connectionState === 'ready'
      update()
      if (httpReady) window.dispatchEvent(new Event('stimma:transport-resumed'))
    } catch { /* Native recovery will signal readiness. */ }
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') suspend()
    else void resume()
  })
  window.addEventListener('stimma:app-active', event => { if (event.detail) void resume(); else suspend() })
  window.addEventListener('stimma:connection-state', event => {
    httpReady = event.detail === 'ready'
    update()
  })
  window.addEventListener('stimma:transport-resumed', () => { httpReady = true; update() })
  window.addEventListener('profile-will-change', () => requests.invalidate())
  window.addEventListener('stimma:workspace-changing', () => requests.invalidate())
}
