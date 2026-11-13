import assert from 'node:assert/strict'
import test from 'node:test'

import { cleanSuggestions, joinFor, MAX_CHIPS, MAX_PHOTO_CHIPS, shownAdds, slotCovers, type SuggestedAdd } from './promptSuggestions.ts'

const lens: SuggestedAdd = { name: 'lens', label: 'lens', kind: 'list', lists: ['camera.lens'] }
const angle: SuggestedAdd = { name: 'camera angle', label: 'angle', kind: 'list', lists: ['camera.angle'] }
const light: SuggestedAdd = { name: 'light', label: 'light', kind: 'light', lists: ['lighting.natural'] }
const grade: SuggestedAdd = { name: 'color grade', label: 'color grade', kind: 'list', lists: ['camera.color_grade'] }

test('a /suggest answer keeps a photography add\'s kind and lists, and plain adds as they were', () => {
  const got = cleanSuggestions({
    vary: [{ from: 0, to: 3, text: 'cat' }, { from: 'x' }],
    adds: [{ name: 'background' }, { ...lens, lists: ['camera.lens', 4] }, { name: '' }, { name: 'sky', kind: 7 }],
  })
  assert.deepEqual(got.vary, [{ from: 0, to: 3, text: 'cat' }])
  assert.deepEqual(got.adds, [{ name: 'background', label: 'background' }, lens, { name: 'sky', label: 'sky' }])
  assert.deepEqual(cleanSuggestions(null), { vary: [], adds: [] })
})

test('an add keeps where it goes only when both its words and its insert came back', () => {
  const got = cleanSuggestions({ adds: [
    { name: 'light', after: 'at dusk', insert: ', lit by <light>' },
    { name: 'sky', after: 'at dusk' },
    { name: 'pet', after: 3, insert: ', <pet>' },
  ] })
  assert.deepEqual(got.adds, [
    { name: 'light', label: 'light', after: 'at dusk', insert: ', lit by <light>' },
    { name: 'sky', label: 'sky' },
    { name: 'pet', label: 'pet' },
  ])
})

test('a slot read as a photography add\'s kind, or drawing from one of its lists, covers it', () => {
  const read = { kinds: ['person', 'light'], lists: ['person.age', 'camera.angle'] }
  assert.equal(slotCovers(light, read), true)
  assert.equal(slotCovers(grade, read), false)
  assert.equal(slotCovers(grade, { kinds: ['list'], lists: ['camera.color_grade'] }), true)
})

test('the camera is covered part by part', () => {
  // A slot on the angle list covers "+ angle" only: the lens is still offered.
  const angleSlot = { kinds: ['person', 'list'], lists: ['person.age', 'camera.angle'] }
  assert.equal(slotCovers(angle, angleSlot), true)
  assert.equal(slotCovers(lens, angleSlot), false)
  // A whole camera covers the parts its details draw from, not the kind alone.
  const camera = { kinds: ['camera'], lists: ['camera.shot_size', 'camera.lens'] }
  assert.equal(slotCovers(lens, camera), true)
  assert.equal(slotCovers(angle, camera), false)
  assert.equal(slotCovers(angle, { kinds: ['camera'], lists: [] }), false)
  // List ids compare structurally: a list under the add's list counts, a sibling with a longer name doesn't.
  assert.equal(slotCovers({ ...light, lists: ['lighting'] }, { kinds: ['list'], lists: ['lighting.studio'] }), true)
  assert.equal(slotCovers(lens, { kinds: ['list'], lists: ['camera.lens_flare'] }), false)
})

test('the model\'s named light is covered like the plain one', () => {
  const windowLight: SuggestedAdd = { name: 'window light', label: 'window light', kind: 'light', lists: ['lighting.natural'] }
  assert.equal(slotCovers(windowLight, { kinds: ['light'], lists: [] }), true)
  assert.equal(slotCovers(windowLight, { kinds: ['list'], lists: ['camera.lens'] }), false)
})

test('a list kind alone covers nothing, nor does anything before the slots are read', () => {
  assert.equal(slotCovers(grade, { kinds: ['list'], lists: ['person.age'] }), false)
  assert.equal(slotCovers(light, null), false)
  assert.equal(slotCovers({ name: 'light', label: 'light' }, { kinds: ['light'], lists: [] }), false)  // the model's own add
})

test('a join is sent only for the exact prompt Suggest answered, even when its words survive an edit', () => {
  const answer = { text: 'a cat on a porch', suggestions: { vary: [], adds: [
    { name: 'light', label: 'light', after: 'on a porch', insert: ', lit by <light>' },
    { name: 'sky', label: 'sky' },
  ] } }
  assert.deepEqual(joinFor(answer, 'light', 'a cat on a porch'),
    { after: 'on a porch', insert: ', lit by <light>', suggested_for: 'a cat on a porch' })
  assert.equal(joinFor(answer, 'light', 'a cat on a porch, lit by candlelight'), null)
  assert.equal(joinFor(answer, 'sky', 'a cat on a porch'), null)
  assert.equal(joinFor(null, 'light', 'a cat on a porch'), null)
})

test('covered parts are hidden before the cap, so the next part moves up', () => {
  const part = (name: string, list: string): SuggestedAdd => ({ name, label: name, kind: 'list', lists: [list] })
  const filmLook = part('film look', 'camera.film_look')
  const framing = part('framing', 'camera.shot_size')
  const own = [{ name: 'weather', label: 'weather' }, { name: 'season', label: 'season' }]
  const adds = [...own, light, angle, lens, filmLook, framing]
  const names = (got: SuggestedAdd[]) => got.map(a => a.name)
  const none = new Set<string>()
  assert.equal(MAX_PHOTO_CHIPS, 3)
  assert.equal(MAX_CHIPS, 5)
  // Nothing read yet: the best three parts.
  assert.deepEqual(names(shownAdds(adds, null, none)), ['weather', 'season', 'light', 'camera angle', 'lens'])
  // A slot read on the angle list hides the angle, and the film look moves up.
  const read = { kinds: ['person', 'list'], lists: ['person.age', 'camera.angle'] }
  assert.deepEqual(names(shownAdds(adds, read, none)), ['weather', 'season', 'light', 'lens', 'film look'])
  // A slot of the same words hides it too, before the cap.
  assert.deepEqual(names(shownAdds(adds, read, new Set(['light']))), ['weather', 'season', 'lens', 'film look', 'framing'])
  // Five chips in all, whatever the mix.
  const many = [...own, { name: 'sky', label: 'sky' }, ...adds.slice(2)]
  assert.deepEqual(names(shownAdds(many, null, none)), ['weather', 'season', 'sky', 'light', 'camera angle'])
})
