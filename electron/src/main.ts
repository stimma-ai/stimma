/**
 * Stimma Electron main process.
 *
 * Boot order matters: identity (bundle id + sandbox) is resolved and
 * userData is pointed inside the sandbox BEFORE app.ready, so the Chromium
 * profile, single-instance scope, and all storage share the sandbox
 * lifecycle (delete the sandbox → next launch is a fresh profile).
 */

import { app } from 'electron'
import path from 'node:path'
import { APP_ORIGIN, installAppProtocolHandler, registerAppScheme } from './appProtocol'
import { shutdownBackend, startBackend } from './backend'
import { initHelper, shutdownHelper } from './helper'
import { prepareLegacyStorageImport } from './legacyStorage'
import { readPackagedMetadata, resolveIdentity } from './identity'
import { registerIpcHandlers } from './ipc'
import { initLog, log } from './log'
import { installApplicationMenu } from './menu'
import { WindowRegistry } from './registry'
import { installTray } from './tray'
import { initWindowState } from './windowState'
import {
  installAppLifecycle,
  restoreWindows,
  setWindowEnvironment,
  setWindowRegistry,
  setWindowTitlePrefix,
  showAllWindows,
} from './windows'

// Packaged bundle id is stamped into package.json by the build (electron-
// builder extraMetadata) and must be read at runtime (see readPackagedMetadata).
const pkg = readPackagedMetadata(app.getAppPath())
const PACKAGED_BUNDLE_ID = pkg.stimmaBundleId || 'ai.stimma.stimma.debug'

const identity = resolveIdentity(PACKAGED_BUNDLE_ID)

// The Chromium profile lives inside the sandbox data dir. All windows share
// the default session (one sandbox = one session; profile windows do NOT get
// separate partitions — localStorage keys are profile-namespaced app-side).
app.setPath('userData', path.join(identity.dataDir, 'chromium'))

initLog(identity.dataDir)
log.info('stimma', `Starting Electron shell (bundle=${identity.bundleId}, sandbox=${identity.sandbox}, dev=${identity.dev})`)

// One app instance per sandbox (the lock is scoped by userData).
if (!app.requestSingleInstanceLock()) {
  log.info('stimma', 'Another instance owns this sandbox; focusing it and exiting.')
  app.exit(0)
} else {
  app.on('second-instance', () => {
    showAllWindows()
  })

  setWindowEnvironment(
    identity.dev
      // 127.0.0.1 (not localhost): the backend's CORS allowlist admits
      // http://127.0.0.1:<any port> for dev sandboxes.
      ? { devUrl: `http://127.0.0.1:${identity.devFrontendPort}`, appOrigin: null }
      : { devUrl: null, appOrigin: APP_ORIGIN },
  )
  if (!identity.dev) registerAppScheme()

  setWindowRegistry(new WindowRegistry(identity.dataDir))
  installAppLifecycle()
  initHelper(identity)
  registerIpcHandlers()
  startBackend(identity, app.getVersion())

  app.on('before-quit', () => {
    shutdownBackend()
  })
  app.on('will-quit', () => {
    shutdownHelper()
  })

  // Terminal signals become a genuine quit so quit hooks run — including
  // electron-updater's apply-on-quit (a raw exit would strand a staged
  // update) and the helper shutdown above.
  process.on('SIGTERM', () => app.quit())
  process.on('SIGINT', () => app.quit())

  if (pkg.productName) setWindowTitlePrefix(pkg.productName)

  void app.whenReady().then(async () => {
    if (!identity.dev) {
      installAppProtocolHandler(path.join(process.resourcesPath, 'frontend'))
    }
    installApplicationMenu(identity.dev)
    installTray(pkg.productName || 'Stimma')
    initWindowState(identity.dataDir)
    // WKWebView localStorage import must be resolved before the first window
    // loads: its preload injects the dump ahead of any page script.
    try {
      await prepareLegacyStorageImport(identity)
    } catch (e) {
      log.warn('legacy-storage', `Import preparation failed: ${e}`)
    }
    restoreWindows()
    log.info('stimma', 'Windows restored')
  })
}
