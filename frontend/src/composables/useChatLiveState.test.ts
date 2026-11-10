import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { _resetChatLiveStateForTests, useChatLiveState } from './useChatLiveState.ts'

// Vue warns about onUnmounted outside a component; that's fine here.
const quiet = () => {
  const warn = console.warn
  console.warn = () => {}
  return () => { console.warn = warn }
}

test('two views of one chat share its queue and sending flag', () => {
  _resetChatLiveStateForTests()
  const restore = quiet()
  const full = useChatLiveState(ref(7))
  const small = useChatLiveState(ref(7))
  restore()
  full.messageQueue.value = [{ id: 'q1', text: 'then crop', attachments: [], mode: 'queue', steering: false }]
  assert.equal(small.messageQueue.value.length, 1)
  small.sending.value = true
  assert.equal(full.sending.value, true)
})

test('only the view in sight owns the queue; out of sight steps back', () => {
  _resetChatLiveStateForTests()
  const restore = quiet()
  const full = useChatLiveState(ref(7))
  const small = useChatLiveState(ref(7))
  restore()
  full.claim()
  small.stepBack()
  assert.equal(full.isOwner.value, true)
  assert.equal(small.isOwner.value, false)
  // The full view goes into the cache and the dock window opens.
  full.stepBack()
  small.claim()
  assert.equal(small.isOwner.value, true)
  assert.equal(full.isOwner.value, false)
  // The dock window closes: the cached full view still drains.
  small.release()
  assert.equal(full.isOwner.value, true)
  assert.equal(full.heldElsewhere(7), false)
})

test('a view switching chats takes its hold with it', async () => {
  _resetChatLiveStateForTests()
  const restore = quiet()
  const id = ref<number | null>(1)
  const view = useChatLiveState(id)
  const other = useChatLiveState(ref(1))
  restore()
  view.claim()
  other.stepBack()
  id.value = 2
  await Promise.resolve()
  assert.equal(view.isOwner.value, true)
  assert.equal(other.isOwner.value, true)
  assert.equal(view.heldElsewhere(1), true)
})
