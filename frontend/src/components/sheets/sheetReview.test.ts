import assert from 'node:assert/strict'
import test from 'node:test'

import { isEmptyAnswer, parseLabels, parseRatingStyle, patchMediaReview, readMediaReview, sentReviewLayout, sentReviewMark } from './sheetReview.ts'

test('thumbs unless the sheet asks for stars', () => {
  assert.equal(parseRatingStyle(undefined), 'thumbs')
  assert.equal(parseRatingStyle('hearts'), 'thumbs')
  assert.equal(parseRatingStyle(' Stars '), 'stars')
  // Off is a section's choice, never the whole sheet's.
  assert.equal(parseRatingStyle('none'), 'thumbs')
  assert.equal(parseRatingStyle('none', true), 'none')
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

test('a sent rating reads its fields, or the words of an older review', () => {
  assert.deepEqual(sentReviewMark({ kind: 'rating', id: 'a', thumb: 'up' }), { thumb: 'up', stars: undefined, labels: undefined })
  assert.deepEqual(sentReviewMark({ kind: 'rating', id: 'a', text: '4 of 5 stars; labeled Hero, Alt' }),
    { thumb: undefined, stars: 4, labels: ['Hero', 'Alt'] })
  assert.deepEqual(sentReviewMark({ kind: 'rating', id: 'a', text: 'thumbs down' })?.thumb, 'down')
  assert.equal(sentReviewMark({ kind: 'rating', id: 'a', text: 'rating cleared' }), null)
  assert.deepEqual(sentReviewMark({ kind: 'stars', id: 'q', text: '3 of 5' }), { stars: 3 })
  assert.equal(sentReviewMark({ kind: 'comment', id: 'c', text: 'thumbs up from me' }), null)
})

test('many rated pictures become strips per verdict', () => {
  const rated = (n: number, thumb: 'up' | 'down') => ({ kind: 'rating', id: `m${n}`, thumb, media_id: n })
  const question = { kind: 'check', id: 'ok', question: 'Render?', text: 'yes' }
  const few = sentReviewLayout([question, ...[1, 2, 3].map(n => rated(n, 'up'))])
  assert.equal(few.rows.length, 4)
  assert.equal(few.groups.length, 0)

  const cleared = { kind: 'rating', id: 'gone', text: 'rating cleared' }
  const many = sentReviewLayout([question, cleared, ...[1, 2, 3, 4, 5, 6, 7, 8].map(n => rated(n, 'up')), rated(9, 'down'), rated(10, 'down'), rated(11, 'up')])
  assert.deepEqual(many.rows.map(row => row.id), ['ok', 'gone'])
  assert.deepEqual(many.groups.map(group => [group.title, group.items.length]), [['Kept', 9], ['Dropped', 2]])

  const stars = sentReviewLayout([...Array(11)].map((_, n) => ({ kind: 'rating', id: `s${n}`, stars: n % 2 ? 5 : 3 })))
  assert.deepEqual(stars.groups.map(group => [group.mark.stars, group.items.length]), [[5, 5], [3, 6]])
})
