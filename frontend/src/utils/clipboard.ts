import { writeText } from '@tauri-apps/plugin-clipboard-manager'

/**
 * Copy text to clipboard using Tauri's clipboard plugin
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await writeText(text)
    return true
  } catch (e) {
    console.error('[clipboard] Failed to copy:', e)
    return false
  }
}
