import assert from 'node:assert/strict'
import test from 'node:test'

import { browserBridge } from './browserBridge.ts'
import { mobileBridge, isMobileShell, revealMobileInterface, setMobileSlideshowActive } from './mobileBridge.ts'
import { mobileNative } from './mobileNative.ts'
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
  // multi-device
  'mdGetState',
  'mdRefreshDevices',
  'mdLocalStatus',
  'mdSetLocalServing',
  'mdRenameLocal',
  'mdForgetDevice',
  'authLocal',
  'mdSetActiveDevice',
  'mdUseLocalServer',
  'mdRetry',
  'mdOnConnectionState',
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
  ['ios', mobileBridge],
] as const

test('Android bridge correlates native replies and preserves native-only authentication', async () => {
  const previous = globalThis.window
  const requests: any[] = []
  const port = {
    onmessage: null as ((event: { data: string }) => void) | null,
    postMessage(message: string) { requests.push(JSON.parse(message)) },
  }
  globalThis.window = { stimmaAndroid: port } as any
  try {
    assert.equal(isMobileShell(), true)
    assert.equal(mobileBridge.kind, 'android')
    const first = mobileNative('connectionInfo')
    const second = mobileNative('getState')
    port.onmessage!({ data: JSON.stringify({ id: requests[1].id, result: { connectionState: 'ready' } }) })
    port.onmessage!({ data: JSON.stringify({ id: requests[0].id, result: { authenticated: true } }) })
    assert.deepEqual(await first, { authenticated: true })
    assert.deepEqual(await second, { connectionState: 'ready' })
    const failure = mobileNative('unsupported')
    port.onmessage!({ data: JSON.stringify({ id: requests[2].id, error: 'Unsupported command' }) })
    await assert.rejects(failure, /Unsupported command/)
    assert.equal((await mobileBridge.authLocal('POST', '/auth/account')).status, 501)
    assert.equal(requests.length, 3)
  } finally { globalThis.window = previous }
})

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

test('non-electron bridges report multi-device as absent, not broken', async () => {
  // The chip hides itself when there are no devices, so a shell without
  // multi-device support must report an empty list on a ready local device
  // rather than an error state.
  for (const bridge of [browserBridge, tauriBridge]) {
    const state = await bridge.mdGetState()
    assert.equal(state.connectionState, 'ready')
    assert.equal(state.activeDeviceId, state.localDeviceId)
    assert.deepEqual(state.devices, [])
    assert.deepEqual(await bridge.mdRefreshDevices(), [])
    assert.equal(typeof bridge.mdOnConnectionState(() => {}), 'function')
  }
})

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


test('mobile account operations never reach the remote backend', async (t) => {
  const calls: unknown[] = []
  const target = new EventTarget()
  const auth = { ok: true, status: 200, data: { authenticated: true } }
  t.mock.method(globalThis, 'fetch', async () => { throw new Error('Unexpected remote auth request') })
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  t.after(() => {
    if (previousWindow) Object.defineProperty(globalThis, 'window', previousWindow)
    else Reflect.deleteProperty(globalThis, 'window')
  })
  Object.defineProperty(globalThis, 'window', { configurable: true, value: {
    location: { port: '9876' },
    webkit: { messageHandlers: { stimma: { async postMessage(message: { method: string }) {
      calls.push(message)
      return message.method === 'authStatus' ? auth : null
    } } } },
    addEventListener: target.addEventListener.bind(target),
    removeEventListener: target.removeEventListener.bind(target),
  } })
  assert.equal(isMobileShell(), true)
  assert.equal(await mobileBridge.getBackendPort(), 9876)
  assert.deepEqual(await mobileBridge.authLocal('GET', '/auth/status'), auth)
  await mobileBridge.authLocal('POST', '/auth/logout')
  const result = await mobileBridge.authLocal('POST', '/auth/unknown')
  assert.equal(result.ok, false)
  assert.deepEqual(calls, [{ method: 'authStatus', args: {} }, { method: 'logout', args: {} }])
  await assert.rejects(mobileBridge.openProfileWindow('profile'))
  await assert.rejects(mobileBridge.mdSetLocalServing(true))
  assert.equal(await mobileBridge.checkForUpdate(), null)
  const transitions: string[] = []
  const unsubscribe = mobileBridge.mdOnConnectionState(state => transitions.push(state))
  target.dispatchEvent(new CustomEvent('stimma:connection-state', { detail: 'unreachable' }))
  target.dispatchEvent(new CustomEvent('stimma:connection-state', { detail: 'invalid' }))
  unsubscribe()
  target.dispatchEvent(new CustomEvent('stimma:connection-state', { detail: 'ready' }))
  assert.deepEqual(transitions, ['unreachable'])
  await assert.rejects(mobileBridge.openExternal('file:///private/file'))
})

test('mobile retry returns the resulting native state without overwriting successful recovery', async (t) => {
  let state = 'unreachable'
  const calls: string[] = []
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  t.after(() => {
    if (previousWindow) Object.defineProperty(globalThis, 'window', previousWindow)
    else Reflect.deleteProperty(globalThis, 'window')
  })
  Object.defineProperty(globalThis, 'window', { configurable: true, value: {
    webkit: { messageHandlers: { stimma: { async postMessage(message: { method: string }) {
      calls.push(message.method)
      if (message.method === 'reload') state = 'ready'
      return { connectionState: state }
    } } } },
  } })
  assert.equal(await mobileBridge.mdRetry(), 'ready')
  assert.deepEqual(calls, ['reload', 'getState'])
})

test('slideshow entry and exit update iOS rotation policy, with older-shell compatibility', async t => {
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
  t.after(() => {
    if (previousWindow) Object.defineProperty(globalThis, 'window', previousWindow)
    else Reflect.deleteProperty(globalThis, 'window')
  })
  const calls: unknown[] = []
  Object.defineProperty(globalThis, 'window', { configurable: true, value: {
    webkit: { messageHandlers: { stimma: { async postMessage(message: unknown) { calls.push(message) } } } },
  } })
  await setMobileSlideshowActive(true)
  await setMobileSlideshowActive(false)
  assert.deepEqual(calls, [
    { method: 'setSlideshowActive', args: { active: true } },
    { method: 'setSlideshowActive', args: { active: false } },
  ])
  const handler = (window as any).webkit.messageHandlers.stimma
  handler.postMessage = async () => { throw new Error('Unsupported native operation') }
  await assert.doesNotReject(setMobileSlideshowActive(true))
})

test('mobile loading cover waits for a rendered frame before revealing the app', async (t) => {
  const calls: string[] = []
  const frames: FrameRequestCallback[] = []
  for (const key of ['window', 'requestAnimationFrame']) {
    const previous = Object.getOwnPropertyDescriptor(globalThis, key)
    t.after(() => {
      if (previous) Object.defineProperty(globalThis, key, previous)
      else Reflect.deleteProperty(globalThis, key)
    })
  }
  Object.defineProperty(globalThis, 'window', { configurable: true, value: {
    webkit: { messageHandlers: { stimma: { async postMessage(message: { method: string }) {
      calls.push(message.method)
    } } } },
  } })
  Object.defineProperty(globalThis, 'requestAnimationFrame', { configurable: true, value: (callback: FrameRequestCallback) => frames.push(callback) })
  const ready = revealMobileInterface()
  assert.deepEqual(calls, [])
  frames.shift()!(0)
  assert.deepEqual(calls, [])
  frames.shift()!(16)
  await ready
  assert.deepEqual(calls, ['interfaceReady'])
})
