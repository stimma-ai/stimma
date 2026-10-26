import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { connectionFailure, pinVerificationError, PROXY_FAILURE_HEADER } from './proxyFailure.ts'

// The table the Android proxy is tested against too.
const contract = JSON.parse(readFileSync(new URL('../../../mobile/contract/proxy-failures.json', import.meta.url), 'utf8')) as {
  header: string
  failures: Record<string, { status: number; connection: string | null }>
}

test('every proxy failure category classifies the way the native contract says', () => {
  assert.equal(PROXY_FAILURE_HEADER, contract.header)
  for (const [category, { status, connection }] of Object.entries(contract.failures)) {
    assert.equal(connectionFailure({ status }), connection, category)
  }
})

test('injected connection failures and timeouts never read as a bad PIN', () => {
  for (const { status, connection } of Object.values(contract.failures)) {
    if (!connection) continue
    // Even if a body somehow said otherwise, the status wins.
    const message = pinVerificationError({ status }, 'Invalid PIN', 'Studio')
    assert.doesNotMatch(message, /PIN/)
    assert.match(message, /Studio/)
  }
  assert.equal(pinVerificationError({ status: 504 }, undefined, 'Studio'), 'No response from Studio')
  assert.equal(pinVerificationError({ status: 502 }, undefined), 'Lost connection to the server')
})

test('genuine access failures keep their existing handling', () => {
  assert.equal(connectionFailure({ status: 401 }), null)
  assert.equal(connectionFailure({ status: 403 }), null)
  assert.equal(pinVerificationError({ status: 401 }, 'Invalid PIN', 'Studio'), 'Invalid PIN')
  assert.equal(pinVerificationError({ status: 403 }, 'PIN required', 'Studio'), 'PIN required')
  // The proxy's own policy rejection is a 403 without a JSON detail.
  assert.equal(pinVerificationError({ status: 403 }, undefined, 'Studio'), 'Invalid PIN')
})
