import type { BrowserWindow, PowerMonitor } from 'electron'

/** Forward native lifecycle signals even when the page remains focused. */
export function installWindowPrivacyLifecycle(win: BrowserWindow, powerMonitor: PowerMonitor): () => void {
  // Sleep/system lock can leave a focused window without a DOM blur. Cover
  // before suspension instead of waiting for the renderer's first wake frame.
  const inactive = () => {
    if (!win.isDestroyed()) win.webContents.send('stimma:app-active', false)
  }
  const active = () => {
    if (!win.isDestroyed()) win.webContents.send('stimma:app-active', win.isFocused() && win.isVisible() && !win.isMinimized())
  }
  win.on('blur', inactive)
  win.on('hide', inactive)
  win.on('minimize', inactive)
  win.on('focus', active)
  powerMonitor.on('suspend', inactive)
  powerMonitor.on('lock-screen', inactive)
  powerMonitor.on('resume', active)
  powerMonitor.on('unlock-screen', active)
  win.on('closed', () => {
    powerMonitor.removeListener('suspend', inactive)
    powerMonitor.removeListener('lock-screen', inactive)
    powerMonitor.removeListener('resume', active)
    powerMonitor.removeListener('unlock-screen', active)
  })

  return active
}
