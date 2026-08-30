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
import { startBackend } from './backend'
import { initHelper, shutdownHelper } from './helper'
import { resolveIdentity } from './identity'
import { registerIpcHandlers } from './ipc'
import { initLog, log } from './log'
import { installApplicationMenu } from './menu'
import { WindowRegistry } from './registry'
import { initWindowState } from './windowState'
import {
  installAppLifecycle,
  restoreWindows,
  setWindowEnvironment,
  setWindowRegistry,
  showAllWindows,
} from './windows'

// Packaged bundle id is stamped by the build; dev falls back to debug.
const PACKAGED_BUNDLE_ID = 'ai.stimma.stimma.debug'

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
      ? { devUrl: `http://127.0.0.1:${identity.devFrontendPort}`, frontendDist: null }
      : { devUrl: null, frontendDist: path.join(process.resourcesPath, 'frontend') },
  )

  setWindowRegistry(new WindowRegistry(identity.dataDir))
  installAppLifecycle()
  initHelper(identity)
  registerIpcHandlers()
  startBackend(identity, app.getVersion())

  app.on('will-quit', () => {
    shutdownHelper()
  })

  void app.whenReady().then(() => {
    installApplicationMenu(identity.dev)
    initWindowState(identity.dataDir)
    restoreWindows()
    log.info('stimma', 'Windows restored')
  })
}
