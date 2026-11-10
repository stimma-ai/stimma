import assert from 'node:assert/strict'
import test from 'node:test'

import { DOCK_SIZES, fitDock, foldOpenWindows, sanitizeDock, type DockEntry } from './chatDockState.ts'

const entry = (chatId: number, win: 'row' | 'open', at: number): DockEntry => ({ chatId, win, at, initial: null })

test('a stored dock keeps one entry per chat and drops junk', () => {
  const out = sanitizeDock({ entries: [
    { chatId: 3, win: 'open', at: 5, initial: { text: 'upscale', mediaIds: [1, 'x', 2] } },
    { chatId: 3, win: 'row', at: 6 },
    { chatId: 'nope' },
    { chatId: 4, win: 'weird', at: 7 },
  ] }, 100)
  assert.deepEqual(out, [
    { chatId: 3, win: 'open', at: 5, initial: { text: 'upscale', mediaIds: [1, 2] } },
    { chatId: 4, win: 'row', at: 7, initial: null },
  ])
  assert.deepEqual(sanitizeDock(null), [])
  assert.deepEqual(sanitizeDock({ entries: 'no' }), [])
})

test('opening a third window folds the oldest open one to a row', () => {
  const entries = [entry(1, 'open', 1), entry(2, 'open', 2), entry(3, 'open', 3)]
  const { entries: next, folded } = foldOpenWindows(entries, 3, null)
  assert.deepEqual(folded, [1])
  assert.deepEqual(next.map(e => [e.chatId, e.win]), [[1, 'row'], [2, 'open'], [3, 'open']])
})

test('the chat on screen full size does not count against open windows', () => {
  const entries = [entry(1, 'open', 1), entry(2, 'open', 2), entry(3, 'open', 3)]
  const { folded } = foldOpenWindows(entries, 3, 1)
  assert.deepEqual(folded, [])
})

test('nothing folds while there is room', () => {
  const entries = [entry(1, 'open', 1), entry(2, 'row', 2)]
  const { entries: next, folded } = foldOpenWindows(entries, 2, null)
  assert.deepEqual(folded, [])
  assert.equal(next, entries)
})

test('rows narrow before anything folds into +N more', () => {
  const { open, row, narrowRow, gap, edge } = DOCK_SIZES
  // Two windows and one row: the row only fits narrow.
  const width = edge * 2 + 2 * (open + gap) + narrowRow + gap + 4
  const layout = fitDock([{ chatId: 1, win: 'open' }, { chatId: 2, win: 'open' }, { chatId: 3, win: 'row' }], width)
  assert.equal(layout.rowWidth, narrowRow)
  assert.deepEqual(layout.shown, [1, 2, 3])
  assert.deepEqual(layout.hidden, [])
  // Plenty of room: rows keep their width.
  assert.equal(fitDock([{ chatId: 1, win: 'row' }], 2000).rowWidth, row)
})

test('what does not fit goes into +N more, oldest first', () => {
  const visible = [1, 2, 3, 4, 5, 6].map(chatId => ({ chatId, win: 'row' as const }))
  const layout = fitDock(visible, 700)
  assert.ok(layout.shown.length < visible.length)
  assert.deepEqual([...layout.shown, ...layout.hidden], [1, 2, 3, 4, 5, 6])
  assert.equal(layout.shown[0], 1)
})

test('the newest always shows, even in a narrow space', () => {
  const layout = fitDock([{ chatId: 9, win: 'open' }, { chatId: 8, win: 'row' }], 100)
  assert.deepEqual(layout.shown, [9])
  assert.deepEqual(layout.hidden, [8])
})
