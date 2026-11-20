import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { stripTypeScriptTypes } from 'node:module'
import { ref } from 'vue'

// useAgentActivity with a fake socket and a fake GET /api/chats/agent/running.
function fixture(running = { chat_ids: [], background: [] }) {
  const ts = readFileSync(new URL('../src/composables/useAgentActivity.ts', import.meta.url), 'utf8')
  const source = stripTypeScriptTypes(ts)
    .replace(/^import .*$/gm, '').replace(/^export /gm, '')
  const handlers = new Map()
  let snapshot = running
  let gate = null
  const make = new Function('ref', 'mobileRecoveryEnabled', 'useWebSocket', 'fetch',
    `${source}; return { useAgentActivity, prime }`)
  const mod = make(ref, false, () => ({ on: (name, fn) => handlers.set(name, fn) }),
    async () => { const taken = snapshot; await gate; return { ok: true, json: async () => taken } })
  const api = mod.useAgentActivity()
  return {
    api, prime: mod.prime, emit: (name, data) => handlers.get(name)?.(data), setRunning: v => { snapshot = v },
    hold: () => { let open; gate = new Promise(resolve => { open = resolve }); return () => { gate = null; open() } },
  }
}

const task = (chatId, id, state) => ['background_task_state', { chat_id: chatId, task_id: id, state }]

test('a chat keeps working after its turn ends while a background task runs', () => {
  const f = fixture()
  f.emit('agent_started', { chat_id: 7 })
  f.emit(...task(7, 'bg-1', 'running'))
  f.emit('agent_stopped', { chat_id: 7, reason: 'completed' })
  assert.equal(f.api.isChatGenerating(7), false) // the turn is over
  assert.equal(f.api.isChatWorking(7), true) // but its work goes on
  f.emit(...task(7, 'bg-1', 'completed'))
  assert.equal(f.api.isChatWorking(7), false)
})

test('a chat with two background tasks stays working until both finish', () => {
  const f = fixture()
  f.emit(...task(3, 'bg-1', 'running'))
  f.emit(...task(3, 'bg-2', 'running'))
  f.emit(...task(3, 'bg-1', 'failed'))
  assert.equal(f.api.isChatWorking(3), true)
  f.emit(...task(3, 'bg-2', 'completed'))
  assert.equal(f.api.isChatWorking(3), false)
})

test('startup and reconnect pick up background tasks already running', async () => {
  const f = fixture({ chat_ids: [], background: [{ chat_id: 5, task_ids: ['bg-4', 'bg-5'] }] })
  await f.prime()
  assert.equal(f.api.isChatWorking(5), true)
  assert.equal(f.api.isChatGenerating(5), false)
  f.emit(...task(5, 'bg-4', 'completed'))
  assert.equal(f.api.isChatWorking(5), true)
  // A task that ended while the socket was down disappears on the re-prime.
  f.emit('websocket_disconnected')
  assert.equal(f.api.isChatWorking(5), false)
  f.setRunning({ chat_ids: [], background: [] })
  await f.prime()
  assert.equal(f.api.isChatWorking(5), false)
})

test('a task that ends while the snapshot is in flight stays ended', async () => {
  const f = fixture({ chat_ids: [], background: [{ chat_id: 9, task_ids: ['bg-1'] }] })
  const release = f.hold()
  const priming = f.prime()
  f.emit(...task(9, 'bg-1', 'completed')) // newer than the snapshot
  release()
  await priming
  assert.equal(f.api.isChatWorking(9), false)
})
