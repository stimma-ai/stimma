import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { computed, reactive, ref, unref } from 'vue'

// Exercise the component's real update and projection functions with Vue refs,
// without mounting its media players or requiring a running backend.
const source = readFileSync(new URL('../src/components/SlideshowMode.vue', import.meta.url), 'utf8')
function componentFunction(name) {
  const start = source.indexOf(`function ${name}(`)
  assert.ok(start >= 0)
  const end = source.indexOf('\n}', start) + 2
  return source.slice(start, end)
}

function harness({ items = null, shared = false, viaSlideshowStore = false } = {}) {
  const original = { id: 7, asset_id: 7, media_id: 101, markers: [], tags: [], expires_at: 'later' }
  const cache = ref(new Map([[0, original]]))
  const props = { items }
  if (shared) {
    props.mediaList = {
      itemsCache: cache,
      updateItem(id, updates) {
        for (const [index, item] of cache.value) {
          if (item.asset_id === id) cache.value.set(index, { ...item, ...updates })
        }
      },
    }
    // useSlideshow keeps mediaList in a reactive() store, which unwraps its refs.
    if (viaSlideshowStore) props.mediaList = reactive({ mediaList: props.mediaList }).mediaList
  }
  const state = {
    props,
    itemsCache: shared ? ref(new Map()) : cache,
    assetHeadOverrides: ref(new Map([[7, { ...original }]])),
    directItemUpdates: ref(new Map()),
    displayItem: ref({ ...original }),
    sourceViewStack: ref([{ item: { ...original } }]),
    setViewStack: ref([{ items: [{ ...original }] }]),
    gridViewStack: ref([{ cellMap: new Map([['0,0', { resolved: { ...original } }]]) }]),
    itemPayloadId: item => item?.media_id ?? item?.id ?? null,
    itemIdentity: item => item?.asset_id ?? item?.id ?? null,
    assetIdOf: item => item.asset_id ?? item.id,
    hasAssetIdentity: item => item.asset_id != null,
    unref,
  }
  const functions = new Function(...Object.keys(state), `
    ${componentFunction('withAssetHeadOverride')}
    ${componentFunction('mediaListCache')}
    ${componentFunction('applyMediaPatchToLocalState')}
    return { resolve: withAssetHeadOverride, patch: applyMediaPatchToLocalState }
  `)(...Object.values(state))
  return { ...state, ...functions, cache, current: computed(() => functions.resolve(items?.[0] ?? cache.value.get(0))) }
}

for (const shared of [false, true]) {
  test(`marker add/remove updates the reactive control strip with ${shared ? 'shared' : 'chat page'} cache and refreshed head`, () => {
    const h = harness({ shared })
    assert.deepEqual(h.current.value.markers, [])
    h.patch(101, { markers: [{ id: 3 }], expires_at: null })
    assert.deepEqual(h.current.value.markers, [{ id: 3 }])
    assert.equal(h.current.value.expires_at, null)
    h.patch(101, { markers: [] })
    assert.deepEqual(h.current.value.markers, [])
  })
}

test('a marker toggled on a set member reaches the set view when mediaList comes through the slideshow store', () => {
  const h = harness({ shared: true, viaSlideshowStore: true })
  h.patch(101, { markers: [{ id: 3 }] })
  assert.deepEqual(h.setViewStack.value[0].items[0].markers, [{ id: 3 }])
  assert.deepEqual(h.cache.value.get(0).markers, [{ id: 3 }])
})

test('tags, prompts and expiry updates reach every slideshow projection', () => {
  const h = harness()
  const patch = { tags: ['curated'], extracted_prompt: 'Updated prompt', expires_at: null }
  h.patch(101, patch)
  for (const item of [h.current.value, h.displayItem.value, h.sourceViewStack.value[0].item,
    h.setViewStack.value[0].items[0], h.gridViewStack.value[0].cellMap.get('0,0').resolved]) {
    for (const [key, value] of Object.entries(patch)) assert.deepEqual(item[key], value)
  }
})

for (const asset of [false, true]) {
  test(`readonly direct ${asset ? 'asset' : 'media'} items reflect edits without mutating props`, () => {
    const original = Object.freeze({ id: 101, ...(asset ? { id: 7, asset_id: 7, media_id: 101 } : {}), markers: [] })
    const h = harness({ items: Object.freeze([original]) })
    assert.deepEqual(h.current.value.markers, [])
    h.patch(101, { markers: [{ id: 3 }] })
    assert.deepEqual(h.current.value.markers, [{ id: 3 }])
    assert.deepEqual(original.markers, [])
  })
}

test('a late edit updates the original asset after navigation without confusing asset and payload ids', () => {
  const h = harness({ shared: true })
  h.cache.value.set(1, { id: 101, asset_id: 101, media_id: 202, markers: [] })
  h.displayItem.value = h.cache.value.get(1)
  h.patch(101, { markers: [{ id: 3 }] })
  assert.deepEqual(h.cache.value.get(0).markers, [{ id: 3 }])
  assert.deepEqual(h.cache.value.get(1).markers, [])
  assert.deepEqual(h.displayItem.value.markers, [])
})

test('historical payload edits do not overwrite the current asset head', () => {
  const h = harness()
  h.assetHeadOverrides.value.set(7, { id: 7, asset_id: 7, media_id: 202, markers: [] })
  h.patch(101, { markers: [{ id: 3 }] })
  assert.deepEqual(h.current.value.markers, [])
  assert.equal(h.current.value.media_id, 202)
})

test('refreshing the displayed payload publishes metadata without restarting its loading state', () => {
  const displayItem = ref({ id: 7, file_hash: 'same', markers: [] })
  const mediaLoaded = ref(true)
  const apply = new Function('displayItem', 'mediaLoaded', 'itemIdentity', `
    ${componentFunction('applyDisplayItem')}
    return applyDisplayItem
  `)(displayItem, mediaLoaded, item => item?.id)
  apply({ id: 7, file_hash: 'same', markers: [{ id: 3 }] })
  assert.deepEqual(displayItem.value.markers, [{ id: 3 }])
  assert.equal(mediaLoaded.value, true)
})

// Delete acts on the image, never on the layout: a set drops the member and
// moves on, a grid keeps the empty cell.
function containerHarness({ items = [], index = 0, cells = null, row = 0, col = 0, viewingGrid = false, content = null } = {}) {
  const setViewStack = ref(items.length ? [{ items, setMediaId: 1 }] : [])
  const setViewIndex = ref(index)
  const gridViewStack = ref(cells ? [{ cellMap: new Map(cells), rows: 2, cols: 2, gridMediaId: 1 }] : [])
  const gridViewRow = ref(row)
  const gridViewCol = ref(col)
  const exits = { set: 0, grid: 0 }
  const state = {
    setViewStack, setViewIndex, gridViewStack, gridViewRow, gridViewCol,
    currentSetView: computed(() => setViewStack.value[setViewStack.value.length - 1] || null),
    currentGridView: computed(() => gridViewStack.value[gridViewStack.value.length - 1] || null),
    isViewingGrid: computed(() => viewingGrid && gridViewStack.value.length > 0),
    exitSetView: () => { exits.set++; setViewStack.value.pop() },
    exitGridView: () => { exits.grid++; gridViewStack.value.pop() },
    hasAssetIdentity: item => item.asset_id != null,
    itemIdentity: item => item?.asset_id ?? item?.id ?? null,
    itemPayloadId: item => item?.media_id ?? item?.id ?? null,
    // The reply lands after the stack entries were replaced by a head update.
    axios: { get: async () => {
      setViewStack.value = setViewStack.value.map(entry => ({ ...entry }))
      gridViewStack.value = gridViewStack.value.map(entry => ({ ...entry }))
      return { data: content }
    } },
  }
  const functions = new Function(...Object.keys(state), `
    ${componentFunction('getGridCellContent')}
    ${componentFunction('containerMemberKey')}
    ${componentFunction('setMembersFromContent')}
    ${componentFunction('dropSetMembers')}
    ${componentFunction('clearGridCells')}
    ${componentFunction('pruneContainerViewsForAssets')}
    async ${componentFunction('refreshContainerViews')}
    return { dropSetMembers, clearGridCells, prune: pruneContainerViewsForAssets, key: containerMemberKey, refresh: refreshContainerViews }
  `)(...Object.values(state))
  return { ...state, ...functions, exits }
}

const member = (id, linked = true) => (linked ? { id, asset_id: id, media_id: id + 100 } : { id: id + 100, media_id: id + 100, asset_id: null })

test('deleting the set member on screen shows the next one', () => {
  const h = containerHarness({ items: [member(1), member(2), member(3)], index: 1 })
  h.prune([2])
  assert.deepEqual(h.currentSetView.value.items.map(item => item.asset_id), [1, 3])
  assert.equal(h.setViewIndex.value, 1)
})

test('deleting the last set member shows the previous one, and an emptied set closes', () => {
  const h = containerHarness({ items: [member(1), member(2)], index: 1 })
  h.prune([2])
  assert.equal(h.setViewIndex.value, 0)
  assert.equal(h.currentSetView.value.items[0].asset_id, 1)
  h.prune([1])
  assert.equal(h.exits.set, 1)
  assert.equal(h.currentSetView.value, null)
})

test('a member removed elsewhere keeps the slide on screen', () => {
  const h = containerHarness({ items: [member(1), member(2), member(3)], index: 2 })
  h.prune([1])
  assert.equal(h.currentSetView.value.items[h.setViewIndex.value].asset_id, 3)
})

test('an embedded set member leaves by its payload, not an Asset id', () => {
  const embedded = member(5, false)
  const h = containerHarness({ items: [member(1), embedded, member(3)], index: 1 })
  h.prune([105])
  assert.equal(h.currentSetView.value.items.length, 3)
  h.dropSetMembers(item => h.key(item) === h.key(embedded))
  assert.deepEqual(h.currentSetView.value.items.map(item => item.asset_id), [1, 3])
  assert.equal(h.setViewIndex.value, 1)
})

test('a trashed grid cell empties without moving other cells, and the open cell returns to the grid', () => {
  const cells = [['0-0', { row: 0, col: 0, resolved: member(1) }], ['0-1', { row: 0, col: 1, resolved: member(2) }]]
  const h = containerHarness({ cells, row: 0, col: 1, viewingGrid: true })
  const original = h.currentGridView.value.cellMap
  h.prune([2])
  assert.equal(h.exits.grid, 1)
  const h2 = containerHarness({ cells, row: 0, col: 0, viewingGrid: true })
  h2.prune([2])
  assert.equal(h2.exits.grid, 0)
  const cellMap = h2.currentGridView.value.cellMap
  assert.equal(cellMap.get('0-1').resolved, null)
  assert.equal(cellMap.get('0-1').col, 1)
  assert.equal(cellMap.get('0-0').resolved.asset_id, 1)
  assert.equal(original.get('0-1').resolved.asset_id, 2, 'the grid overview’s own map is not mutated')
})

test('a refresh lands even after a head update replaced the set entry, keeping the slide on screen', async () => {
  const h = containerHarness({ items: [member(1), member(3)], index: 1, content: { items: [
    { member_id: 21, resolved: member(1) }, { member_id: 22, resolved: member(2) }, { member_id: 23, resolved: member(3) },
  ] } })
  await h.refresh()
  assert.deepEqual(h.currentSetView.value.items.map(item => item.member_id), [21, 22, 23])
  assert.equal(h.currentSetView.value.items[h.setViewIndex.value].asset_id, 3)
})

test('a grid refresh that empties the open cell returns to the grid', async () => {
  const cells = [['0-0', { row: 0, col: 0, resolved: member(1) }], ['0-1', { row: 0, col: 1, resolved: member(2) }]]
  const h = containerHarness({ cells, row: 0, col: 1, viewingGrid: true, content: { cells: [{ row: 0, col: 0, resolved: member(1) }] } })
  await h.refresh()
  assert.equal(h.exits.grid, 1)
})

test('trashing the last member of an open set does not count against a list that only holds the set', () => {
  const h = containerHarness({ items: [member(1)], index: 0 })
  const counted = []
  const props = { isTrashView: false, mediaList: { findIndex: id => (id === 50 ? 0 : -1), removeItems: ids => counted.push(...ids) } }
  const deps = {
    props, getCurrentProfileId: () => 'default', deletingItemIds: ref(new Set()), localRemovedIds: ref(new Set()),
    containerMemberRemovals: new Set(), pruneContainerViewsForAssets: h.prune,
    applyRemovalToCount: n => counted.push(`count:${n}`), handleRemovedMediaIdsLocally: () => {},
  }
  const handle = new Function(...Object.keys(deps), `${componentFunction('handleAssetsRemovedWs')}; return handleAssetsRemovedWs`)(...Object.values(deps))
  handle({ asset_id: 1 })
  assert.equal(h.exits.set, 1)
  assert.deepEqual(counted, [])
  handle({ asset_id: 50 })
  assert.deepEqual(counted, [50, 'count:1'])
})
