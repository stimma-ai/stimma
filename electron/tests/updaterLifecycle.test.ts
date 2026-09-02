import assert from 'node:assert/strict'
import test from 'node:test'

import { beginUpdateInstall } from '../src/updaterLifecycle.ts'

test('update install marks the app as quitting before electron-updater closes windows', () => {
  const calls: string[] = []

  beginUpdateInstall({
    markQuitting: () => calls.push('mark-quitting'),
    shutdownHelper: () => calls.push('shutdown-helper'),
    shutdownBackend: () => calls.push('shutdown-backend'),
    quitAndInstall: () => calls.push('quit-and-install'),
  })

  assert.deepEqual(calls, [
    'mark-quitting',
    'shutdown-helper',
    'shutdown-backend',
    'quit-and-install',
  ])
})
