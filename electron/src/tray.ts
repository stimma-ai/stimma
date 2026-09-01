/**
 * System tray (Windows) / status area (Linux). macOS gets none — the Dock
 * fills this role there, matching the Tauri shell exactly (its TrayIconBuilder
 * was compiled out on macOS).
 *
 * Behavior ported from src-tauri/src/lib.rs: a hidden window needs a way
 * back, so the tray offers "Show Stimma" and "Quit", and a plain left click
 * re-shows all windows (the menu opens on right click only).
 */

import { Menu, Tray, app } from 'electron'
import fs from 'node:fs'
import path from 'node:path'
import { log } from './log'
import { showAllWindows } from './windows'

// Module-scoped so the tray isn't garbage-collected.
let tray: Tray | null = null

function trayIconPath(): string | null {
  const candidates = app.isPackaged
    ? [path.join(process.resourcesPath, 'tray-icon.png')]
    : [
        // Dev: the committed (unbadged) icon from the repo.
        path.join(__dirname, '..', '..', 'src-tauri', 'icons', '32x32.png'),
      ]
  return candidates.find((candidate) => fs.existsSync(candidate)) ?? null
}

export function installTray(productName: string): void {
  if (process.platform === 'darwin') return

  const icon = trayIconPath()
  if (!icon) {
    log.warn('tray', 'Tray icon asset missing; system tray not installed')
    return
  }

  try {
    tray = new Tray(icon)
    tray.setToolTip(productName)
    tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: `Show ${productName}`, click: () => showAllWindows() },
        { label: 'Quit', click: () => app.quit() },
      ]),
    )
    // Left click re-shows directly; the context menu stays on right click.
    tray.on('click', () => showAllWindows())
    log.info('tray', 'System tray installed')
  } catch (e) {
    log.warn('tray', `Failed to install system tray: ${e}`)
  }
}
