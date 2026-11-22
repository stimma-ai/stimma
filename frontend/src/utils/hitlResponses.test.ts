import assert from 'node:assert/strict'
import test from 'node:test'
import { findHitlResponseItem, hitlResponseData } from './hitlResponses.ts'

const request = (id: number) => ({ id, item_type: 'hitl_request' })
const response = (id: number, meta: any) => ({ id, item_type: 'hitl_response', item_metadata: JSON.stringify(meta) })

test('an answer resolves only the card it names', () => {
  const a = request(1)
  const b = request(2)
  const items = [a, b, response(3, { approved: true, scope: 'once', request_item_id: 2 })]
  assert.equal(findHitlResponseItem(items, a), null)
  assert.deepEqual(hitlResponseData(findHitlResponseItem(items, b)), { approved: true, scope: 'once', request_item_id: 2 })
})

test('an answer saved without a request id resolves every earlier card', () => {
  const a = request(1)
  const b = request(2)
  const items = [a, b, response(3, { approved: false })]
  assert.equal(findHitlResponseItem(items, a)?.id, 3)
  assert.equal(findHitlResponseItem(items, b)?.id, 3)
})

test('plan approvals read the nested response', () => {
  const a = request(1)
  assert.deepEqual(hitlResponseData(findHitlResponseItem([a, response(2, { response: { approved: true } })], a)), { approved: true })
})
