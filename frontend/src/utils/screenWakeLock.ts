/**
 * Keep the display awake (no screensaver, no dimming) while something is on
 * screen to watch, the way a video player does. Uses the Screen Wake Lock API,
 * which Electron maps to the OS screensaver inhibitor where the platform
 * offers one. Browsers drop the lock whenever the page is
 * hidden, so it is taken again each time the page becomes visible.
 * Unsupported or insecure contexts simply do nothing.
 */
import { desktop } from '../desktop'

type Sentinel = { release(): Promise<void>; addEventListener(type: 'release', fn: () => void): void }
type WakeLockApi = { request(type: 'screen'): Promise<Sentinel> }

export function createScreenWakeLock(): (active: boolean) => void {
  let wanted = false
  let sentinel: Sentinel | null = null
  let requesting = false

  async function acquire() {
    const api = (typeof navigator !== 'undefined' ? (navigator as Navigator & { wakeLock?: WakeLockApi }).wakeLock : undefined)
    if (!api || !wanted || sentinel || requesting || document.visibilityState !== 'visible') return
    requesting = true
    try {
      const lock = await api.request('screen')
      if (!wanted) {
        void lock.release().catch(() => {})
        return
      }
      sentinel = lock
      lock.addEventListener('release', () => {
        if (sentinel === lock) sentinel = null
      })
    } catch {
      // Denied, unsupported, or the page went hidden mid-request.
    } finally {
      requesting = false
    }
  }

  function onVisibility() {
    void acquire()
  }

  return (active: boolean) => {
    if (active === wanted) return
    wanted = active
    // Where the wake lock can't reach the OS (Hyprland), the desktop shell
    // marks the window itself. Older shells lack the method.
    void desktop.setKeepScreenAwake?.(active)?.catch(() => {})
    if (active) {
      document.addEventListener('visibilitychange', onVisibility)
      void acquire()
    } else {
      document.removeEventListener('visibilitychange', onVisibility)
      const lock = sentinel
      sentinel = null
      void lock?.release().catch(() => {})
    }
  }
}
