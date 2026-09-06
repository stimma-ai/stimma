/** File sharing only: library URLs may be private or local to this device. */
export function supportsNativeShare(kind: string, nav: Pick<Navigator, 'share' | 'canShare'> = navigator): boolean {
  return kind === 'ios' || (typeof nav.share === 'function' && typeof nav.canShare === 'function')
}

export function shareFile(
  file: File,
  bridge: { kind: string; saveToDownloads: (name: string, bytes: Uint8Array) => Promise<boolean> },
  nav: Pick<Navigator, 'share' | 'canShare'> = navigator,
): Promise<unknown> {
  if (bridge.kind === 'ios') {
    if (file.size > 64 * 1024 * 1024) return Promise.reject(new Error('This file is too large for the share sheet (64 MB maximum).'))
    return file.arrayBuffer().then(bytes => bridge.saveToDownloads(file.name, new Uint8Array(bytes)))
  }
  if (!supportsNativeShare(bridge.kind, nav) || !nav.canShare({ files: [file] })) {
    return Promise.reject(new Error('This browser cannot share this file. Use Export to save it instead.'))
  }
  // Must run directly in the tap handler, before any fetch or other await.
  return nav.share({ files: [file] })
}
