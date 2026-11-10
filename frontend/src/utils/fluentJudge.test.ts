import test from 'node:test'
import assert from 'node:assert/strict'
import { judgeWaitLabel, tellsUnjudged, unjudgedMessage, unjudgedNote, waitForJudge, type JudgeState } from './fluentJudge.ts'

test('the tile says Getting Fluent ready, with the percent once bytes arrive', () => {
  assert.equal(judgeWaitLabel({ status: 'downloading', waiting: true, percent: 62 }, 'Fluent'), 'Getting Fluent ready… 62%')
  assert.equal(judgeWaitLabel({ status: 'downloading', waiting: true, percent: 0 }, 'Fluent'), 'Getting Fluent ready…')
  assert.equal(judgeWaitLabel({ status: 'loading', waiting: true }, 'Fluent'), 'Getting Fluent ready…')
  assert.equal(judgeWaitLabel(null, 'Cast'), 'Getting Cast ready…')
})

test('the user is told only when the check can’t be had, never under Privacy Lockdown', () => {
  assert.equal(tellsUnjudged({ status: 'ready' }), false)
  assert.equal(tellsUnjudged({ status: 'downloading', waiting: true }), false)
  assert.equal(tellsUnjudged({ status: 'unavailable', unjudged: 'unavailable' }), true)
  assert.equal(tellsUnjudged({ status: 'downloading', unjudged: 'stalled' }), true)
  assert.equal(tellsUnjudged({ status: 'error', unjudged: 'error' }), true)
  assert.equal(tellsUnjudged({ status: 'lockdown', unjudged: 'lockdown' }), false)
  assert.match(unjudgedMessage('Fluent'), /^Fluent couldn’t finish getting ready/)
})

test('Generation details notes an unchecked image, and only that', () => {
  assert.equal(unjudgedNote({ fix: { judge: 'v', rounds: [] } }, 'Fluent'), null)
  assert.equal(unjudgedNote({ draws: [] }, 'Fluent'), null)
  assert.equal(unjudgedNote(null, 'Fluent'), null)
  assert.equal(unjudgedNote({ fix: { skipped: 'unavailable' } }, 'Fluent'), 'Choices weren’t checked to fit together: Fluent wasn’t ready.')
  assert.equal(unjudgedNote({ fix: { skipped: 'lockdown' } }, 'Fluent'), 'Choices weren’t checked to fit together: Privacy Lockdown is on.')
})

function server(states: JudgeState[]) {
  const asked: boolean[] = []
  return {
    asked,
    fetch: async (start: boolean) => { asked.push(start); return states[Math.min(asked.length - 1, states.length - 1)] },
  }
}
const noSleep = async () => {}

test('a run waits while the server says so, showing each state, then runs judged', async () => {
  const s = server([
    { status: 'downloading', waiting: true, percent: 10 },
    { status: 'downloading', waiting: true, percent: 62 },
    { status: 'loading', waiting: true },
    { status: 'ready', waiting: false },
  ])
  const shown: string[] = []
  const out = await waitForJudge({ fetch: s.fetch, onWaiting: st => shown.push(judgeWaitLabel(st, 'Fluent')), cancelled: () => false, sleep: noSleep })
  assert.equal(out.outcome, 'ready')
  assert.deepEqual(shown, ['Getting Fluent ready… 10%', 'Getting Fluent ready… 62%', 'Getting Fluent ready…'])
  assert.deepEqual(s.asked, [true, false, false, false], 'only the first ask starts the download')
})

test('a ready judge costs one ask and no tile', async () => {
  const s = server([{ status: 'ready', waiting: false }])
  let shown = 0
  const out = await waitForJudge({ fetch: s.fetch, onWaiting: () => { shown++ }, cancelled: () => false, sleep: noSleep })
  assert.equal(out.outcome, 'ready')
  assert.equal(shown, 0)
})

test('the server giving up ends the wait unjudged, with the reason', async () => {
  const s = server([{ status: 'downloading', waiting: true, percent: 40 }, { status: 'downloading', waiting: false, unjudged: 'stalled' }])
  const out = await waitForJudge({ fetch: s.fetch, onWaiting: () => {}, cancelled: () => false, sleep: noSleep })
  assert.equal(out.outcome, 'unjudged')
  assert.equal(out.state?.unjudged, 'stalled')
})

test('cancelling the tile ends the wait', async () => {
  let cancel = false
  const s = server([{ status: 'downloading', waiting: true, percent: 5 }])
  const out = await waitForJudge({ fetch: s.fetch, onWaiting: () => { cancel = true }, cancelled: () => cancel, sleep: noSleep })
  assert.equal(out.outcome, 'cancelled')
})

test('an unreachable status never hangs the run', async () => {
  const out = await waitForJudge({ fetch: async () => { throw new Error('offline') }, onWaiting: () => {}, cancelled: () => false, sleep: noSleep })
  assert.equal(out.outcome, 'ready')
})
