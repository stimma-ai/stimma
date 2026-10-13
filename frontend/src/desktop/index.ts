/**
 * Desktop bridge selection.
 *
 * `desktop` is the app-wide bridge instance, chosen once at module load:
 * Electron preload bridge if exposed, then the native mobile bridge,
 * otherwise the browser fallback. `isDesktop()` is the single native-shell
 * feature-detection point.
 */

import type { DesktopBridge, DesktopKind } from './types'
import { browserBridge } from './browserBridge'
import { isMobileShell, mobileBridge } from './mobileBridge'

export type { DesktopBridge, DesktopKind, DesktopUpdate } from './types'
export type { VoiceDownloadEvent, VoiceTranscriptEvent } from './types'

function detectBridge(): DesktopBridge {
  if (typeof window !== 'undefined' && (window as any).stimmaDesktop) {
    // Electron preload bridge (window.stimmaDesktop) — implements DesktopBridge
    // directly; methods proxy to ipcRenderer.invoke in the preload script.
    return (window as any).stimmaDesktop as DesktopBridge
  }
  if (isMobileShell()) return mobileBridge
  return browserBridge
}

/** The active desktop bridge for this window. */
export const desktop: DesktopBridge = detectBridge()

/** True when running inside a native shell (iOS, Android, or Electron). */
export function isDesktop(): boolean {
  return desktop.kind !== 'browser'
}
