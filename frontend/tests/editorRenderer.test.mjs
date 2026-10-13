import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'
import { createEditorRenderer } from '../src/imageEditor/stack/editorRenderer.ts'

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function harness() {
  const document = ref({ edits: [{ id: 'edit', enabled: true, params: { value: 1 } }] })
  const frames = new Map(), timers = new Map()
  let handle = 0, gate = null, active = 0, maxActive = 0
  const calls = [], live = [], caches = [], errors = [], effects = []
  const composite = ref(null), stepPreviews = ref({ orphan: 'old' })
  const rendering = ref(false), maskDebtByOp = ref({})
  const overlay = ref(false), visible = ref([])
  let renderer
  const compositor = {
    failedOpIds: new Set(), maskDebt: new Map([['edit', 0.25]]),
    async render(doc) {
      calls.push(doc)
      active++
      maxActive = Math.max(maxActive, active)
      const blocked = gate
      gate = null
      renderer.onStepPreview('edit', `preview-${doc.edits[0]?.params.value}`)
      try {
        if (blocked) await blocked.promise
        return { value: doc.edits[0]?.params.value }
      } finally { active-- }
    },
    async renderUpTo() { throw new Error('unexpected crop replay') },
  }
  renderer = createEditorRenderer({
    document, baseReady: () => true,
    annotationOverlayActive: overlay, visibleAnnotateOps: visible,
    family: () => 'paint', cropOpId: () => null, setCropInput: () => {},
    compositor, composite, stepPreviews, rendering, maskDebtByOp,
    publishLivePreview: canvas => live.push(canvas),
    scheduleHeadCache: (doc, canvas) => caches.push({ doc, canvas }),
    syncSelectionGeometry: () => effects.push('geometry'),
    paint: () => effects.push('paint'), samplePalette: () => effects.push('palette'),
    looksOpen: () => false, renderLookThumbs: async () => {},
    reportError: message => errors.push(message),
    scheduler: {
      requestFrame(cb) { const id = ++handle; frames.set(id, cb); return id },
      cancelFrame(id) { frames.delete(id) },
      setTimer(cb, delay) { const id = ++handle; timers.set(id, { cb, delay }); return id },
      clearTimer(id) { timers.delete(id) },
    },
  })
  return { ...renderer, document, composite, stepPreviews, rendering, maskDebtByOp,
    compositor, overlay, visible, calls, live, caches, errors, effects, frames, timers,
    get maxActive() { return maxActive },
    block() { gate = deferred(); return gate },
    frame() { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(cb => cb()) },
    timer() { const callbacks = [...timers.values()]; timers.clear(); callbacks.forEach(({ cb }) => cb()) },
  }
}

test('requests coalesce into one frame and publish a single authoritative snapshot', async () => {
  const h = harness()
  const first = h.render()
  h.document.value.edits[0].params.value = 2
  const second = h.render()
  assert.equal(first, second)
  assert.equal(h.frames.size, 1)
  h.frame()
  await first
  assert.equal(h.calls.length, 1)
  assert.equal(h.composite.value.value, 2)
  assert.deepEqual(h.stepPreviews.value, { edit: 'preview-2' })
  assert.deepEqual(h.maskDebtByOp.value, { edit: 0.25 })
  assert.deepEqual(h.effects, ['geometry', 'paint', 'palette'])
  assert.equal(h.live.length, 1)
  assert.equal(h.caches.length, 1)
  assert.equal(h.rendering.value, false)
})

test('normal frames outrank settled bursts and repeated bursts reset their timer', async () => {
  const h = harness()
  const pending = h.render({ settleMs: 140 })
  const initial = [...h.timers.keys()][0]
  h.render({ settleMs: 140 })
  assert.equal(h.timers.has(initial), false)
  assert.equal(h.timers.size, 1)
  h.render()
  assert.equal(h.timers.size, 0)
  assert.equal(h.frames.size, 1)
  h.render({ settleMs: 140 })
  assert.equal(h.timers.size, 0)
  h.frame()
  await pending
  assert.equal(h.calls.length, 1)
  const settled = h.render({ settleMs: 140 })
  assert.equal(h.frames.size, 0)
  h.timer()
  await settled
  assert.equal(h.calls.length, 2)
})

test('an awaited replay is serialized and cannot publish its stale pixels or row previews', async () => {
  const h = harness()
  const blocked = h.block()
  const pending = h.render()
  h.frame()
  assert.equal(h.rendering.value, true)
  assert.deepEqual(h.stepPreviews.value, { orphan: 'old' })
  h.document.value.edits[0].params.value = 2
  const latest = h.render()
  assert.equal(latest, pending)
  assert.equal(h.calls.length, 1)
  blocked.resolve()
  await pending
  assert.equal(h.maxActive, 1)
  assert.equal(h.calls.length, 2)
  assert.equal(h.calls[0].edits[0].params.value, 1)
  assert.equal(h.composite.value.value, 2)
  assert.deepEqual(h.stepPreviews.value, { edit: 'preview-2' })
  assert.deepEqual(h.live.map(canvas => canvas.value), [2])
  assert.deepEqual(h.caches.map(({ canvas }) => canvas.value), [2])
})

test('overlay composites do not overwrite authoritative thumbnails or head caches', async () => {
  const h = harness()
  h.overlay.value = true
  h.visible.value = [{ id: 'edit' }]
  const pending = h.render()
  h.frame()
  await pending
  assert.equal(h.calls[0].edits.length, 0)
  assert.deepEqual(h.stepPreviews.value, { orphan: 'old' })
  assert.equal(h.live.length, 0)
  assert.equal(h.caches.length, 0)
  assert.deepEqual(h.effects, ['geometry', 'paint', 'palette'])
})

test('a failed edit is never persisted as an authoritative head cache', async () => {
  const h = harness()
  h.compositor.failedOpIds.add('edit')
  const pending = h.render()
  h.frame()
  await pending
  assert.equal(h.live.length, 1)
  assert.equal(h.caches.length, 0)
})

test('a superseded replay failure cannot put a stale error over the successful document', async () => {
  const h = harness()
  const blocked = h.block()
  const pending = h.render()
  h.frame()
  h.document.value.edits[0].params.value = 2
  h.render()
  blocked.reject(new Error('missing payload from the previous document'))
  await pending
  assert.equal(h.composite.value.value, 2)
  assert.deepEqual(h.errors, [])
})

test('teardown cancels a scheduled replay and resolves its waiting caller', async () => {
  const h = harness()
  const pending = h.render({ settleMs: 140 })
  h.abandonScheduledRender()
  await pending
  assert.equal(h.frames.size, 0)
  assert.equal(h.timers.size, 0)
  assert.equal(h.calls.length, 0)
})

test('teardown invalidates a running replay before it can republish the cleared editor', async () => {
  const h = harness()
  const blocked = h.block()
  const pending = h.render()
  h.frame()
  h.abandonScheduledRender()
  blocked.resolve()
  await pending
  assert.equal(h.composite.value, null)
  assert.equal(h.live.length, 0)
  assert.equal(h.caches.length, 0)
  assert.deepEqual(h.effects, [])
  assert.deepEqual(h.stepPreviews.value, { orphan: 'old' })
})

test('teardown also suppresses a running replay failure', async () => {
  const h = harness()
  const blocked = h.block()
  const pending = h.render()
  h.frame()
  h.abandonScheduledRender()
  blocked.reject(new Error('late decode failure'))
  await pending
  assert.deepEqual(h.errors, [])
})

test('a disposed editor cannot restart replay or accept late compositor thumbnails', async () => {
  const h = harness()
  h.dispose()
  await h.render()
  h.onStepPreview('edit', 'late-preview')
  assert.equal(h.frames.size, 0)
  assert.equal(h.calls.length, 0)
  assert.deepEqual(h.stepPreviews.value, { orphan: 'old' })
})

test('a current decode failure is reported and the queue remains usable', async () => {
  const h = harness()
  const blocked = h.block()
  const pending = h.render()
  h.frame()
  blocked.reject(new Error('current payload is missing'))
  await pending
  assert.deepEqual(h.errors, ['current payload is missing'])
  assert.equal(h.rendering.value, false)
  const retry = h.render()
  h.frame()
  await retry
  assert.equal(h.composite.value.value, 1)
})
