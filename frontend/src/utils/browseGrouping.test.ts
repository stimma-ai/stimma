import assert from 'node:assert/strict'
import test from 'node:test'

import {
  FOLD_STALE_MS,
  PENDING_GROUP,
  clampTileMin,
  createGroupedReloadScheduler,
  groupByTriggerLabel,
  groupCountLabel,
  groupSub,
  groupTitle,
  groupingUnavailableReason,
  isGroupOpen,
  parseFolds,
  rememberFolds,
  serializeFolds,
  toSections,
  type AssetGroup,
} from './browseGrouping.ts'
import { formatDate } from './timeFormat.js'
import { useMediaList } from '../composables/useMediaList.ts'

const NOW = new Date(2026, 10, 9, 15, 0) // Mon 9 Nov 2026, local time
const iso = (d: Date) => d.toISOString()
const group = (over: Partial<AssetGroup> = {}): AssetGroup => ({
  key: 'g1', title: 'Neon koi', project_id: null, first_at: iso(NOW), last_at: iso(NOW),
  count: 6, total: 6, offset: 0, refs: [], ...over,
})

test('trigger labels name the choice, and None reads as no grouping', () => {
  assert.equal(groupByTriggerLabel('auto'), 'Group by auto')
  assert.equal(groupByTriggerLabel('month'), 'Group by month')
  assert.equal(groupByTriggerLabel('none'), 'No grouping')
})

test('similarity search and random order turn grouping off', () => {
  assert.equal(groupingUnavailableReason({ sortBy: 'created_desc' }), null)
  assert.equal(groupingUnavailableReason({ sortBy: 'similarity' }), 'Not available with similarity search')
  assert.equal(groupingUnavailableReason({ sortBy: 'created_desc', similarToText: 'koi' }), 'Not available with similarity search')
  assert.equal(groupingUnavailableReason({ sortBy: 'created_desc', similarTo: [3] }), 'Not available with similarity search')
  assert.equal(groupingUnavailableReason({ sortBy: 'random' }), 'Not available in random order')
})

test('the tile size stays in the slider range', () => {
  assert.equal(clampTileMin('abc'), 200)
  assert.equal(clampTileMin(50), 120)
  assert.equal(clampTileMin(999), 360)
  assert.equal(clampTileMin(240.4), 240)
})

test('day and month keys get client-side names', () => {
  assert.equal(groupTitle(group({ key: '2026-11-09', title: null }), 'day', NOW), 'Today')
  assert.equal(groupSub(group({ key: '2026-11-09', title: null }), 'day', NOW), formatDate(new Date(2026, 10, 9)))
  assert.equal(groupTitle(group({ key: '2026-11-08', title: null }), 'day', NOW), 'Yesterday')
  const old = groupTitle(group({ key: '2026-10-27', title: null }), 'day', NOW)
  assert.ok(old.endsWith(formatDate(new Date(2026, 9, 27))), old)
  assert.equal(groupSub(group({ key: '2026-10-27', title: null }), 'day', NOW), '')
  assert.equal(groupTitle(group({ key: '2026-03', title: null }), 'month', NOW), new Date(2026, 2, 1).toLocaleDateString(undefined, { month: 'long' }))
  assert.equal(groupSub(group({ key: '2026-03', title: null }), 'month', NOW), '2026')
  assert.equal(groupTitle(group({ key: PENDING_GROUP, title: null }), 'auto', NOW), 'New')
  assert.equal(groupTitle(group({ title: null }), 'auto', NOW), 'Untitled')
})

test('a session group shows its span', () => {
  const first = new Date(2026, 10, 3, 10)
  assert.equal(groupSub(group({ first_at: iso(first), last_at: iso(NOW) }), 'auto', NOW), `${formatDate(first)} → today`)
  assert.equal(groupSub(group({ first_at: iso(NOW), last_at: iso(NOW) }), 'theme', NOW), 'Today')
})

test('counts read "6 of 29" only when filters narrow the group', () => {
  assert.equal(groupCountLabel(group({ count: 6, total: 29 }), true), '6 of 29')
  assert.equal(groupCountLabel(group({ count: 6, total: 29 }), false), '6')
  assert.equal(groupCountLabel(group({ count: 29, total: 29 }), true), '29')
})

test('quiet groups start folded and a remembered choice wins', () => {
  const now = NOW.getTime()
  const fresh = group({ last_at: iso(new Date(now - FOLD_STALE_MS + 60000)) })
  const stale = group({ key: 'g2', last_at: iso(new Date(now - FOLD_STALE_MS - 60000)) })
  assert.equal(isGroupOpen(fresh, new Map(), now), true)
  assert.equal(isGroupOpen(stale, new Map(), now), false)
  assert.equal(isGroupOpen(stale, new Map([['g2', 'open']]), now), true)
  assert.equal(isGroupOpen(fresh, new Map([['g1', 'folded']]), now), false)
})

test('fold memory keeps the most recent choices, capped', () => {
  let folds = rememberFolds(new Map(), [['a', 'open'], ['b', 'folded'], ['c', 'open']], 3)
  folds = rememberFolds(folds, [['a', 'folded'], ['d', 'open']], 3)
  assert.deepEqual([...folds.keys()], ['c', 'a', 'd'])
  assert.equal(folds.get('a'), 'folded')
  assert.deepEqual(parseFolds(serializeFolds(folds)), folds)
  assert.deepEqual(parseFolds('{nope'), new Map())
})

test('a revisit points at its sources\' home group', () => {
  const groups = [
    group({ key: 'g9', title: 'Koi, again', offset: 0, count: 2, refs: [{ asset_id: 50, home_key: 'g1' }] }),
    group({ key: 'g1', title: 'Neon koi', offset: 2, count: 3, last_at: iso(new Date(2026, 9, 2, 12)) }),
  ]
  const [revisit] = toSections(groups, { groupBy: 'auto', folds: new Map(), now: NOW.getTime(), filtering: false })
  assert.deepEqual(revisit.home, { key: 'g1', label: `Neon koi, ${formatDate(new Date(2026, 9, 2, 12))}` })
})

test('the project dot shows outside Project grouping only', () => {
  const groups = [group({ project_id: 4 })]
  const name = () => 'Poster run'
  const [auto] = toSections(groups, { groupBy: 'auto', folds: new Map(), now: NOW.getTime(), filtering: false, projectName: name })
  const [byProject] = toSections(groups, { groupBy: 'project', folds: new Map(), now: NOW.getTime(), filtering: false, projectName: name })
  assert.equal(auto.projectName, 'Poster run')
  assert.equal(byProject.projectName, null)
})

function fakeClock() {
  let t = 0
  const timers: { at: number, fn: () => void, id: number }[] = []
  let nextId = 1
  return {
    now: () => t,
    setTimer: (fn: () => void, ms: number) => { const id = nextId++; timers.push({ at: t + ms, fn, id }); return id },
    clearTimer: (id: unknown) => { const i = timers.findIndex(x => x.id === id); if (i >= 0) timers.splice(i, 1) },
    async advance(ms: number) {
      const end = t + ms
      for (;;) {
        timers.sort((a, b) => a.at - b.at)
        const next = timers[0]
        if (!next || next.at > end) break
        timers.shift()
        t = next.at
        next.fn()
        await new Promise(resolve => setImmediate(resolve))
      }
      t = end
    },
  }
}

test('new assets reload 500 ms after the last one', async () => {
  const clock = fakeClock()
  let runs = 0
  const scheduler = createGroupedReloadScheduler({ run: async () => { runs++ }, ...clock })
  scheduler.request('created')
  await clock.advance(300)
  scheduler.request('created')
  await clock.advance(300)
  assert.equal(runs, 0)
  await clock.advance(300)
  assert.equal(runs, 1)
})

test('grouping progress reloads at most once every 3 s', async () => {
  const clock = fakeClock()
  const at: number[] = []
  const scheduler = createGroupedReloadScheduler({ run: async () => { at.push(clock.now()) }, ...clock })
  scheduler.request('groups')
  await clock.advance(600)
  for (let i = 0; i < 10; i++) {
    scheduler.request('groups')
    await clock.advance(200)
  }
  await clock.advance(5000)
  assert.deepEqual(at, [500, 3500])
})

test('a grouped reload with an unchanged total still reloads the pages', async () => {
  // Assets moved out of "New" into their groups: same total, same first item,
  // different order behind it. Sections and pages must both refresh. [Sol S5]
  const a = { asset_id: 1, file_hash: 'a', file_format: 'png' }
  const b = { asset_id: 2, file_hash: 'b', file_format: 'png' }
  const c = { asset_id: 3, file_hash: 'c', file_format: 'png' }
  let order = [a, b, c]
  const list = useMediaList({
    fetchMedia: async () => ({ items: order, total: order.length }),
    buildFilterParams: () => ({ group_by: 'auto' }),
    gridPageSize: 2,
  })
  await list.loadPage(0, 2)
  await list.loadPage(1, 2)
  assert.deepEqual([...list.loadedPages.value].sort(), ['0:2', '1:2'])
  order = [a, c, b]

  // The ungrouped path keeps the old pages: nothing it can see changed.
  assert.equal(await list.silentReload(), false)
  assert.equal(list.getItem(1)?.asset_id, 2)

  let sectionLoads = 0
  const scheduler = createGroupedReloadScheduler({
    run: async () => {
      await Promise.all([
        (async () => { sectionLoads++ })(),
        list.silentReload({ force: true }),
      ])
    },
    debounceMs: 0,
  })
  const version = list.cacheVersion.value
  scheduler.request('groups')
  await new Promise(resolve => setTimeout(resolve, 10))
  assert.equal(sectionLoads, 1)
  assert.equal(list.getItem(1)?.asset_id, 3)
  assert.deepEqual([...list.loadedPages.value], ['0:2'], 'other pages reload on demand')
  assert.ok(list.cacheVersion.value > version, 'the grid hears about it')
})
