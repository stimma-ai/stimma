import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getStartupWaitMessage,
  waitForBackendHealth,
} from '../src/utils/backendStartup.js'

test('routine startup waits do not show status text', () => {
  assert.equal(getStartupWaitMessage(0), null)
  assert.equal(getStartupWaitMessage(14_999), null)
})

test('long startup waits explain the exceptional library upgrade', () => {
  assert.equal(
    getStartupWaitMessage(15_000),
    'Upgrading your library. Large libraries may take several minutes.',
  )
})

test('backend readiness keeps waiting past the former 30-second attempt limit', async () => {
  let attempts = 0
  const waitingAttempts = []

  const response = await waitForBackendHealth('http://127.0.0.1:9191', {
    fetchImpl: async () => {
      attempts += 1
      if (attempts <= 75) throw new Error('not ready')
      return { ok: true, status: 200 }
    },
    sleepImpl: async () => {},
    onWaiting: ({ attempt }) => waitingAttempts.push(attempt),
  })

  assert.equal(response.status, 200)
  assert.equal(attempts, 76)
  assert.equal(waitingAttempts.at(-1), 75)
})

test('backend readiness retries non-success health responses', async () => {
  let attempts = 0
  await waitForBackendHealth('http://127.0.0.1:9191', {
    fetchImpl: async () => ({ ok: ++attempts === 3 }),
    sleepImpl: async () => {},
  })

  assert.equal(attempts, 3)
})
