import assert from 'node:assert/strict'
import test from 'node:test'

import { browserBridge } from './browserBridge.ts'
import { tauriBridge } from './tauriBridge.ts'

// The full bridge contract. Every implementation must expose exactly these
// methods — a shell that silently lacks one turns into a runtime crash in
// whatever feature calls it.
const CONTRACT_METHODS = [
  // app / backend
  'getBackendPort',
  'getAppVersion',
  'relaunch',
  'log',
  // windows / profiles
  'getWindowProfile',
  'reportWindowProfile',
  'openProfileWindow',
  'closeDeletedProfileWindow',
  'closeCurrentWindow',
  'setWindowTitle',
  'setWindowSize',
  'focusCurrentWindow',
  // shell
  'openExternal',
  'openAuthUrl',
  'openPath',
  'revealItemInDir',
  // clipboard
  'writeClipboardText',
  // dialogs
  'pickDirectory',
  // downloads
  'saveToDownloads',
  // print
  'print',
  // drag-out
  'startNativeDrag',
  'embedMetadata',
  'isShiftKeyDown',
  // voice
  'voiceModelStatus',
  'voiceDownloadModel',
  'voiceStart',
  'voiceStop',
  'voiceCancel',
  'voiceKeepalive',
  // updater
  'checkForUpdate',
  // tablet
  'onTabletInput',
] as const

const IMPLEMENTATIONS = [
  ['browser', browserBridge],
  ['tauri', tauriBridge],
] as const

for (const [name, bridge] of IMPLEMENTATIONS) {
  test(`${name} bridge implements the full desktop contract`, () => {
    for (const method of CONTRACT_METHODS) {
      assert.equal(
        typeof (bridge as any)[method],
        'function',
        `${name} bridge is missing ${method}()`,
      )
    }
    assert.equal(typeof bridge.kind, 'string')

    const extras = Object.keys(bridge).filter(
      (key) => key !== 'kind' && !(CONTRACT_METHODS as readonly string[]).includes(key),
    )
    assert.deepEqual(extras, [], `${name} bridge has undeclared methods: ${extras.join(', ')}`)
  })
}

test('browser bridge inert operations resolve to safe defaults', async () => {
  assert.equal(await browserBridge.getWindowProfile(), null)
  assert.equal(await browserBridge.closeDeletedProfileWindow(), false)
  assert.equal(await browserBridge.pickDirectory(), null)
  assert.equal(await browserBridge.embedMetadata({}), null)
  assert.equal(await browserBridge.isShiftKeyDown(), false)
  assert.equal(await browserBridge.voiceModelStatus(), false)
  assert.equal(await browserBridge.voiceStop(), '')
  assert.equal(await browserBridge.checkForUpdate(), null)
  const unlisten = await browserBridge.onTabletInput(() => {})
  assert.equal(typeof unlisten, 'function')
  unlisten()
})

test('browser bridge desktop-only operations reject rather than pretend', async () => {
  await assert.rejects(browserBridge.getBackendPort())
  await assert.rejects(browserBridge.getAppVersion())
  await assert.rejects(browserBridge.relaunch())
  await assert.rejects(browserBridge.openProfileWindow('p'))
  await assert.rejects(browserBridge.openPath('/tmp/x'))
  await assert.rejects(browserBridge.revealItemInDir('/tmp/x'))
  await assert.rejects(browserBridge.startNativeDrag(['/tmp/x']))
  await assert.rejects(browserBridge.voiceStart(() => {}))
  await assert.rejects(browserBridge.voiceDownloadModel(() => {}))
})
