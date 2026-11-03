import assert from 'node:assert/strict'
import test from 'node:test'
import { log } from '../src/log.ts'

test('shell logger removes network details from URLs, socket errors and forwarded logs', (t) => {
  const lines: string[] = []
  t.mock.method(console, 'log', (line: string) => lines.push(line))
  const messages = [
    'Blocked navigation to https://render-box.example:9192/path',
    'Renderer finished loading app://render-box.example/',
    'Target set to render-box:9191',
    'connect ECONNREFUSED 192.168.42.8:9191',
    'getaddrinfo ENOTFOUND studio-node.example',
    'routes 10.23.45.6 172.23.4.5 100.97.42.8 render-box.local render-box.tailtest.ts.net',
    'routes [fd12:3456::8]:9191 fd12:3456::8 fe80::1234 2001:db8:1234:5678:9abc:def0:1234:5678',
  ]
  for (const message of messages) log.info('test', message)
  const text = lines.join('\n')
  for (const value of ['render-box', 'studio-node', '9191', '9192', '192.168.42.8', '10.23.45.6',
    '172.23.4.5', '100.97.42.8', 'fd12:3456::8', 'fe80::1234', '2001:db8']) {
    assert.ok(!text.includes(value), value)
  }
  assert.match(text, /https:\/\/\[redacted\]\/path/)
  const useful = 'Version 1.2.3 and 1.2.3.4; version:1.2.3; file app.123.js:42; size 1048576 bytes (12.5 MB); 12:34:56'
  log.info('test', useful)
  assert.ok(lines.at(-1)!.endsWith(useful))
})
