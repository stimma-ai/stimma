import { computed, ref } from 'vue'
import { isMobileShell } from '../desktop/mobileBridge.ts'

// The native signal also covers interruptions where WebKit visibility lags.
const mobile = isMobileShell()
const visible = ref(!mobile || document.visibilityState !== 'hidden')
const nativeActive = ref(true)
const connected = ref(true)
const needsUserPlay = ref(!visible.value)
export const mobileForeground = computed(() => !mobile || (visible.value && nativeActive.value))
export const mobileAdvanceReady = computed(() => mobileForeground.value && connected.value)
export const mobileAutoplayAllowed = computed(() => mobileForeground.value && !needsUserPlay.value)

export function allowMobilePlayback() {
  if (mobileForeground.value) needsUserPlay.value = false
}

function pauseMedia() {
  needsUserPlay.value = true
  document.querySelectorAll('audio, video').forEach(element => element.pause())
}

if (mobile) {
  document.addEventListener('visibilitychange', () => {
    visible.value = document.visibilityState !== 'hidden'
    if (!visible.value) pauseMedia()
  })
  window.addEventListener('stimma:app-active', event => {
    nativeActive.value = event.detail === true
    if (!nativeActive.value) pauseMedia()
  })
  window.addEventListener('stimma:connection-state', event => {
    connected.value = event.detail === 'ready'
  })
  // Catch delayed autoplay/canplay callbacks, including players outside the
  // managed registry. A return to the foreground does not grant play intent.
  document.addEventListener('play', event => {
    if (!(event.target instanceof HTMLMediaElement)) return
    if (mobileForeground.value && navigator.userActivation?.isActive) allowMobilePlayback()
    if (!mobileAutoplayAllowed.value) event.target.pause()
  }, true)
}
