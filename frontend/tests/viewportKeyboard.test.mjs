import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick } from 'vue'

// An unfolded foldable (roomy compact chrome) whose window the software keyboard
// shortens below the 500px "short" line while a text field has focus.
async function fixture(t, { width = 752, height = 822 } = {}) {
  const originals = ['window', 'document'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)])
  t.after(() => {
    for (const [key, descriptor] of originals) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor)
      else Reflect.deleteProperty(globalThis, key)
    }
  })
  const listeners = { short: [], resize: [] }
  const doc = { activeElement: null, documentElement: { setAttribute() {} } }
  Object.defineProperty(globalThis, 'window', { configurable: true, value: {
    screen: { width, height }, location: { search: '' },
    sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    webkit: { messageHandlers: { stimma: { postMessage() {} } } },
    addEventListener(type, fn) { if (type === 'resize') listeners.resize.push(fn) },
    matchMedia(query) {
      return {
        get matches() {
          if (query === '(pointer: coarse)') return true
          if (query === '(max-height: 499px)') return height < 500
          if (query === '(max-width: 767px)') return width < 768
          if (query === '(max-width: 599px)') return width < 600
          if (query.includes('min-width: 600px')) return width >= 600 && width <= 839
          return false
        },
        addEventListener(_, fn) { if (query === '(max-height: 499px)') listeners.short.push(fn) },
      }
    },
  } })
  Object.defineProperty(globalThis, 'document', { configurable: true, value: doc })
  const { useViewport } = await import(`../src/composables/useViewport.ts?keyboard=${Math.random()}`)
  return {
    viewport: useViewport(),
    focus(tagName, type) { doc.activeElement = tagName ? { tagName, type, isContentEditable: tagName === 'DIV' } : null },
    async setHeight(h) {
      height = h
      listeners.short.forEach(fn => fn({ matches: height < 500 }))
      listeners.resize.forEach(fn => fn())
      await nextTick()
    },
  }
}

test('the keyboard opening over a text field is not a short screen', async t => {
  const f = await fixture(t)
  assert.equal(f.viewport.isRoomy.value, true)
  assert.equal(f.viewport.isShort.value, false)
  f.focus('TEXTAREA')
  await f.setHeight(464)
  assert.equal(f.viewport.isShort.value, false, 'docked agent must stay where the focused field is')
  await f.setHeight(822)
  assert.equal(f.viewport.isShort.value, false)
})

test('the prompt editor (contenteditable) counts as typing too', async t => {
  const f = await fixture(t)
  f.focus('DIV')
  await f.setHeight(464)
  assert.equal(f.viewport.isShort.value, false)
})

test('a short window with nothing being typed is short', async t => {
  const f = await fixture(t)
  f.focus('BUTTON')
  await f.setHeight(400)
  assert.equal(f.viewport.isShort.value, true)
  await f.setHeight(822)
  assert.equal(f.viewport.isShort.value, false)
})

test('a window that stays short after typing ends becomes short on the next resize', async t => {
  const f = await fixture(t)
  f.focus('INPUT', 'text')
  await f.setHeight(464)
  assert.equal(f.viewport.isShort.value, false)
  f.focus(null)
  await f.setHeight(450)
  assert.equal(f.viewport.isShort.value, true)
})

test('a checkbox with focus is not typing', async t => {
  const f = await fixture(t)
  f.focus('INPUT', 'checkbox')
  await f.setHeight(464)
  assert.equal(f.viewport.isShort.value, true)
})
