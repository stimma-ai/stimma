import assert from 'node:assert/strict'
import test from 'node:test'
import { createInitialMessageConsumer } from './initialMessage.ts'

test('mount and activation on the same route send the first message once', () => {
  const consume = createInitialMessageConsumer()
  const query = { initialMessage: 'make a cat', attachmentIds: '4,5' }
  assert.deepEqual(consume(7, query), { text: 'make a cat', attachmentIds: [4, 5] })
  assert.equal(consume(7, query), null)
  assert.equal(consume(7, { ...query }), null)
})

test('the consumer re-arms once the query has been cleared', () => {
  const consume = createInitialMessageConsumer()
  assert.ok(consume(7, { initialMessage: 'again' }))
  assert.equal(consume(7, {}), null)
  assert.deepEqual(consume(7, { initialMessage: 'again' }), { text: 'again', attachmentIds: [] })
})

test('a different chat or message is not suppressed', () => {
  const consume = createInitialMessageConsumer()
  assert.ok(consume(7, { initialMessage: 'one' }))
  assert.ok(consume(8, { initialMessage: 'one' }))
  assert.ok(consume(8, { initialMessage: 'two' }))
  assert.equal(consume(8, { initialMessage: '' }), null)
})
