import assert from 'node:assert/strict'
import test from 'node:test'

import { triggerServerUpdateCheck } from './serverUpdateCheck.ts'

function response(body: unknown, ok = true): Response {
  return { ok, json: async () => body } as Response
}

test('a client update check also triggers a headless server check', async () => {
  const calls: Array<[string, RequestInit | undefined]> = []
  const request = async (url: string, init?: RequestInit) => {
    calls.push([url, init])
    return response(calls.length === 1 ? { headless: true } : { status: 'checking' })
  }

  assert.equal(await triggerServerUpdateCheck('/api', request), true)
  assert.deepEqual(calls.map(([url, init]) => [url, init?.method ?? 'GET']), [
    ['/api/headless/status', 'GET'],
    ['/api/headless/check', 'POST'],
  ])
})

test('desktop-managed backends do not receive a server command', async () => {
  const calls: string[] = []
  const request = async (url: string) => {
    calls.push(url)
    return response({ headless: false })
  }

  assert.equal(await triggerServerUpdateCheck('/api', request), false)
  assert.deepEqual(calls, ['/api/headless/status'])
})

test('server check failures remain best-effort', async () => {
  const request = async () => { throw new Error('offline') }
  assert.equal(await triggerServerUpdateCheck('/api', request), false)
})
