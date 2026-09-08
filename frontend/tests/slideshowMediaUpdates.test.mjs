import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { computed, ref } from 'vue'

// Exercise the component's real update and projection functions with Vue refs,
// without mounting its media players or requiring a running backend.
const source = readFileSync(new URL('../src/components/SlideshowMode.vue', import.meta.url), 'utf8')
function componentFunction(name) {
  const start = source.indexOf(`function ${name}(`)
  assert.ok(start >= 0)
  const end = source.indexOf('\n}', start) + 2
  return source.slice(start, end)
}

function harness({ items = null, shared = false } = {}) {
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
  }
  const functions = new Function(...Object.keys(state), `
    ${componentFunction('withAssetHeadOverride')}
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

test('tags, captions and expiry updates reach every slideshow projection', () => {
  const h = harness()
  const patch = { tags: ['curated'], vlm_caption: 'Updated caption', expires_at: null }
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
