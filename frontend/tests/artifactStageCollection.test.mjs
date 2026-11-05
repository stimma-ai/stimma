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
