import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { stripTypeScriptTypes } from 'node:module'
import test from 'node:test'
import { computed, ref } from 'vue'

// Exercise the editor's actual render queue without mounting its unrelated
// panels or contacting the backend. Only canvas replay and UI sinks are faked.
const view = await readFile(new URL('../src/views/ImageEditorView.vue', import.meta.url), 'utf8')
const queue = view.slice(view.indexOf('type RenderOptions ='), view.indexOf('/** Fit the composite into the viewport'))
const input = view.slice(view.indexOf('async function renderCropInput('), view.indexOf('/** The crop rectangle the overlay draws'))
const code = stripTypeScriptTypes(`${queue}\n${input}`)
const createQueue = new Function('deps', `with (deps) { ${code}; return { render }; }`)

function harness() {
  const step = (id, kind = 'adjust') => ({ id, enabled: true, class: 'parametric', exec: { kind }, params: {} })
  const stack = { doc: ref({ base: { file_hash: 'base' }, canvas: { width: 240, height: 120 },
    edits: [step('below'), step('crop', 'crop'), step('above')] }) }
  const family = ref('crop'), cropOpId = ref('crop'), cropInput = ref(null)
  let gate = null
  const calls = []
  const compositor = {
    failedOpIds: new Set(), maskDebt: new Map(),
    async renderUpTo(doc, index) {
      const snapshot = structuredClone(doc)
      calls.push(snapshot)
      if (gate) { const wait = gate; gate = null; await wait }
      return { edits: snapshot.edits.slice(0, index), canvas: snapshot.canvas }
    },
    async render(doc) { return { edits: doc.edits } },
  }
  const noop = () => {}
  const deps = { stack, family, cropOpId, cropInput, compositor, computed,
    baseInfo: ref({}), composite: ref(null), annotationOverlayActive: ref(false),
    visibleAnnotateOps: ref([]), stepPreviews: ref({}), rendering: ref(false),
    maskDebtByOp: ref({}), error: ref(null), looksOpen: ref(false), props: { assetId: '1' },
    publishEditorLivePreview: noop, scheduleHeadCache: noop, syncSelectionGeometry: noop,
    paint: noop, samplePalette: noop, renderLookThumbs: noop,
    bufferedStepPreviews: null, emitPreviews: true,
    requestAnimationFrame: cb => setTimeout(cb, 0), cancelAnimationFrame: clearTimeout,
  }
  const queue = createQueue(deps)
  return { ...deps, ...queue, calls, block() {
    let release
    gate = new Promise(resolve => { release = resolve })
    return release
  } }
}

test('crop stays live on visibility, params, reorder, removal and undo', async () => {
  const h = harness()
  await h.render()
  assert.deepEqual(h.cropInput.value.edits.map(op => op.id), ['below'])
  h.stack.doc.value.edits[0].enabled = false
  await h.render()
  assert.equal(h.cropInput.value.edits[0].enabled, false)
  h.stack.doc.value.edits[0].params = { brightness: 10 }
  await h.render()
  assert.deepEqual(h.cropInput.value.edits[0].params, { brightness: 10 })
  // A row moved below the crop becomes part of its input; rows above don't.
  h.stack.doc.value.edits.unshift(h.stack.doc.value.edits.pop())
  await h.render()
  assert.deepEqual(h.cropInput.value.edits.map(op => op.id), ['above', 'below'])
  const previous = structuredClone(JSON.parse(JSON.stringify(h.stack.doc.value)))
  h.stack.doc.value.edits.splice(1, 1)
  await h.render()
  assert.deepEqual(h.cropInput.value.edits.map(op => op.id), ['above'])
  h.stack.doc.value = previous
  await h.render()
  assert.deepEqual(h.cropInput.value.edits.map(op => op.id), ['above', 'below'])
  // Before a crop step exists, its input is the complete current stack.
  h.cropOpId.value = null
  await h.render()
  assert.equal(h.cropInput.value.edits.length, 3)
  assert.equal(h.error.value, null)
})

test('an in-flight crop replay cannot publish over a newer sidebar edit', async () => {
  const h = harness()
  await h.render()
  const initial = h.cropInput.value
  const release = h.block()
  const pending = h.render()
  while (h.calls.length < 2) await new Promise(resolve => setTimeout(resolve, 0))
  h.stack.doc.value.edits[0].enabled = false
  const latest = h.render()
  assert.equal(h.cropInput.value, initial)
  release()
  await Promise.all([pending, latest])
  assert.equal(h.calls[1].edits[0].enabled, true)
  assert.equal(h.cropInput.value.edits[0].enabled, false)
  assert.equal(h.error.value, null)
})

test('crop replay uses the full document and drops a preview after leaving Crop', async () => {
  const h = harness()
  h.annotationOverlayActive.value = true
  h.visibleAnnotateOps.value = [{ id: 'below' }]
  await h.render()
  assert.deepEqual(h.cropInput.value.edits.map(op => op.id), ['below'])
  assert.deepEqual(h.composite.value.edits.map(op => op.id), ['crop', 'above'])
  const initial = h.cropInput.value
  const release = h.block()
  const pending = h.render()
  while (h.calls.length < 2) await new Promise(resolve => setTimeout(resolve, 0))
  h.family.value = 'paint'
  h.cropOpId.value = null
  release()
  await pending
  assert.equal(h.cropInput.value, initial)
})
