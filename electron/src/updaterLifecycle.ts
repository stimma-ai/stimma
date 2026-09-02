export interface UpdateInstallActions {
  markQuitting(): void
  shutdownHelper(): void
  shutdownBackend(): void
  quitAndInstall(): void
}

/**
 * Prepare the app lifecycle before electron-updater starts its quit sequence.
 *
 * electron-updater closes every window before Electron emits `before-quit`.
 * Stimma's last-window handler normally hides that window to keep the app
 * warm, so it must know this is a genuine quit before quitAndInstall begins.
 */
export function beginUpdateInstall(actions: UpdateInstallActions): void {
  actions.markQuitting()
  actions.shutdownHelper()
  actions.shutdownBackend()
  actions.quitAndInstall()
}
