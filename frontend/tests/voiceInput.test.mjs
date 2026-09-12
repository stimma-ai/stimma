import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { ref, computed } from 'vue'

// Run the actual composable with a fake desktop bridge and controlled time.
const source = stripTypeScriptTypes(readFileSync(new URL('../src/composables/useVoiceInput.ts', import.meta.url), 'utf8'))
  .replace(/^import .*$/gm, '').replace(/^export /gm, '')

async function fixture(t) {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval'] })
  let starts = 0
  let stops = 0
  const window = new EventTarget()
  const document = new EventTarget()
  const create = new Function('ref', 'computed', 'onMounted', 'onUnmounted', 'checkIsTauri', 'initApiConfig', 'desktop', 'useTelemetry', 'isPrivacyLockdownActive', 'addToast', 'localStorage', 'window', 'document', `${source}; return useVoiceInput`)
  const useVoiceInput = create(ref, computed, fn => fn(), () => {}, () => true, async () => {}, {
    voiceModelStatus: async () => true,
    voiceStart: async () => { starts++ },
    voiceStop: async () => { stops++; return '' },
    voiceCancel: async () => {},
    voiceKeepalive: async () => {},
  }, () => ({ track() {} }), () => false, () => {}, { removeItem() {} }, window, document)
  let text = ''
  const api = useVoiceInput({ getText: () => text, setText: value => { text = value } })
  const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve() }
  await flush()
  t.after(() => api.cancel())
  function down(key = ' ', options = {}) {
    const event = { key, code: key === ' ' ? 'Space' : 'KeyA', repeat: false, preventDefault() { this.defaultPrevented = true }, ...options }
    api.handleInputKeydown(event)
    if (!event.defaultPrevented) text += key
    return event
  }
  return { api, down, up: () => api.handleInputKeyup({ key: ' ', code: 'Space' }), flush,
    tick: ms => t.mock.timers.tick(ms), window,
    get text() { return text }, get starts() { return starts }, get stops() { return stops } }
}

test('releasing just before the hold threshold never starts dictation', async t => {
  const f = await fixture(t)
  f.down(); f.tick(240); f.up(); f.tick(100); await f.flush()
  assert.equal(f.starts, 0)
  assert.equal(f.text, ' ')
})

test('rapid spaces remain separate keystrokes, including Deskflow pairs', async t => {
  const f = await fixture(t)
  for (let i = 0; i < 20; i++) {
    f.down(); f.up(); f.tick(25); await f.flush()
  }
  f.tick(350); await f.flush()
  assert.equal(f.starts, 0)
  assert.equal(f.text, ' '.repeat(20))
})

test('overlapping character typing cancels a pending space hold', async t => {
  const f = await fixture(t)
  f.down(); f.tick(100); f.down('a'); f.tick(300); await f.flush(); f.up()
  assert.equal(f.starts, 0)
  assert.equal(f.text, ' a')
})

test('a continuous hold starts once, suppresses repeat, and stops immediately on release', async t => {
  const f = await fixture(t)
  f.down(); f.tick(250); await f.flush()
  assert.equal(f.starts, 1)
  assert.equal(f.down(' ', { repeat: true }).defaultPrevented, true)
  f.up()
  assert.equal(f.stops, 1)
  await f.flush()
  assert.equal(f.api.state.value, 'idle')
})

test('blur cancels a hold before it can start', async t => {
  const f = await fixture(t)
  f.down(); f.tick(200); f.window.dispatchEvent(new Event('blur')); f.tick(200); await f.flush()
  assert.equal(f.starts, 0)
})

test('modified spaces and composition never arm dictation', async t => {
  const f = await fixture(t)
  for (const modifier of ['ctrlKey', 'altKey', 'metaKey', 'shiftKey', 'isComposing']) {
    f.down(' ', { [modifier]: true }); f.tick(300); await f.flush(); f.up()
  }
  assert.equal(f.starts, 0)
})
