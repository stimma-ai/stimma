import assert from 'node:assert/strict'
import test from 'node:test'
import { createSlideshowSwipe } from '../src/utils/slideshowSwipe.js'

function fixture() {
  let time = 0
  const offsets = [], navigation = [], releases = []
  const swipe = createSlideshowSwipe({
    canNavigate: () => true,
    drag: x => offsets.push(x),
    navigate: direction => navigation.push(direction),
    release: direction => releases.push(direction),
    now: () => time,
  })
  const touch = (x, y) => ({ identifier: 1, clientX: x, clientY: y })
  return {
    offsets, navigation, releases, swipe,
    start: () => swipe.start({ touches: [touch(200, 200)] }),
    move(x, y = 200, elapsed = 30) {
      time += elapsed
      swipe.move({ touches: [touch(x, y)] })
    },
    end(x, y = 200, elapsed = 10) {
      time += elapsed
      swipe.end({ touches: [], changedTouches: [touch(x, y)] })
    },
  }
}

test('horizontal drag tracks the finger even when it drifts vertically', () => {
  const f = fixture()
  f.start(); f.move(150); f.move(100, 300)
  assert.deepEqual(f.offsets, [-50, -100])
  f.end(100, 300)
  assert.deepEqual(f.navigation, ['next'])
})

test('short fast flick advances but a short held drag springs back', () => {
  const flick = fixture()
  flick.start(); flick.move(170); flick.end(165)
  assert.deepEqual(flick.navigation, ['next'])
  const held = fixture()
  held.start(); held.move(170); held.end(170, 200, 500)
  assert.deepEqual(held.navigation, [])
  assert.deepEqual(held.releases, [null])
})

test('vertical intent never turns into a horizontal page change', () => {
  const f = fixture()
  f.start(); f.move(200, 170); f.move(50, 160); f.end(50, 160)
  assert.deepEqual(f.offsets, [])
  assert.deepEqual(f.navigation, [])
})

test('cancelling a drag releases it and prevents a synthetic tap or navigation', () => {
  const f = fixture()
  f.start(); f.move(100); f.swipe.cancel(); f.end(50)
  assert.deepEqual(f.navigation, [])
  assert.equal(f.releases[0], null)
  assert.equal(f.swipe.suppressClick(), true)
})

test('left-edge starts belong to the compact drawer, while interior swipes still advance', async () => {
  const { isDrawerEdgeTouch } = await import('../src/utils/drawerGesture.js')
  const navigation = [], offsets = []
  const swipe = createSlideshowSwipe({ canNavigate: () => true, reserveGesture: isDrawerEdgeTouch,
    navigate: direction => navigation.push(direction), drag: x => offsets.push(x) })
  const touch = x => ({ identifier: 1, clientX: x, clientY: 200 })
  swipe.start({ touches: [touch(8)] })
  swipe.move({ touches: [touch(210)] })
  swipe.end({ touches: [], changedTouches: [touch(210)] })
  assert.deepEqual(navigation, [])
  assert.deepEqual(offsets, [])
  assert.equal(swipe.suppressClick(), true)
  swipe.start({ touches: [touch(30)] })
  swipe.move({ touches: [touch(210)] })
  swipe.end({ touches: [], changedTouches: [touch(210)] })
  assert.deepEqual(navigation, ['previous'])
  assert.equal(isDrawerEdgeTouch({ touches: [touch(8), touch(12)] }), false)
})

test('compact shell opens the drawer over a slideshow only for a left-edge start', async () => {
  const { readFile } = await import('node:fs/promises')
  const { ref, computed } = await import('vue')
  const { isDrawerEdgeTouch } = await import('../src/utils/drawerGesture.js')
  // Exercise the shell's real handlers together with slideshow swipe ownership.
  const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
  const handlers = source.slice(source.indexOf('const DRAWER_W ='), source.indexOf('// Any navigation closes the drawer'))
  const create = new Function('ref', 'computed', 'isDrawerEdgeTouch', 'sidebarOpen', 'sidebarDocked', `${handlers}\nreturn { start: onCompactTouchStart, move: onCompactTouchMove, end: onCompactTouchEnd, drawerDragging, drawerX }`)
  for (const x of [8, 24, 25, 100]) {
    const sidebarOpen = ref(false)
    const drawer = create(ref, computed, isDrawerEdgeTouch, sidebarOpen, ref(false))
    const target = { closest: () => true }
    const touch = x => ({ identifier: 1, clientX: x, clientY: 200 })
    let prevented = false
    drawer.start({ touches: [touch(x)], target })
    drawer.move({ touches: [touch(x + 210)], target, cancelable: true, preventDefault: () => { prevented = true } })
    drawer.end({ changedTouches: [touch(x + 210)] })
    assert.equal(sidebarOpen.value, x <= 24)
    assert.equal(prevented, x <= 24)
    assert.equal(drawer.drawerDragging.value, false)
  }
})
