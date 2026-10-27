import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { websocketHarness } from './fixtures/websocketHarness.mjs'
import { createRealtimeScope } from '../src/composables/realtimeScope.js'

function harness() {
  const sent = []
  const timers = new Map()
  let timerId = 0
  const scope = createRealtimeScope({
    schedule: fn => fn(),
    setTimer: (fn) => { timers.set(++timerId, fn); return timerId },
    clearTimer: id => timers.delete(id),
    warn: () => {},
  })
  const send = (event, data) => { sent.push({ event, data }); return true }
  const fireTimers = () => { for (const [id, fn] of [...timers]) { timers.delete(id); fn() } }
  return { scope, sent, send, timers, fireTimers }
}

const settled = async (promise) => {
  let done = false
  promise.then(() => { done = true })
  await new Promise(resolve => setImmediate(resolve))
  return done
}

test('the connect query carries the capability and the complete scope', () => {
  const { scope } = harness()
  scope.acquire('chat:7')
  scope.acquire('previews:tool-a@@g')
  scope.setPreviewPolicy({ maxFps: 2, maxBytes: 262144 })
  const params = new URLSearchParams(scope.connectQuery('profile-a'))
  assert.equal(params.get('realtime'), '1')
  assert.equal(params.get('profile'), 'profile-a')
  assert.deepEqual(params.getAll('topic'), ['chat:7', 'previews:tool-a@@g'])
  assert.equal(params.get('previews'), '1')
  assert.equal(params.get('preview_fps'), '2')
  assert.equal(params.get('preview_bytes'), '262144')
})

test('a current server gets the full scope after each change and acknowledges it', async () => {
  const { scope, sent, send } = harness()
  scope.connectQuery('a')
  scope.socketOpened(send)
  scope.handleServerMessage('connected', { realtime: { protocol: 1, profile_id: 'a', topics: [] } })
  assert.equal(sent.length, 0, 'nothing changed since connecting')

  const release = scope.acquire('chat:7')
  assert.equal(sent.length, 1)
  assert.equal(sent[0].event, 'realtime_scope')
  assert.deepEqual(sent[0].data, {
    profile_id: 'a', topics: ['chat:7'],
    previews: { enabled: true, max_fps: null, max_bytes: null, max_bytes_per_second: null }, seq: 1,
  })
  // A view reads chat 7 over HTTP only once the server follows it for us.
  const ready = scope.ready('chat:7')
  assert.equal(await settled(ready), false)
  scope.handleServerMessage('realtime_scope_applied', { seq: 1, profile_id: 'a', topics: ['chat:7'] })
  assert.equal(await settled(ready), true)

  // A second view of the same chat shares the subscription.
  const again = scope.acquire('chat:7')
  assert.equal(sent.length, 1)
  release()
  assert.equal(sent.length, 1, 'still followed by the other view')
  again()
  assert.deepEqual(sent[1].data.topics, [])
  assert.equal(sent[1].data.seq, 2)

  scope.setProfile('b')
  scope.setPreviewsVisible(false)
  assert.equal(sent.at(-1).data.profile_id, 'b')
  assert.equal(sent.at(-1).data.previews.enabled, false)
})

test('changes made while connecting are sent once the server confirms scopes', () => {
  const { scope, sent, send } = harness()
  scope.acquire('chat:1')
  scope.connectQuery('a')
  scope.acquire('generator:tool-x@@g')
  scope.socketOpened(send)
  assert.equal(sent.length, 0, 'not before the server says it understands scopes')
  scope.handleServerMessage('connected', { realtime: { topics: ['chat:1'] } })
  assert.deepEqual(sent.map(m => m.data.topics), [['chat:1', 'generator:tool-x@@g']])
})

test('an older server is never sent scope messages and never delays a view', async () => {
  const { scope, sent, send } = harness()
  scope.connectQuery('a')
  scope.socketOpened(send)
  const pending = scope.ready(undefined)
  scope.acquire('chat:3')
  const ready = scope.ready('chat:3')
  scope.handleServerMessage('connected', { message: 'Connected to Stimma WebSocket' })
  assert.equal(await settled(ready), true)
  assert.equal(await settled(pending), true)
  scope.acquire('chat:4')
  scope.setPreviewsVisible(false)
  assert.equal(sent.length, 0)
  assert.equal(await settled(scope.ready('chat:4')), true)
})

test('topics in the connect URL are ready as soon as the socket opens', async () => {
  const { scope, send } = harness()
  scope.acquire('chat:9')
  scope.connectQuery('a')
  const ready = scope.ready('chat:9')
  assert.equal(await settled(ready), false)
  scope.socketOpened(send)
  assert.equal(await settled(ready), true)
})

test('a lost acknowledgement or a dropped socket never stalls a view', async () => {
  const { scope, send, fireTimers } = harness()
  scope.connectQuery('a')
  scope.socketOpened(send)
  scope.handleServerMessage('connected', { realtime: { topics: [] } })
  scope.acquire('chat:1')
  const timedOut = scope.ready('chat:1')
  fireTimers()
  assert.equal(await settled(timedOut), true)

  scope.acquire('chat:2')
  const dropped = scope.ready('chat:2')
  scope.socketClosed()
  assert.equal(await settled(dropped), true)
  // Offline: the reconnect resynchronizes, so there is nothing to wait for.
  assert.equal(await settled(scope.ready('chat:2')), true)
})

test('reconnecting restores every followed topic and the profile', () => {
  const { scope, sent, send } = harness()
  scope.connectQuery('a')
  scope.socketOpened(send)
  scope.handleServerMessage('connected', { realtime: { topics: [] } })
  scope.acquire('chat:5')
  scope.acquire('generator:tool-y@@g')
  scope.setProfile('b')
  scope.socketClosed()
  const params = new URLSearchParams(scope.connectQuery('b'))
  assert.deepEqual(params.getAll('topic'), ['chat:5', 'generator:tool-y@@g'])
  assert.equal(params.get('profile'), 'b')
  const before = sent.length
  scope.socketOpened(send)
  scope.handleServerMessage('connected', { realtime: { topics: ['chat:5', 'generator:tool-y@@g'] } })
  assert.equal(sent.length, before, 'the URL already restored the scope')
})

function scopedHarness() {
  const h = harness()
  h.scope.connectQuery('a')
  h.scope.socketOpened(h.send)
  h.scope.handleServerMessage('connected', { realtime: { profile_id: 'a', topics: [] } })
  h.ack = (index = h.sent.length - 1) => {
    const { data } = h.sent[index]
    h.scope.handleServerMessage('realtime_scope_applied', { seq: data.seq, profile_id: data.profile_id, topics: data.topics })
  }
  return h
}

test('an acknowledgement for an older scope does not make a topic ready', async () => {
  const { scope, sent, ack } = scopedHarness()
  let release = scope.acquire('chat:7')
  ack()
  assert.equal(await settled(scope.ready('chat:7')), true)
  // Leave the chat and come back before either change is acknowledged.
  release()
  release = scope.acquire('chat:7')
  assert.deepEqual(sent.map(m => m.data.topics), [['chat:7'], [], ['chat:7']])
  const ready = scope.ready('chat:7')
  assert.equal(await settled(ready), false, 'still subscribed in the stale ack, but a removal is in flight')
  ack(1)
  assert.equal(await settled(ready), false, 'the unsubscribe was applied; the resubscribe is pending')
  ack(2)
  assert.equal(await settled(ready), true)
})

test('a profile change waits for the server to filter for the new profile', async () => {
  const { scope, sent, ack } = scopedHarness()
  scope.acquire('generator:tool-z@@g')
  ack()
  const confirmedProfiles = []
  scope.onProfileConfirmed(id => confirmedProfiles.push(id))
  scope.setProfile('b')
  const ready = scope.ready('generator:tool-z@@g')
  assert.equal(await settled(ready), false)
  assert.equal(sent.at(-1).data.profile_id, 'b')
  ack()
  assert.equal(await settled(ready), true)
  assert.deepEqual(confirmedProfiles, ['b'])
})

test('overlapping scope changes still reconcile a profile switch exactly once', () => {
  const { scope, sent, ack } = scopedHarness()
  const confirmedProfiles = []
  scope.onProfileConfirmed(id => confirmedProfiles.push(id))
  // Profile B as seq 1, a topic change as seq 2, neither acknowledged yet.
  scope.setProfile('b')
  scope.acquire('chat:9')
  assert.deepEqual(sent.map(m => [m.data.seq, m.data.profile_id, m.data.topics]), [
    [1, 'b', []], [2, 'b', ['chat:9']],
  ])
  ack(0)
  assert.deepEqual(confirmedProfiles, [], 'a later change is still in flight')
  ack(1)
  assert.deepEqual(confirmedProfiles, ['b'])
  ack(1)
  assert.deepEqual(confirmedProfiles, ['b'], 'once')
  // A later topic-only change does not reconcile the profile again.
  scope.acquire('chat:11')
  ack()
  assert.deepEqual(confirmedProfiles, ['b'])
})

test('a read that does not wait is provisional only until the topic is confirmed', () => {
  const { scope, ack } = scopedHarness()
  const late = []
  scope.onLateConfirm(topic => late.push(topic))
  scope.acquire('generator:tool-q@@g')
  assert.equal(scope.markProvisional('generator:tool-q@@g'), true)
  ack()
  assert.deepEqual(late, ['generator:tool-q@@g'])
  // Once confirmed, a read needs no reconciliation.
  assert.equal(scope.markProvisional('generator:tool-q@@g'), false)
  ack()
  assert.deepEqual(late, ['generator:tool-q@@g'])
})

test('a timed-out wait reads provisionally and is reconciled on confirmation', async () => {
  const { scope, ack, fireTimers } = scopedHarness()
  const late = []
  scope.onLateConfirm(topic => late.push(topic))
  scope.acquire('chat:3')
  const ready = scope.ready('chat:3')
  fireTimers()
  assert.equal(await ready, false, 'provisional')
  assert.deepEqual(late, [])
  ack()
  assert.deepEqual(late, ['chat:3'])
  ack()
  assert.deepEqual(late, ['chat:3'], 'reconciled once')
})

test('a reconnect replaces pending provisional reconciliation', async () => {
  const { scope, send, fireTimers } = scopedHarness()
  const late = []
  scope.onLateConfirm(topic => late.push(topic))
  scope.acquire('chat:3')
  const ready = scope.ready('chat:3')
  fireTimers()
  await ready
  scope.socketClosed()
  scope.connectQuery('a')
  scope.socketOpened(send)
  assert.deepEqual(late, [], 'the reconnect resync covers it')
})

// The real useWebSocket singleton with a controlled socket.
function socketFixture(before = () => {}) {
  const { api, sockets, scope } = websocketHarness({ profile: 'profile-a', url: 'ws://server/ws', before })
  return { api, sockets, scope }
}

test('the socket connects with the scope and keeps the server in step', () => {
  let release
  // The singleton connects as soon as it is first used.
  const { api, sockets, scope } = socketFixture(scope => { release = scope.acquire('chat:12') })
  assert.equal(sockets.length, 1)
  const url = new URL(sockets[0].url)
  assert.equal(url.pathname, '/ws')
  assert.equal(url.searchParams.get('realtime'), '1')
  assert.equal(url.searchParams.get('profile'), 'profile-a')
  assert.deepEqual(url.searchParams.getAll('topic'), ['chat:12'])

  const seen = []
  api.on('connected', data => seen.push(data))
  sockets[0].open()
  sockets[0].receive('connected', { realtime: { protocol: 1, profile_id: 'profile-a', topics: ['chat:12'] } })
  assert.equal(seen.length, 1, 'ordinary handlers still see the welcome')
  release()
  assert.deepEqual(sockets[0].sent.map(m => [m.event, m.data.topics]), [['realtime_scope', []]])

  // Events for another profile are still dropped client-side.
  const media = []
  api.on('media_added', data => media.push(data.media_id))
  sockets[0].receive('media_added', { media_id: 1, profile_id: 'profile-b' })
  sockets[0].receive('media_added', { media_id: 2, profile_id: 'profile-a' })
  assert.deepEqual(media, [2])
})

test('the cached PIN rides the connect URL and scope messages, never the snapshot', () => {
  const { scope, sent, send } = harness()
  const pins = new Map([['locked', '1234']])
  scope.setPinSource(id => pins.get(id) ?? null)

  const open = new URLSearchParams(scope.connectQuery('open'))
  assert.equal(open.get('pin'), null, 'an open profile sends no PIN')
  const params = new URLSearchParams(scope.connectQuery('locked'))
  assert.equal(params.get('profile'), 'locked')
  assert.equal(params.get('pin'), '1234')
  assert.equal(scope.presentedPin('locked'), '1234')

  scope.socketOpened(send)
  scope.handleServerMessage('connected', { realtime: { protocol: 1, profile_id: 'locked', topics: [], authorized: true } })
  scope.acquire('chat:1')
  assert.equal(sent.at(-1).data.pin, '1234')
  scope.setProfile('open')
  assert.equal('pin' in sent.at(-1).data, false)
  assert.equal(scope.presentedPin('locked'), null, 'the socket is scoped to another profile now')
  assert.equal(JSON.stringify(scope.snapshot()).includes('1234'), false)
})

test('a scope message refused for its PIN is reported once, with the PIN it carried', () => {
  const { scope, send } = harness()
  const pins = new Map([['locked', '0000']])
  scope.setPinSource(id => pins.get(id) ?? null)
  const rejected = []
  scope.onPinRejected((profile, pin) => rejected.push([profile, pin]))
  scope.connectQuery('open')
  scope.socketOpened(send)
  scope.handleServerMessage('connected', { realtime: { protocol: 1, profile_id: 'open', topics: [] } })
  scope.setProfile('locked')
  scope.handleServerMessage('realtime_scope_rejected', { seq: 1, reason: 'invalid_pin' })
  scope.handleServerMessage('realtime_scope_rejected', { seq: 1, reason: 'invalid_pin' })
  scope.handleServerMessage('realtime_scope_rejected', { seq: 9, reason: 'invalid topic' })
  assert.deepEqual(rejected, [['locked', '0000']])
})

test('a wrong PIN on connect is forgotten and the socket reconnects without it', () => {
  const pins = new Map([['profile-a', '0000']])
  const { sockets, clock, rejectedPins } = websocketHarness({ profile: 'profile-a', url: 'ws://server/ws', pins })
  assert.equal(new URL(sockets[0].url).searchParams.get('pin'), '0000')
  sockets[0].open()
  sockets[0].drop(4403)
  assert.deepEqual(rejectedPins, [['profile-a', '0000']])
  clock.advance(1000)
  assert.equal(sockets.length, 2, 'reconnects as after any drop')
  assert.equal(new URL(sockets[1].url).searchParams.get('pin'), null)
})

test('entering a PIN replaces a socket that did not present it, once', () => {
  const pins = new Map()
  const { sockets, window } = websocketHarness({ profile: 'profile-a', url: 'ws://server/ws', pins })
  sockets[0].open()
  sockets[0].receive('connected', { realtime: { protocol: 1, profile_id: 'profile-a', topics: [], authorized: false } })

  // Another profile's PIN changes nothing here.
  pins.set('profile-b', '9999')
  window.dispatchEvent(new CustomEvent('pin-cached', { detail: { profileId: 'profile-b' } }))
  assert.equal(sockets.length, 1)

  pins.set('profile-a', '1234')
  window.dispatchEvent(new CustomEvent('pin-cached', { detail: { profileId: 'profile-a' } }))
  assert.equal(sockets.length, 2)
  assert.equal(sockets[0].closed, true)
  assert.equal(new URL(sockets[1].url).searchParams.get('pin'), '1234')

  // Re-entering the same PIN (unlocking after an idle lock) keeps the socket.
  sockets[1].open()
  window.dispatchEvent(new CustomEvent('pin-cached', { detail: { profileId: 'profile-a' } }))
  assert.equal(sockets.length, 2)
})
