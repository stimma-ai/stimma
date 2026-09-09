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
  assert.deepEqual(entries.map(e => e.id), [10, 20, 30, 40])
  assert.equal(entries[0].label, 'Generating · Option 1')
})

test('legacy previews and final displays deduplicate without reordering the chat', () => {
  const entries = collectChatMedia([
    { item_type: 'progress_display', item_metadata: JSON.stringify({ display_data: { previews: [2, 1] } }) },
    { item_type: 'media_display', item_metadata: { display_data: { rows: [{ output: { media_id: 1 } }, { output: { media_id: 2 } }] } } },
  ])
  assert.deepEqual(entries.map(e => e.id), [2, 1])
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
  assert.deepEqual(entries.map(e => e.id), [1, 2, 3, 4, 5, 6])
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
