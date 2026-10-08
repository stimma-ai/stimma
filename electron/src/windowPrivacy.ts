import type { BrowserWindow, PowerMonitor } from 'electron'

/** Forward native lifecycle signals even when the page remains focused. */
export function installWindowPrivacyLifecycle(win: BrowserWindow, powerMonitor: PowerMonitor): () => void {
  let suspended = false
  let screenLocked = false
  // Sleep/system lock can leave a focused window without a DOM blur. Cover
  // before suspension instead of waiting for the renderer's first wake frame.
  const inactive = () => {
    if (!win.isDestroyed()) win.webContents.send('stimma:app-active', false)
  }
  const active = () => {
    if (!win.isDestroyed()) win.webContents.send('stimma:app-active', !suspended && !screenLocked && win.isVisible() && !win.isMinimized())
  }
  const suspend = () => { suspended = true; inactive() }
  const lock = () => { screenLocked = true; inactive() }
  const resume = () => { suspended = false; active() }
  const unlock = () => { screenLocked = false; active() }
  // Focus is independent of privacy: visible desktop windows remain readable.
  win.on('hide', inactive)
  win.on('minimize', inactive)
  win.on('show', active)
  win.on('restore', active)
  win.on('focus', active)
  powerMonitor.on('suspend', suspend)
  powerMonitor.on('lock-screen', lock)
  powerMonitor.on('resume', resume)
  powerMonitor.on('unlock-screen', unlock)
  win.on('closed', () => {
    powerMonitor.removeListener('suspend', suspend)
    powerMonitor.removeListener('lock-screen', lock)
    powerMonitor.removeListener('resume', resume)
    powerMonitor.removeListener('unlock-screen', unlock)
  })

  return active
}
