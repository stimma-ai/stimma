import assert from 'node:assert/strict'
import test from 'node:test'
import { buildChatItemIndex } from '../src/utils/chatItemIndex.js'
import { createBoundedTextCache } from '../src/utils/boundedTextCache.js'

test('tool result index preserves forward lookup, retries, and first-result semantics', () => {
  const items = [
    { id: 1, item_type: 'tool_result', tool_call_id: 'a' },
    { id: 2, item_type: 'tool_call', tool_call_id: 'a' },
    { id: 3, item_type: 'tool_call', tool_call_id: 'b', parent_item_id: 2 },
    { id: 4, item_type: 'tool_result', tool_call_id: 'b', parent_item_id: 2 },
    { id: 5, item_type: 'tool_result', tool_call_id: 'a' },
    { id: 6, item_type: 'tool_result', tool_call_id: 'a' },
    { id: 7, item_type: 'tool_call', tool_call_id: 'a' },
    { id: 8, item_type: 'tool_call', tool_call_id: 'a' },
    { id: 9, item_type: 'tool_result', tool_call_id: 'a' },
    { id: 10, item_type: 'tool_call', tool_call_id: 'missing' },
  ]
  const index = buildChatItemIndex(items)
  assert.equal(index.toolResults.get(2).id, 5)
  assert.equal(index.toolResults.get(3).id, 4)
  assert.equal(index.toolResults.get(7), undefined)
  assert.equal(index.toolResults.get(8).id, 9)
  assert.equal(index.toolResults.get(10), undefined)
  assert.equal(index.firstToolCalls.get('a').id, 2)
  assert.deepEqual(index.children.get(2).map(item => item.id), [3, 4])
  assert.equal(index.childResults.get(2).get('b').id, 4)
  assert.equal(buildChatItemIndex(items.filter(item => item.id !== 5)).toolResults.get(2).id, 6)
})

test('render cache reuses results, distinguishes same-length edits and themes, and bounds retention', () => {
  const cache = createBoundedTextCache(2, 100)
  let calls = 0
  const render = key => cache.get(key, () => { calls++; return key.toUpperCase() })
  assert.equal(render('dark:a'), 'DARK:A')
  render('dark:a')
  assert.equal(calls, 1)
  render('dark:b')
  render('dark:a') // a is now most recently used
  render('light:a') // evicts b
  render('dark:a')
  assert.equal(calls, 3)
  render('dark:b')
  assert.equal(calls, 4)
  const large = 'x'.repeat(101)
  render(large)
  render(large)
  assert.equal(calls, 6, 'oversized results are not retained')
  cache.clear()
  render('dark:b')
  assert.equal(calls, 7)
  const small = createBoundedTextCache(10, 6)
  small.get('a', () => '1234')
  small.get('b', () => '12')
  assert.equal(small.get('a', () => 'new'), 'new', 'character budget evicts entries')
})
