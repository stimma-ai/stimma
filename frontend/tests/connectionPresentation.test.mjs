import assert from 'node:assert/strict'
import test from 'node:test'
import { createRenderer, h, nextTick, onUnmounted, reactive, ref } from 'vue'
import { useConnectionPresentation } from '../src/composables/useConnectionPresentation.js'

// Render the connection gate with a stateful workspace: losing the component
// instance loses navigation, drafts, and sheets just as it does in the app.
const renderer = createRenderer({
  createElement: () => ({ children: [] }), createText: () => ({}), createComment: () => ({}),
  setText() {}, setElementText() {}, patchProp() {}, parentNode: node => node.parent,
  nextSibling: () => null,
  insert(node, parent) { node.parent = parent; parent.children.push(node) },
  remove(node) { node.parent.children.splice(node.parent.children.indexOf(node), 1) },
})

function fixture(t, kind) {
  const state = ref('connecting')
  const device = ref('server-a')
  let workspace, mounts = 0, unmounts = 0, gate
  const Workspace = { setup() {
    mounts++
    workspace = reactive({ path: ['home'], sheet: null, draft: '', scroll: 0 })
    onUnmounted(() => unmounts++)
    return () => h('main')
  } }
  const app = renderer.createApp({ setup() {
    gate = useConnectionPresentation(state, device, kind)
    return () => gate.showConnectionScreen.value ? h('connecting') : h(Workspace)
  } })
  app.mount({ children: [] })
  t.after(() => app.unmount())
  return {
    state, device, get workspace() { return workspace }, get mounts() { return mounts },
    get unmounts() { return unmounts }, get blocked() { return gate.showConnectionScreen.value },
    async transition(value) { state.value = value; await nextTick() },
  }
}

for (const kind of ['ios', 'android']) {
  test(`${kind} retains navigation, modal, draft and scroll across repeated recovery`, async t => {
    const f = fixture(t, kind)
    assert.equal(f.blocked, true)
    await f.transition('unreachable')
    assert.equal(f.mounts, 0, 'a failed cold connection cannot reveal the workspace')
    await f.transition('ready')
    Object.assign(f.workspace, { path: ['home', 'library', 'asset'], sheet: 'details', draft: 'unfinished', scroll: 800 })
    const original = f.workspace
    for (const state of ['connecting', 'ready', 'connecting', 'unreachable', 'connecting', 'unreachable', 'ready']) {
      await f.transition(state)
      assert.equal(f.state.value, state, 'transport status remains truthful')
      assert.equal(f.blocked, false)
      assert.equal(f.workspace, original)
      assert.deepEqual({ ...f.workspace }, { path: ['home', 'library', 'asset'], sheet: 'details', draft: 'unfinished', scroll: 800 })
    }
    assert.equal(f.mounts, 1)
    assert.equal(f.unmounts, 0)
  })
}

test('mobile server changes invalidate retained workspace even when switching back', async t => {
  const f = fixture(t, 'ios')
  await f.transition('ready')
  await f.transition('connecting')
  f.device.value = 'server-b'
  await nextTick()
  assert.equal(f.blocked, true)
  assert.equal(f.unmounts, 1)
  await f.transition('unreachable')
  f.device.value = 'server-a'
  await nextTick()
  assert.equal(f.blocked, true)
  await f.transition('ready')
  assert.equal(f.mounts, 2)
})

test('desktop keeps its existing connection gate', async t => {
  const f = fixture(t, 'electron')
  await f.transition('ready')
  await f.transition('connecting')
  assert.equal(f.blocked, true)
  assert.equal(f.unmounts, 1)
})
