import assert from 'node:assert/strict'
import test from 'node:test'

import { isEmptyAnswer, parseLabels, parseRatingStyle, patchMediaReview, readMediaReview } from './sheetReview.ts'

test('thumbs unless the sheet asks for stars', () => {
  assert.equal(parseRatingStyle(undefined), 'thumbs')
  assert.equal(parseRatingStyle('hearts'), 'thumbs')
  assert.equal(parseRatingStyle(' Stars '), 'stars')
})

test('labels are trimmed, unique and capped', () => {
  assert.deepEqual(parseLabels('Hero,  Needs   retouch ,Hero,,'), ['Hero', 'Needs retouch'])
  assert.equal(parseLabels('a,b,c,d,e,f,g,h,i,j').length, 8)
  assert.deepEqual(parseLabels(undefined), [])
})

test('a review keeps only what is set, so clearing it leaves nothing to send', () => {
  let review = patchMediaReview({}, { thumb: 'up' })
  review = patchMediaReview(review, { labels: ['Hero'] })
  assert.deepEqual(review, { thumb: 'up', labels: ['Hero'] })
  review = patchMediaReview(patchMediaReview(review, { thumb: null }), { labels: [] })
  assert.deepEqual(review, {})
  assert.equal(isEmptyAnswer(review), true)
  assert.equal(isEmptyAnswer({ stars: 3 }), false)
})

test('answers that are not a review read as none', () => {
  assert.deepEqual(readMediaReview(4), {})
  assert.deepEqual(readMediaReview({ thumb: 'sideways', stars: 9, labels: [] }), {})
  assert.deepEqual(readMediaReview({ thumb: 'down', stars: 2, labels: ['Soft'] }), { thumb: 'down', stars: 2, labels: ['Soft'] })
})
