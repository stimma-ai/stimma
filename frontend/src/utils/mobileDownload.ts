export const MOBILE_SHARE_LIMIT = 64 * 1024 * 1024

export function checkMobileDownloadSize(size: number, kind: string): void {
  if (['ios', 'android'].includes(kind) && size > MOBILE_SHARE_LIMIT) {
    throw new Error('This file exceeds the 64 MB phone export limit. Choose a smaller export or export it from Stimma on your computer.')
  }
}

/** Check before allocating an ArrayBuffer or the native bridge's JSON array. */
export async function saveDownloadBlob(blob: Blob, filename: string, bridge: {
  kind: string
  saveToDownloads: (filename: string, bytes: Uint8Array) => Promise<boolean>
}): Promise<boolean> {
  checkMobileDownloadSize(blob.size, bridge.kind)
  const saved = await bridge.saveToDownloads(filename, new Uint8Array(await blob.arrayBuffer()))
  if (!saved) throw new Error('The file was not saved. Please try exporting again.')
  return true
}
