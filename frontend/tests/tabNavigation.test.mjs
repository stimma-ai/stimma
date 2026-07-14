import assert from 'node:assert/strict'
import test from 'node:test'

import { useTabNavigation } from '../src/composables/useTabNavigation.js'

test('slideshow visibility does not rewrite the active tool route', () => {
  const navigation = useTabNavigation()
  const originalWindow = globalThis.window
  const historyCalls = []

  globalThis.window = {
    history: {
      pushState: (...args) => historyCalls.push(['pushState', ...args]),
      replaceState: (...args) => historyCalls.push(['replaceState', ...args]),
    },
    location: {
      pathname: '/tools/provider%3Aimage-tool',
      search: '?instance=7',
      hash: '',
    },
  }

  try {
    navigation.enterSlideshowMode()
    assert.equal(navigation.slideshowActive.value, true)

    navigation.exitSlideshowMode()
    assert.equal(navigation.slideshowActive.value, false)
    assert.deepEqual(historyCalls, [])
  } finally {
    globalThis.window = originalWindow
  }
})
