import { test } from 'node:test'
import assert from 'node:assert/strict'
import { shareFile, supportsNativeShare } from './nativeShare.ts'

const file = new File(['image'], 'art.png', { type: 'image/png' })
const browser = { kind: 'browser', saveToDownloads: async () => { throw new Error('Unexpected download') } }

test('browser share is invoked synchronously with the actual file to retain tap activation', async () => {
  let called = false
  const nav = {
    canShare: (data: ShareData) => data.files?.[0] === file,
    share: (data: ShareData) => {
      assert.deepEqual(data, { files: [file] })
      called = true
      return Promise.resolve()
    },
  }
  const result = shareFile(file, browser, nav)
  assert.equal(called, true)
  await result
})

test('unsupported files do not share a private library URL or silently download', async () => {
  const nav = { canShare: () => false, share: async () => { throw new Error('Unexpected share') } }
  await assert.rejects(shareFile(file, browser, nav), /Use Export/)
  assert.equal(supportsNativeShare('browser', {} as Navigator), false)
})

test('iOS uses its native share bridge without requiring browser Web Share', async () => {
  const bridge = {
    kind: 'ios',
    saveToDownloads: async (name: string, bytes: Uint8Array) => {
      assert.equal(name, 'art.png')
      assert.equal(new TextDecoder().decode(bytes), 'image')
      return true
    },
  }
  assert.equal(supportsNativeShare('ios', {} as Navigator), true)
  assert.equal(await shareFile(file, bridge, {} as Navigator), true)
})

test('browser cancellation remains distinguishable from a sharing failure', async () => {
  const cancelled = new DOMException('Cancelled', 'AbortError')
  await assert.rejects(shareFile(file, browser, {
    canShare: () => true,
    share: () => Promise.reject(cancelled),
  }), err => err === cancelled)
})
