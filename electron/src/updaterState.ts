export interface AvailableUpdate {
  version: string
  body?: string
  date?: string
}

/**
 * Tracks the update handle exposed to the renderer separately from the
 * package electron-updater has staged on disk.
 *
 * A check creates a fresh renderer-side handle, but it must not invalidate an
 * already downloaded package. Scheduled checks continue while the app waits
 * for the user to restart, so coupling these two lifetimes makes a later check
 * accidentally turn an updater-aware restart into a plain Electron relaunch.
 */
export class UpdaterState {
  available: AvailableUpdate | null = null
  downloadedVersion: string | null = null

  recordCheck(available: AvailableUpdate | null): void {
    this.available = available
  }

  markDownloaded(version: string): void {
    this.downloadedVersion = version
  }

  closeAvailableHandle(): void {
    this.available = null
  }

  hasDownloadedUpdate(): boolean {
    return this.downloadedVersion !== null
  }

  hasDownloadedAvailableUpdate(): boolean {
    return this.available !== null && this.downloadedVersion === this.available.version
  }
}
