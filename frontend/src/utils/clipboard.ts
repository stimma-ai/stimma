import { desktop } from '../desktop'

/**
 * Copy text to clipboard via the desktop bridge (native clipboard in the
 * desktop app, navigator.clipboard in the browser).
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await desktop.writeClipboardText(text)
    return true
  } catch (e) {
    console.error('[clipboard] Failed to copy:', e)
    return false
  }
}
