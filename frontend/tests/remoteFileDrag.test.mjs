import assert from 'node:assert/strict'
import test from 'node:test'
import { build } from 'vite'

// Exercise the real composable with only its shell/network dependencies replaced.
const result = await build({
  configFile: false, logLevel: 'silent',
  build: { write: false, minify: false, lib: { entry: 'src/composables/useTauriDrag.ts', formats: ['es'] } },
  plugins: [{ name: 'fixture', enforce: 'pre',
    resolveId(id) {
      if (/^(vue|\.\/useMediaApi|\.\.\/apiConfig|\.\.\/desktop|\.\/useProfile|\.\/useMultiDevice|\.\/useToasts)$/.test(id)) return '\0fixture'
    },
    load(id) { if (id === '\0fixture') return `
      const s = globalThis.dragFixture;
      export const ref = value => ({value});
      export const useMediaApi = () => ({getMediaItem: async () => null});
      export const getApiBase = () => '/api';
      export const isTauri = () => true;
      export const initApiConfig = async () => {};
      export const desktop = s.desktop;
      export const getCurrentDbGuid = () => s.profile;
      export const useMultiDevice = () => s;
      export const addToast = () => {};
    ` },
  }],
})
const code = (Array.isArray(result) ? result[0] : result).output.find(x => x.type === 'chunk').code

test('remote reveal and drag use local copies, isolate devices, and never wait inside a drag', async () => {
  const calls = [], requests = []
  globalThis.dragFixture = {
    profile: 'profile-a', isRemote: { value: true }, activeDeviceId: { value: 'server-a' },
    desktop: {
      cacheRemoteFile: async (name, bytes) => { assert.equal(name, 'picture.png'); assert.equal(bytes.length, 3); return `/tmp/copy-${requests.length}.png` },
      revealItemInDir: async path => calls.push(['reveal', path]),
      startNativeDrag: async paths => calls.push(['drag', ...paths]),
    },
  }
  const previousFetch = globalThis.fetch
  globalThis.fetch = async url => {
    requests.push(url)
    return new Response(new Uint8Array([1, 2, 3]), { headers: { 'content-disposition': "inline; filename*=UTF-8''picture.png" } })
  }
  try {
    const { useTauriDrag } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
    await new Promise(resolve => setTimeout(resolve, 0))
    const drag = useTauriDrag()
    await drag.revealMediaFile(7, '/server/picture.png')
    assert.deepEqual(requests, ['/api/db/profile-a/media/7/file'])
    assert.deepEqual(calls, [['reveal', '/tmp/copy-1.png']])
    let prevented = false
    const operation = drag.handleDragStart({ preventDefault() { prevented = true } }, 7, '/server/picture.png')
    assert.equal(prevented, true)
    assert.deepEqual(calls.at(-1), ['drag', '/tmp/copy-1.png'])
    await operation
    globalThis.dragFixture.activeDeviceId.value = 'server-b'
    calls.length = 0
    await drag.handleDragStart({ preventDefault() {} }, 7, '/server/picture.png')
    assert.equal(calls.length, 0, 'cold remote drag must not start after awaiting transfer')
    await drag.revealMediaFile(7, '/server/picture.png')
    assert.equal(requests.length, 2)
    assert.deepEqual(calls, [['reveal', '/tmp/copy-2.png']])
    globalThis.dragFixture.profile = 'profile-b'
    await drag.revealMediaFile(7, '/server/picture.png')
    assert.equal(requests.at(-1), '/api/db/profile-b/media/7/file')
    globalThis.dragFixture.profile = 'unavailable'
    globalThis.fetch = async () => new Response('', { status: 503 })
    const beforeFailure = calls.length
    await assert.rejects(drag.revealMediaFile(7, '/server/picture.png'), /local copy/)
    await drag.handleMultiDragStart({ preventDefault() {} }, [7, 8], ['/server/a', '/server/b'])
    assert.equal(calls.length, beforeFailure, 'failed transfers never reveal or drag server paths')
    globalThis.dragFixture.isRemote.value = false
    await drag.revealMediaFile(7, '/local/original.png')
    assert.deepEqual(calls.at(-1), ['reveal', '/local/original.png'])
  } finally { globalThis.fetch = previousFetch; delete globalThis.dragFixture }
})
