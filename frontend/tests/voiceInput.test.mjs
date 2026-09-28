import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { ref, computed } from 'vue'

// Run the actual composable with a fake desktop bridge and controlled time.
const source = stripTypeScriptTypes(readFileSync(new URL('../src/composables/useVoiceInput.ts', import.meta.url), 'utf8'))
  .replace(/^import .*$/gm, '').replace(/^export /gm, '')

async function fixture(t, bridgeOverrides = {}) {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] })
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
    ...bridgeOverrides,
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

test('a short burst of rapid space taps remains ordinary typing', async t => {
  const f = await fixture(t)
  for (let i = 0; i < 5; i++) {
    f.down(); f.up(); f.tick(25); await f.flush()
  }
  f.tick(350); await f.flush()
  assert.equal(f.starts, 0)
  assert.equal(f.text, ' '.repeat(5))
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

test('sustained keyboard-bridge down/up repeats dictate and stop after release', async t => {
  const f = await fixture(t)
  f.down('a')
  for (let i = 0; i < 30; i++) {
    f.down(); f.up(); f.tick(25); await f.flush()
  }
  assert.equal(f.starts, 1)
  assert.equal(f.text, 'a ')
  assert.equal(f.stops, 0)
  f.tick(60); await f.flush()
  assert.equal(f.stops, 1)
  assert.equal(f.api.state.value, 'idle')
})

test('spaced taps never accumulate into a hold', async t => {
  const f = await fixture(t)
  for (let i = 0; i < 30; i++) {
    f.down(); f.up(); f.tick(100); await f.flush()
  }
  assert.equal(f.starts, 0)
  assert.equal(f.text, ' '.repeat(30))
})

test('typing between repeat bursts prevents them from becoming a hold', async t => {
  const f = await fixture(t)
  for (let word = 0; word < 4; word++) {
    for (let i = 0; i < 5; i++) {
      f.down(); f.up(); f.tick(25); await f.flush()
    }
    f.down('a')
  }
  f.tick(300); await f.flush()
  assert.equal(f.starts, 0)
  assert.equal(f.text, '     a'.repeat(4))
})

test('blur cancels a pending repeat burst', async t => {
  const f = await fixture(t)
  for (let i = 0; i < 8; i++) {
    f.down(); f.up(); f.tick(25); await f.flush()
  }
  f.window.dispatchEvent(new Event('blur'))
  f.tick(300); await f.flush()
  assert.equal(f.starts, 0)
})

test('local holds can retry after a temporary capture error', async t => {
  let attempts = 0
  const f = await fixture(t, {
    voiceStart: async () => { if (++attempts === 1) throw new Error('Microphone temporarily unavailable') },
  })
  f.down(); f.tick(250); await f.flush(); f.up()
  assert.equal(f.api.state.value, 'error')
  f.down(); f.tick(250); await f.flush()
  assert.equal(attempts, 2)
  assert.equal(f.api.state.value, 'recording')
  f.up(); await f.flush()
  assert.equal(f.api.state.value, 'idle')
})

test('model status failures show an error and allow retry', async t => {
  let attempts = 0
  const f = await fixture(t, {
    voiceModelStatus: async () => { if (++attempts === 1) throw new Error('Helper unavailable'); return true },
  })
  assert.equal(await f.api.start(), false)
  assert.equal(f.api.state.value, 'error')
  assert.match(f.api.error.value, /Helper unavailable/)
  f.down(); f.tick(250); await f.flush()
  assert.equal(f.starts, 1)
  f.up(); await f.flush()
})

test('releasing a local hold during the model check prevents late capture', async t => {
  let resolveStatus
  const f = await fixture(t, { voiceModelStatus: () => new Promise(resolve => { resolveStatus = resolve }) })
  f.down(); f.tick(250); await f.flush()
  assert.equal(f.api.state.value, 'starting')
  f.up()
  resolveStatus(true); await f.flush()
  assert.equal(f.starts, 0)
  assert.equal(f.api.state.value, 'idle')
})

test('release while native capture is starting does not restart keepalive', async t => {
  let resolveStart
  let keepalives = 0
  const f = await fixture(t, {
    voiceStart: () => new Promise(resolve => { resolveStart = resolve }),
    voiceKeepalive: async () => { keepalives++ },
  })
  f.down(); f.tick(250); await f.flush()
  f.up(); await f.flush()
  assert.equal(f.stops, 1)
  resolveStart(); await f.flush()
  f.tick(2000); await f.flush()
  assert.equal(keepalives, 0)
  assert.equal(f.api.state.value, 'idle')
})

test('paired repeats never paint a run of spaces while arming dictation', async t => {
  const f = await fixture(t)
  f.down('a')
  for (let i = 0; i < 30; i++) {
    f.down(); f.up(); f.tick(25); await f.flush()
    assert.equal(f.text, 'a ')
  }
  assert.equal(f.starts, 1)
})

test('buffered space taps are inserted before the next character', async t => {
  const f = await fixture(t)
  f.down('a')
  f.down(); f.up(); f.tick(25)
  f.down(); f.up(); f.tick(25)
  assert.equal(f.text, 'a ')
  f.down('b')
  assert.equal(f.text, 'a  b')
  f.tick(300); await f.flush()
  assert.equal(f.starts, 0)
})
