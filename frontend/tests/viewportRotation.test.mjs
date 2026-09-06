import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, watch } from 'vue'

async function fixture(t, { native = true, width = 390, height = 844 } = {}) {
  const originals = ['window', 'document'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)])
  t.after(() => {
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor)
      else Reflect.deleteProperty(globalThis, key)
    }
  })
  const queries = []
  const attributes = {}
  Object.defineProperty(globalThis, 'window', { configurable: true, value: {
    screen: { width, height }, location: { search: '' },
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    ...(native ? { webkit: { messageHandlers: { stimma: { postMessage() {} } } } } : {}),
    matchMedia(query) {
      const listeners = []
      const result = {
        get matches() {
          if (query === '(pointer: coarse)') return native
          if (query === '(max-width: 767px)') return width < 768
          return width >= 768 && width <= 1023
        },
        addEventListener(_, fn) { listeners.push(fn) },
      }
      queries.push(() => listeners.forEach(fn => fn({ matches: result.matches })))
      return result
    },
  } })
  Object.defineProperty(globalThis, 'document', { configurable: true, value: {
    documentElement: { setAttribute(key, value) { attributes[key] = value } },
  } })
  const { useViewport } = await import(`../src/composables/useViewport.ts?case=${native}-${width}-${height}`)
  return {
    viewport: useViewport(), attributes,
    async rotate() { [width, height] = [height, width]; queries.forEach(fn => fn()); await nextTick() },
  }
}

test('native phone keeps compact chrome and slideshow controls through both rotations', async t => {
  const f = await fixture(t)
  let remounts = 0
  const stop = watch(f.viewport.isCompact, () => remounts++)
  t.after(stop)
  for (let i = 0; i < 6; i++) {
    await f.rotate()
    assert.equal(f.viewport.isCompact.value, true)
    assert.equal(f.attributes['data-viewport'], 'compact')
    assert.equal(f.viewport.isCoarsePointer.value, true)
  }
  assert.equal(remounts, 0, 'App must not replace its router/KeepAlive tree')
})

test('a phone launched sideways also uses compact chrome', async t => {
  const f = await fixture(t, { width: 844, height: 390 })
  assert.equal(f.viewport.isCompact.value, true)
  await f.rotate()
  assert.equal(f.viewport.isCompact.value, true)
})

test('ordinary browser responsive breakpoints remain unchanged', async t => {
  const f = await fixture(t, { native: false })
  assert.equal(f.viewport.isCompact.value, true)
  await f.rotate()
  assert.equal(f.viewport.isMedium.value, true)
  await f.rotate()
  assert.equal(f.viewport.isCompact.value, true)
})

test('native tablets retain tablet and wide layouts', async t => {
  const f = await fixture(t, { width: 820, height: 1180 })
  assert.equal(f.viewport.isMedium.value, true)
  await f.rotate()
  assert.equal(f.viewport.isWide.value, true)
})
