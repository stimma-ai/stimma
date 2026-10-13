/** The phone shells hand bytes to the OS share sheet in one message; above this they fail. */
export const PHONE_SHARE_MAX_BYTES = 64 * 1024 * 1024
export const PHONE_SHARE_TOO_LARGE = 'This file is too large for the share sheet (64 MB maximum). Use Export to save it instead.'

function isPhoneShell(kind: string) {
  return kind === 'ios' || kind === 'android'
}

/**
 * Checked against the library's recorded size BEFORE downloading anything,
 * so a 300 MB video says no at once instead of after the download.
 */
export function phoneShareTooLarge(kind: string, sizeBytes: number | null | undefined): boolean {
  return isPhoneShell(kind) && typeof sizeBytes === 'number' && sizeBytes > PHONE_SHARE_MAX_BYTES
}

/** File sharing only: library URLs may be private or local to this device. */
export function supportsNativeShare(kind: string, nav: Pick<Navigator, 'share' | 'canShare'> = navigator): boolean {
  return isPhoneShell(kind) || (typeof nav.share === 'function' && typeof nav.canShare === 'function')
}

export function shareFile(
  file: File,
  bridge: { kind: string; saveToDownloads: (name: string, bytes: Uint8Array) => Promise<boolean> },
  nav: Pick<Navigator, 'share' | 'canShare'> = navigator,
): Promise<unknown> {
  if (isPhoneShell(bridge.kind)) {
    if (phoneShareTooLarge(bridge.kind, file.size)) return Promise.reject(new Error(PHONE_SHARE_TOO_LARGE))
    return file.arrayBuffer().then(async bytes => {
      const completed = await bridge.saveToDownloads(file.name, new Uint8Array(bytes))
      if (!completed) throw new DOMException('Sharing was cancelled.', 'AbortError')
      return true
    })
  }
  if (!supportsNativeShare(bridge.kind, nav) || !nav.canShare({ files: [file] })) {
    return Promise.reject(new Error('This browser cannot share this file. Use Export to save it instead.'))
  }
  // Must run directly in the tap handler, before any fetch or other await.
  return nav.share({ files: [file] })
}
