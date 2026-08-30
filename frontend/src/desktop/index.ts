/**
 * Desktop bridge selection.
 *
 * `desktop` is the app-wide bridge instance, chosen once at module load:
 * Electron preload bridge if exposed, Tauri if its IPC globals are present,
 * otherwise the browser fallback. `isDesktop()` replaces ad-hoc
 * `__TAURI_INTERNALS__` checks as the single shell feature-detection point.
 */

import type { DesktopBridge, DesktopKind } from './types'
import { browserBridge } from './browserBridge'
import { isTauriShell, tauriBridge } from './tauriBridge'

export type { DesktopBridge, DesktopKind, DesktopUpdate } from './types'
export type { VoiceDownloadEvent, VoiceTranscriptEvent } from './types'

function detectBridge(): DesktopBridge {
  if (typeof window !== 'undefined' && (window as any).stimmaDesktop) {
    // Electron preload bridge (window.stimmaDesktop) — implements DesktopBridge
    // directly; methods proxy to ipcRenderer.invoke in the preload script.
    return (window as any).stimmaDesktop as DesktopBridge
  }
  if (isTauriShell()) {
    return tauriBridge
  }
  return browserBridge
}

/** The active desktop bridge for this window. */
export const desktop: DesktopBridge = detectBridge()

/** True when running inside a native desktop shell (Tauri or Electron). */
export function isDesktop(): boolean {
  return desktop.kind !== 'browser'
}
