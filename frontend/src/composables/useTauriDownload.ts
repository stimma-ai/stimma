/**
 * Composable for handling file downloads in Tauri.
 *
 * In Tauri, browser download mechanisms (anchor tag with download attribute)
 * don't work. We use the Tauri FS plugin to write files directly to the
 * Downloads folder.
 */

import { ref } from 'vue'

// Module-level state
const isTauri = ref(false)
let downloadDir: string | null = null
let initPromise: Promise<void> | null = null
let initComplete = false

/**
 * Initialize Tauri detection and load path info.
 * Returns a promise that resolves when initialization is complete.
 */
async function initTauri(): Promise<void> {
  if (initComplete) return

  if (initPromise) {
    return initPromise
  }

  initPromise = (async () => {
    try {
      const { invoke } = await import('@tauri-apps/api/core')

      // Try to invoke a command to verify IPC works
      await invoke('get_backend_port')
      isTauri.value = true
      console.log('[useTauriDownload] Tauri detected')

      // Get the downloads directory path
      const { downloadDir: getDownloadDir } = await import('@tauri-apps/api/path')
      downloadDir = await getDownloadDir()
      console.log('[useTauriDownload] Downloads directory:', downloadDir)
    } catch (e) {
      console.log('[useTauriDownload] Not in Tauri or IPC not available:', e)
      isTauri.value = false
      downloadDir = null
    } finally {
      initComplete = true
    }
  })()

  return initPromise
}

// Start initialization immediately on module load
initTauri()

/**
 * Ensure Tauri is initialized before proceeding.
 * Call this at the start of any download operation.
 */
async function ensureInitialized(): Promise<void> {
  if (!initComplete) {
    await initTauri()
  }
}

/**
 * Generate a unique filename by appending a number if the file already exists
 */
async function getUniqueFilename(baseFilename: string): Promise<string> {
  if (!downloadDir) return baseFilename

  try {
    const { exists } = await import('@tauri-apps/plugin-fs')

    // Check if file exists
    const fullPath = `${downloadDir}/${baseFilename}`
    if (!(await exists(fullPath))) {
      return baseFilename
    }

    // File exists, find a unique name
    const lastDot = baseFilename.lastIndexOf('.')
    const name = lastDot > 0 ? baseFilename.substring(0, lastDot) : baseFilename
    const ext = lastDot > 0 ? baseFilename.substring(lastDot) : ''

    let counter = 1
    while (counter < 1000) {
      const newFilename = `${name} (${counter})${ext}`
      if (!(await exists(`${downloadDir}/${newFilename}`))) {
        return newFilename
      }
      counter++
    }

    // Fallback with timestamp if all numbered versions exist
    return `${name}_${Date.now()}${ext}`
  } catch (e) {
    console.error('[useTauriDownload] Error checking file existence:', e)
    return baseFilename
  }
}

/**
 * Save binary data to the Downloads folder (Tauri only)
 */
async function saveToDownloads(data: Uint8Array, filename: string): Promise<boolean> {
  await ensureInitialized()

  if (!isTauri.value || !downloadDir) {
    console.error('[useTauriDownload] Cannot save: not in Tauri or no download dir')
    return false
  }

  try {
    const { writeFile, BaseDirectory } = await import('@tauri-apps/plugin-fs')

    // Get a unique filename to avoid overwriting
    const uniqueFilename = await getUniqueFilename(filename)

    console.log('[useTauriDownload] Saving to:', `${downloadDir}/${uniqueFilename}`)
    await writeFile(uniqueFilename, data, { baseDir: BaseDirectory.Download })
    console.log('[useTauriDownload] File saved successfully:', uniqueFilename)

    return true
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
 * Works in both Tauri and browser.
 */
async function downloadFromResponse(
  responseData: Blob,
  filename: string
): Promise<boolean> {
  await ensureInitialized()

  try {
    console.log('[useTauriDownload] Downloading with filename:', filename, 'isTauri:', isTauri.value)

    if (isTauri.value && downloadDir) {
      // In Tauri: save directly to Downloads folder
      const arrayBuffer = await responseData.arrayBuffer()
      const data = new Uint8Array(arrayBuffer)
      return await saveToDownloads(data, filename)
    } else {
      // In browser: use anchor tag download
      triggerBrowserDownload(responseData, filename)
      return true
    }
  } catch (e) {
    console.error('[useTauriDownload] Download from response failed:', e)
    return false
  }
}

/**
 * Check if we're running in Tauri
 */
async function checkIsTauri(): Promise<boolean> {
  await ensureInitialized()
  return isTauri.value
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
