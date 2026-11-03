import assert from 'node:assert/strict'
import test from 'node:test'
import { log, scrubNetworkDetails } from '../src/log.ts'

test('network scrubber preserves diagnostics and loopback endpoints', () => {
  for (const message of [
    'task_queues:105:5', 'App.vue:42:11', 'foo.ts:10', 'foo.js:1:2', 'foo.py:7',
    'app.123.js:42', 'foo.ts:100000', 'size:1024', 'render-box:9191', 'metric.value1:1024',
    'Version 1.2.3; version:1.2.3; size 1048576 bytes (12.5 MB); 12:34:56',
    'invalid 999.1.2.3', 'Listening on localhost:9191', 'Listening on 127.0.0.1:9191',
    'Listening on 127.0.0.1:PORT', 'Listening on 127.0.0.2:9191',
    'Listening on [::1]:9191', 'Listening on ::1', 'Listening on 0:0:0:0:0:0:0:1',
    'http://localhost:9191/path', 'http://127.0.0.1:9191/path', 'http://[::1]:9191/path',
    'http://[0:0:0:0:0:0:0:1]:9191/path',
  ]) {
    assert.equal(scrubNetworkDetails(message), message)
  }
})

test('network scrubber removes addresses without removing error codes', () => {
  const cases = [
    ['getaddrinfo ENOTFOUND studio-node.example', 'getaddrinfo ENOTFOUND [redacted]'],
    ['getaddrinfo EAI_AGAIN studio-node.example:9191', 'getaddrinfo EAI_AGAIN [redacted]'],
    ['connect ECONNREFUSED 203.0.113.8:9191', 'connect ECONNREFUSED [redacted]'],
    ['route 198.51.100.8', 'route [redacted]'],
    ['route studio-node.example:9191 studio-node.example', 'route [redacted] [redacted]'],
    ['route [2001:db8::8]:9191 2001:db8::8', 'route [redacted] [redacted]'],
    ['route fe80::1234%eth0 ::ffff:192.0.2.8', 'route [redacted] [redacted]'],
    ['https://render-box:9191/path', 'https://[redacted]/path'],
    ['https://user:password@localhost:9191/path', 'https://[redacted]/path'],
    ['https://studio-node.example:9191/path', 'https://[redacted]/path'],
  ]
  for (const [message, expected] of cases) {
    assert.equal(scrubNetworkDetails(message), expected, message)
  }
})

test('shell logger removes network details from URLs, socket errors and forwarded logs', (t) => {
  const lines: string[] = []
  t.mock.method(console, 'log', (line: string) => lines.push(line))
  const messages = [
    'Blocked navigation to https://render-box.example:9192/path',
    'Renderer finished loading app://render-box.example/',
    'Target set to render-box.example:9191',
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
  const useful = 'Version 1.2.3; version:1.2.3; file app.123.js:42; size 1048576 bytes (12.5 MB); 12:34:56'
  log.info('test', useful)
  assert.ok(lines.at(-1)!.endsWith(useful))
})
