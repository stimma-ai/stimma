// A chat's image collection borrows the artifact panel without disturbing what
// the panel remembers for this chat or the next one.
import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { nextTick, ref } from 'vue'
import { createServer } from 'vite'

const store = new Map()
globalThis.localStorage = {
  getItem: key => (store.has(key) ? store.get(key) : null),
  setItem: (key, value) => store.set(key, String(value)),
  removeItem: key => store.delete(key),
}

globalThis.sessionStorage = globalThis.localStorage
globalThis.window = globalThis
globalThis.location = new URL('http://stimma.test/')
globalThis.addEventListener ??= () => {}

const server = await createServer({
  configFile: false, logLevel: 'error', appType: 'custom', optimizeDeps: { noDiscovery: true },
  root: fileURLToPath(new URL('..', import.meta.url)), server: { middlewareMode: true, ws: false },
})
const { useArtifactStage } = await server.ssrLoadModule('/src/composables/useArtifactStage.ts')
const { makeStorageKey } = await server.ssrLoadModule('/src/utils/storageKeys')
test.after(() => server.close())

const stateKey = id => makeStorageKey('chat', id, 'artifact_stage_state')

test('switching chats with a collection open leaves the next chat its saved panel', async () => {
  const saved = JSON.stringify({ open: true, file: { name: 'next.txt', path: 'next.txt', size: 1 }, dismissedAssetId: null })
  store.set(stateKey(2), saved)
  const chatId = ref(1)
  const stage = useArtifactStage(chatId, ref([]))
  stage.openCollection(7)
  chatId.value = 2
  await nextTick()
  assert.equal(stage.collectionItemId.value, null)
  assert.equal(JSON.parse(store.get(stateKey(2))).file.name, 'next.txt')
})

test('an artifact chip takes the panel back from a collection', async () => {
  const stage = useArtifactStage(ref(3), ref([]))
  await stage.openOnAsset(5).catch(() => {}) // the asset id sticks even with no backend
  stage.openCollection(7)
  stage.selectFromChip({ asset_id: 5, revision_id: 1, revision_number: 1 })
  assert.equal(stage.collectionItemId.value, null)
  assert.equal(stage.stageOpen.value, true)
})

test('closing a collection brings back what the panel showed, and a reload forgets it', async () => {
  const chatId = ref(4)
  const stage = useArtifactStage(chatId, ref([]))
  stage.openCollection(7)
  assert.equal(JSON.parse(store.get(stateKey(4))).open, false)
  stage.close()
  assert.equal(stage.stageOpen.value, false)
  stage.openFile({ name: 'a.txt', path: 'a.txt', size: 1 })
  stage.openCollection(7)
  assert.equal(stage.stageOpen.value, true)
  stage.closeCollection()
  assert.equal(stage.stageOpen.value, true)
  assert.equal(stage.workspaceFile.value.name, 'a.txt')
})

// A revision load answers after the person has moved on: it must not paint the
// old chat's artifact into the new one, nor reopen a panel they closed.
const axios = (await import('axios')).default

function deferredRevisions() {
  const pending = []
  const original = axios.get
  axios.get = url => {
    const match = String(url).match(/assets\/(\d+)\/revisions/)
    if (!match) return original.call(axios, url)
    return new Promise(resolve => pending.push({ id: Number(match[1]), resolve }))
  }
  const answer = (id) => {
    const entry = pending.find(item => item.id === id)
    pending.splice(pending.indexOf(entry), 1)
    entry.resolve({ data: { asset: { id, title: `Asset ${id}`, current_revision_id: id * 10 }, revisions: [{ id: id * 10, revision_number: 1, media_id: id * 100 }] } })
  }
  return { pending, answer, restore: () => { axios.get = original } }
}

test('a revision load that lands after a chat switch is dropped', async t => {
  const api = deferredRevisions()
  t.after(api.restore)
  const chatId = ref(11)
  const stage = useArtifactStage(chatId, ref([]))
  const opening = stage.openOnAsset(8)
  await nextTick()
  assert.equal(api.pending.length, 1)
  assert.equal(stage.loading.value, true)
  chatId.value = 12
  await nextTick()
  assert.equal(stage.loading.value, false)
  api.answer(8)
  await opening
  assert.equal(stage.asset.value, null)
  assert.deepEqual(stage.revisions.value, [])
  assert.equal(stage.stageOpen.value, false)
  assert.equal(stage.loading.value, false)
})

test('closing the panel while an artifact loads keeps it closed', async t => {
  const api = deferredRevisions()
  t.after(api.restore)
  const stage = useArtifactStage(ref(13), ref([]))
  const opening = stage.openOnAsset(9)
  await nextTick()
  stage.close()
  api.answer(9)
  await opening
  assert.equal(stage.stageOpen.value, false)
})

test('an older asset load cannot overwrite a newer one', async t => {
  const api = deferredRevisions()
  t.after(api.restore)
  const stage = useArtifactStage(ref(14), ref([]))
  const first = stage.openOnAsset(3)
  await nextTick()
  const second = stage.openOnAsset(4)
  await nextTick()
  api.answer(4)
  await second
  assert.equal(stage.asset.value.id, 4)
  api.answer(3)
  await first
  assert.equal(stage.asset.value.id, 4)
  assert.equal(stage.viewedRevision.value.media_id, 400)
  assert.equal(stage.loading.value, false)
})
