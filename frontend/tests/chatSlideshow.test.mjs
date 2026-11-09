import assert from 'node:assert/strict'
import test from 'node:test'
import { collectChatMedia, progressPreviewTiles } from '../src/utils/chatMedia.js'
import { reconcileSlideshowCollection } from '../src/utils/slideshowCollection.js'

function batch(slots, title = 'Generating') {
  return { item_type: 'progress_display', item_metadata: { display_data: {
    title, status: 'in_progress', preview_slots: slots.map(id => ({
      media_ids: id ? [id] : [], status: id ? 'completed' : 'pending',
    })),
  } } }
}

test('out-of-order completion keeps numbered progress slots and chat batch order', () => {
  const partial = batch([null, 20])
  assert.deepEqual(progressPreviewTiles(partial.item_metadata.display_data).map(t => [t.option, t.mediaId]), [[1, null], [2, 20]])
  const entries = collectChatMedia([batch([10, 20]), batch([30, 40]), {
    item_type: 'assistant_message', message_text: 'Favorites: ![](media:40) ![](media_id=10)',
  }])
  assert.deepEqual(entries.map(e => e.id), [10, 20, 30, 40, 40, 10])
  assert.equal(entries[0].label, 'Generating · Option 1')
})

test('legacy previews and final displays each retain their recorded order', () => {
  const entries = collectChatMedia([
    { item_type: 'progress_display', item_metadata: JSON.stringify({ display_data: { previews: [2, 1] } }) },
    { item_type: 'media_display', item_metadata: { display_data: { rows: [{ output: { media_id: 1 } }, { output: { media_id: 2 } }] } } },
  ])
  assert.deepEqual(entries.map(e => e.id), [2, 1, 1, 2])
})

test('references, scored results, analysis and grids belong to the same chat sequence', () => {
  const entries = collectChatMedia([
    { item_type: 'media_display', item_metadata: { display_data: { rows: [{
      input: { input_image: { media_id: 1 }, ref_images: [{ media_id: 2 }] }, output: { media_id: 3 },
    }] } } },
    { item_type: 'scored_results', item_metadata: { scored_data: { items: [{ media_id: 3 }, { media_id: 4 }] } } },
    { item_type: 'analysis_result', item_metadata: { analysis_data: { media_id: 5 } } },
    { item_type: 'grid_generation', item_metadata: { display_data: { grid_media_id: 6 } } },
  ])
  assert.deepEqual(entries.map(e => e.id), [1, 2, 3, 3, 4, 5, 6])
})

test('an open slideshow retains its image as earlier slots and subsequent batches arrive', () => {
  const image = { id: 20 }
  const first = reconcileSlideshowCollection([20], [10, 20, 30], new Map([[0, image]]), 0)
  assert.equal(first.index, 1)
  assert.equal(first.cache.get(1), image)
  assert.equal(first.removed, false)
  const second = reconcileSlideshowCollection([10, 20, 30], [10, 20, 30, 40, 50], first.cache, first.index)
  assert.equal(second.index, 1)
  assert.equal(second.cache.get(1), image)
  assert.equal(second.cache.has(0), false)
})

test('same-count replacements invalidate old positions and removals select a surviving neighbor', () => {
  const next = reconcileSlideshowCollection([10, 20], [30, 20], new Map([[0, { id: 10 }], [1, { id: 20 }]]), 0)
  assert.equal(next.removed, true)
  assert.equal(next.cache.has(0), false)
  assert.equal(next.index, 0)
})

test('100 generated images followed by 10 favorites retain both appearances in chat order', () => {
  const favorites = [73, 4, 95, 12, 60, 21, 88, 32, 50, 9]
  const entries = collectChatMedia([
    { ...batch(Array.from({ length: 100 }, (_, i) => i + 1)), id: 1 },
    { id: 2, item_type: 'media_display', item_metadata: { display_data: {
      rows: favorites.map(id => ({ output: { media_id: id } })),
    } } },
  ])
  assert.equal(entries.length, 110)
  assert.deepEqual(entries.slice(100).map(e => e.id), favorites)
  assert.equal(new Set(entries.map(e => e.key)).size, 110)
  assert.equal(entries.findIndex(e => e.itemId === 2 && e.slot === 'row:0:output'), 100)
})

test('repeated images in one message have distinct positions, excluding hidden thinking', () => {
  const entries = collectChatMedia([{ id: 9, item_type: 'assistant_message',
    message_text: '<think>![](media:99)</think>`![](media:98)`\n\n```md\n![](media:97)\n```\n![](media:3) ![](media:3) ![](media:4)',
  }])
  assert.deepEqual(entries.map(e => e.id), [3, 3, 4])
  assert.deepEqual(entries.map(e => e.slot), ['message:0', 'message:1', 'message:2'])
  assert.equal(new Set(entries.map(e => e.key)).size, 3)
})

test('loading earlier slots or chat history preserves the selected repeated appearance and cache', () => {
  const initial = [
    { ...batch([null, 20]), id: 2 },
    { id: 3, item_type: 'assistant_message', message_text: '![](media:20) ![](media:20)' },
  ]
  const oldEntries = collectChatMedia(initial)
  const newEntries = collectChatMedia([
    { ...batch([20]), id: 1 }, { ...batch([10, 20]), id: 2 }, initial[1],
    { ...batch([20]), id: 4 },
  ])
  const images = oldEntries.map(e => ({ id: e.id, _slideshowItemKey: e.key }))
  const next = reconcileSlideshowCollection(oldEntries.map(e => e.key), newEntries.map(e => e.key),
    new Map(images.map((image, i) => [i, image])), 2)
  assert.equal(next.index, 4)
  assert.equal(next.cache.get(4), images[2])
  assert.equal(next.cache.get(3), images[1])
  assert.equal(next.cache.get(2), images[0])
  assert.equal(next.removed, false)
})


test('collector trims message text like the transcript renderer before parsing images', () => {
  const entries = collectChatMedia([{ id: 5, item_type: 'assistant_message',
    message_text: '    ![](media:3) ![](media:4)   ',
  }])
  assert.deepEqual(entries.map(e => e.id), [3, 4])
  assert.deepEqual(entries.map(e => e.slot), ['message:0', 'message:1'])
})

test('a slideshow opened from a collection hands back only that collection\'s rows', async () => {
  const { collectionRowOf } = await import('../src/utils/chatMedia.js')
  const entries = collectChatMedia([
    { id: 5, item_type: 'media_display', item_metadata: { display_data: { rows: [{ output: { media_id: 1 } }, { output: { media_id: 2 } }] } } },
    { id: 6, item_type: 'media_display', item_metadata: { display_data: { rows: [{ input: { input_image: { media_id: 1 } }, output: { media_id: 3 } }] } } },
  ])
  assert.deepEqual(entries.map(entry => collectionRowOf(entry, 5)), [0, 1, null, null])
  assert.deepEqual(entries.map(entry => collectionRowOf(entry, 6)), [null, null, null, 0])
  assert.equal(collectionRowOf(null, 5), null)
})

test('an artifact\'s slideshow is its versions, oldest first', async () => {
  const { artifactRevisionEntries } = await import('../src/utils/chatMedia.js')
  const entries = artifactRevisionEntries([
    { id: 11, revision_number: 1, media_id: 101 },
    { id: 12, revision_number: 2, media_id: 102, note: 'Warmer' },
    { id: 13, revision_number: 3, media_id: 103 },
  ])
  assert.deepEqual(entries.map(entry => entry.id), [101, 102, 103])
  assert.deepEqual(entries.map(entry => entry.key), ['artifact:11', 'artifact:12', 'artifact:13'])
  assert.equal(entries[1].label, 'v2 · Warmer')
  // ← from v3 is v2.
  assert.equal(entries[entries.findIndex(entry => entry.revisionId === 13) - 1].revisionId, 12)
})
