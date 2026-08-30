/**
 * Composable for handling file downloads in the desktop app.
 *
 * In the desktop shell, browser download mechanisms (anchor tag with download
 * attribute) don't work. The desktop bridge writes files directly to the
 * Downloads folder; browser mode falls back to an anchor-tag download.
 */

import { ref } from 'vue'
import { isDesktop, desktop } from '../desktop'

// Kept as a ref for existing template consumers; resolved synchronously now
// that shell detection no longer needs an IPC probe.
const isTauri = ref(isDesktop())

async function ensureInitialized(): Promise<void> {
  isTauri.value = isDesktop()
}

/**
 * Save binary data to the Downloads folder (desktop app only)
 */
async function saveToDownloads(data: Uint8Array, filename: string): Promise<boolean> {
  if (!isDesktop()) {
    console.error('[useTauriDownload] Cannot save: not in the desktop app')
    return false
  }

  try {
    return await desktop.saveToDownloads(filename, data)
  } catch (e) {
    console.error('[useTauriDownload] Failed to save file:', e)
    return false
  }
}

/**
 * Trigger a browser download using an anchor tag
 */
function triggerBrowserDownload(blob: Blob, filename: string): void {
  const blobUrl = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = blobUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(blobUrl)
}

/**
 * Download blob data with the given filename.
 * Works in both the desktop app and the browser.
 */
async function downloadFromResponse(
  responseData: Blob,
  filename: string
): Promise<boolean> {
  try {
    if (isDesktop()) {
      const arrayBuffer = await responseData.arrayBuffer()
      const data = new Uint8Array(arrayBuffer)
      return await saveToDownloads(data, filename)
    } else {
      triggerBrowserDownload(responseData, filename)
      return true
    }
  } catch (e) {
    console.error('[useTauriDownload] Download from response failed:', e)
    return false
  }
}

/**
 * Check if we're running in the desktop app
 */
async function checkIsTauri(): Promise<boolean> {
  return isDesktop()
}

export function useTauriDownload() {
  return {
    isTauri,
    downloadFromResponse,
    saveToDownloads,
    checkIsTauri,
    ensureInitialized
  }
}
