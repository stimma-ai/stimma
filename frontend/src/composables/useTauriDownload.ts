/**
 * Composable for handling file downloads in the desktop app.
 *
 * In the desktop shell, browser download mechanisms (anchor tag with download
 * attribute) don't work. The desktop bridge writes files directly to the
 * Downloads folder; browser mode falls back to an anchor-tag download.
 */

import { ref } from 'vue'
import { isDesktop, desktop } from '../desktop'
import { checkMobileDownloadSize, saveDownloadBlob } from '../utils/mobileDownload'

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
    throw new Error('File saving is unavailable outside the app.')
  }

  checkMobileDownloadSize(data.byteLength, desktop.kind)
  const saved = await desktop.saveToDownloads(filename, data)
  if (!saved) throw new Error('The file was not saved. Please try exporting again.')
  return true
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
  if (isDesktop()) return await saveDownloadBlob(responseData, filename, desktop)
  triggerBrowserDownload(responseData, filename)
  return true
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
