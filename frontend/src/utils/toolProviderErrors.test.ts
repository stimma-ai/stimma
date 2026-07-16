import assert from 'node:assert/strict'
import test from 'node:test'

import { formatToolProviderConnectionError } from './toolProviderErrors.ts'

test('turns DNS failures into a concise actionable message', () => {
  assert.deepEqual(
    formatToolProviderConnectionError(
      'Failed to connect: Failed to connect to ws://asdjkas: Cannot connect to host asdjkas:80 ssl:default [nodename nor servname provided, or not known]',
      'ws://asdjkas',
    ),
    {
      title: 'Server not found',
      message: 'We couldn’t find ws://asdjkas. Check the address and try again.',
    },
  )
})

test('distinguishes refused, timed out, and authentication failures', () => {
  assert.equal(formatToolProviderConnectionError('Connection refused', 'ws://localhost:8188').title, 'Provider isn’t running')
  assert.equal(formatToolProviderConnectionError('Connection timed out', 'ws://renderbox:8188').title, 'Connection timed out')
  assert.equal(formatToolProviderConnectionError('HTTP 401 unauthorized').title, 'Authentication failed')
})

test('removes repeated connection prefixes from unknown failures', () => {
  assert.deepEqual(
    formatToolProviderConnectionError('Failed to connect: Failed to connect: Protocol negotiation failed'),
    { title: 'Couldn’t connect', message: 'Protocol negotiation failed.' },
  )
})
