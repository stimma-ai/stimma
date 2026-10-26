import { computed, ref } from 'vue'
import { mobilePlatform, mobileNative } from '../desktop/mobileNative.ts'
import { createTransportRecovery } from '../utils/transportRecovery.js'

export const mobileRecoveryEnabled = Boolean(mobilePlatform())
/** null while connected; 'reconnecting' or 'unavailable' while known content may be out of date. */
export const mobileRecoveryStatus = ref(null)
export const mobileRecoveryVisible = computed(() => mobileRecoveryStatus.value !== null)

const recovery = createTransportRecovery({ changed: state => { mobileRecoveryStatus.value = state.status } })

export function setMobileSocketReady(ready) {
  if (!mobileRecoveryEnabled) return
  recovery.socket(ready)
}
export function waitForMobileTransport(signal) {
  return mobileRecoveryEnabled ? recovery.wait(signal) : Promise.resolve()
}
/** Whether the app socket may connect now. Always true off the phone shells. */
export function mobileTransportAdmitsSocket() {
  return !mobileRecoveryEnabled || recovery.admitsSocket
}
/** The current disruption epoch: a socket opened in an earlier epoch may be stale. */
export function mobileTransportEpoch() {
  return mobileRecoveryEnabled ? recovery.epoch : 0
}
/** Runs whenever the app socket may connect again after it could not. */
export function onMobileTransportAdmit(listener) {
  return mobileRecoveryEnabled ? recovery.onAdmit(listener) : () => {}
}
/** Runs once each time the connection recovers from a disruption. */
export function onMobileTransportReady(listener) {
  return mobileRecoveryEnabled ? recovery.onReady(listener) : () => {}
}

if (mobileRecoveryEnabled) {
  let resumeEpoch = 0
  let suspended = false
  const suspend = () => {
    if (suspended) return
    resumeEpoch++
    suspended = true
    recovery.suspend()
  }
  const resume = async () => {
    if (!suspended || document.visibilityState === 'hidden') return
    suspended = false
    const epoch = ++resumeEpoch
    recovery.resume()
    // Shells that publish recovery phases report the generation in progress;
    // older shells and live dev connections only say whether HTTP is ready.
    try {
      const state = await mobileNative('getState')
      if (suspended || epoch !== resumeEpoch) return
      if (state?.recovery) { recovery.nativeState(state.recovery); return }
      recovery.legacyConnection(state.connectionState)
      if (state.connectionState === 'ready') recovery.legacyResumed()
    } catch { /* Native recovery will signal readiness. */ }
  }
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') suspend()
    else void resume()
  })
  window.addEventListener('stimma:app-active', event => { if (event.detail) void resume(); else suspend() })
  window.addEventListener('stimma:transport-state', event => recovery.nativeState(event.detail))
  window.addEventListener('stimma:connection-state', event => recovery.legacyConnection(event.detail))
  window.addEventListener('stimma:transport-resumed', () => recovery.legacyResumed())
  window.addEventListener('profile-will-change', () => recovery.invalidate())
  window.addEventListener('stimma:workspace-changing', () => recovery.invalidate())
  // Learn the shell's recovery generation before the first disruption.
  void mobileNative('getState').then(state => { if (state?.recovery) recovery.nativeState(state.recovery) }, () => {})
}
