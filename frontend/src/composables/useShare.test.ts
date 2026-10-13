import assert from 'node:assert/strict'
import test from 'node:test'
import {
  createShareSession,
  createSharedLinksList,
  formatBytes,
  friendlyShareError,
  normalizeStatus,
  publishedStepsPreview,
  shareTypeFact,
  validateUsername,
} from './useShare.ts'
import { useShareDialog } from './useShareDialog.ts'

type Handler = (url: string, init: RequestInit) => unknown | Promise<unknown>

interface Call { url: string; method: string; body: any; signal?: AbortSignal | null }

/** A fetch double: routes by "METHOD path" (query stripped), records every call. */
function mockFetch(routes: Record<string, Handler | unknown>) {
  const calls: Call[] = []
  const fetchImpl = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    const method = (init.method || 'GET').toUpperCase()
    calls.push({ url, method, body: init.body ? JSON.parse(String(init.body)) : null, signal: init.signal })
    const key = `${method} ${url.split('?')[0]}`
    if (!(key in routes)) return new Response(JSON.stringify({ error: 'no route' }), { status: 404 })
    const route = routes[key]
    const value = typeof route === 'function' ? await (route as Handler)(url, init) : route
    if (value instanceof Response) return value
    return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  return { fetchImpl, calls }
}

const tick = (ms = 0) => new Promise(r => setTimeout(r, ms))

/** A response that resolves when released, and rejects on abort like real fetch. */
function deferred(init: RequestInit, value: unknown) {
  return new Promise<Response>((resolve, reject) => {
    init.signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })))
    setTimeout(() => resolve(new Response(JSON.stringify(value))), 30)
  })
}

const OK_STATUS = { can_share: true, reason_code: null, identity_required: false, account: { username: 'maker', display_name: 'Maker', avatar_url: null } }
const MEDIA = { id: 7, file_format: 'png', file_size: 2_400_000, width: 1024, height: 768 }

test('signed out lands on can\'t share with the reason code, never on the form', async () => {
  const { fetchImpl, calls } = mockFetch({
    'GET /api/share/status': { can_share: false, reason_code: 'signed_out', reason: 'Not signed in', identity_required: false, account: null },
  })
  const s = createShareSession({ fetch: fetchImpl })
  await s.start(MEDIA)
  assert.equal(s.phase.value, 'cant-share')
  assert.equal(s.reasonCode.value, 'signed_out')
  assert.ok(!calls.some(c => c.url.includes('pre-check')), 'no pre-check while signed out')
})

test('legacy status without reason_code still maps to the right state', () => {
  assert.equal(normalizeStatus({ can_share: false, reason: 'Stimma sharing is disabled in Privacy Lockdown' }).reason_code, 'privacy_lockdown')
  assert.equal(normalizeStatus({ can_share: false, reason: 'Authentication expired - please sign in again' }).reason_code, 'auth_expired')
  assert.equal(normalizeStatus({ can_share: false, reason: 'Your sharing privileges have been suspended' }).reason_code, 'banned')
  assert.equal(normalizeStatus({ can_share: false, reason: 'Not signed in to your Stimma account' }).reason_code, 'signed_out')
  assert.equal(normalizeStatus({ can_share: true, username: 'a' }).account?.username, 'a')
  assert.equal(normalizeStatus({ can_share: false, identity_required: true }).reason_code, null)
})

test('a status request that fails is "unavailable", which can be retried', async () => {
  let fail = true
  const { fetchImpl } = mockFetch({
    'GET /api/share/status': () => (fail ? new Response('nope', { status: 502 }) : OK_STATUS),
    'GET /api/share/links': { links: [] },
    'POST /api/share/suggest-title': { title: 'Harbor' },
    'POST /api/share/pre-check': { blocked: false, decision: 'approved', nsfw: false },
  })
  const s = createShareSession({ fetch: fetchImpl })
  await s.start(MEDIA)
  assert.equal(s.phase.value, 'cant-share')
  assert.equal(s.reasonCode.value, 'unavailable')
  fail = false
  await s.recheck()
  assert.equal(s.phase.value, 'form')
  s.dispose()
})

test('existing links show first; Create another link opens the form and starts checks', async () => {
  const { fetchImpl, calls } = mockFetch({
    'GET /api/share/status': OK_STATUS,
    'GET /api/share/links': { links: [{ shortcode: 'abc', url: 'https://example.test/s/abc', title: 'Dune', status: 'quarantined', view_count: 3, created_at: '2026-10-01T00:00:00Z' }] },
    'POST /api/share/suggest-title': { title: 'Harbor' },
    'POST /api/share/pre-check': { blocked: false, decision: 'approved', nsfw: false },
  })
  const s = createShareSession({ fetch: fetchImpl })
  await s.start(MEDIA)
  assert.equal(s.phase.value, 'links')
  assert.equal(s.links.value[0].view_count, 3)
  assert.ok(calls.find(c => c.url === '/api/share/links?media_id=7'))
  assert.ok(!calls.some(c => c.url.includes('pre-check')))
  s.createAnother()
  assert.equal(s.phase.value, 'form')
  await tick(5)
  assert.equal(s.title.value, 'Harbor')
  assert.ok(calls.some(c => c.url.includes('pre-check')))
  s.dispose()
})

test('deleting the last existing link drops to the form', async () => {
  const { fetchImpl, calls } = mockFetch({
    'GET /api/share/status': OK_STATUS,
    'GET /api/share/links': [{ shortcode: 'abc', url: 'u', title: null, status: 'approved', view_count: 0, created_at: null }],
    'DELETE /api/share/links/abc': { success: true },
    'POST /api/share/suggest-title': {},
    'POST /api/share/pre-check': { blocked: false },
  })
  const s = createShareSession({ fetch: fetchImpl })
  await s.start(MEDIA)
  await s.deleteLink('abc')
  assert.equal(s.links.value.length, 0)
  assert.equal(s.phase.value, 'form')
  assert.ok(calls.some(c => c.method === 'DELETE'))
  s.dispose()
})

test('identity required → username step: validation, availability, then on to the form', async () => {
  let identityDone = false
  const { fetchImpl, calls } = mockFetch({
    'GET /api/share/status': () => (identityDone ? OK_STATUS : { can_share: false, identity_required: true, reason: 'set up' }),
    'GET /api/share/check-username': (url: string) => ({ available: !url.includes('taken'), username: 'x' }),
    'POST /api/share/setup-identity': () => { identityDone = true; return { success: true, username: 'maker' } },
    'GET /api/share/links': [],
    'POST /api/share/suggest-title': {},
    'POST /api/share/pre-check': { blocked: false },
  })
  const s = createShareSession({ fetch: fetchImpl, usernameDebounceMs: 0 })
  await s.start(MEDIA)
  assert.equal(s.phase.value, 'username')

  s.setUsername('ab')
  assert.match(s.usernameError.value || '', /3 characters/)
  assert.equal(s.canSubmitUsername.value, false)

  s.setUsername('Bad Name!')
  assert.equal(s.usernameInput.value, 'badname!')
  assert.match(s.usernameError.value || '', /lowercase/)

  s.setUsername('taken')
  await tick(5)
  assert.equal(s.usernameAvailable.value, false)
  assert.match(s.usernameError.value || '', /taken/)

  s.setUsername('maker')
  await tick(5)
  assert.equal(s.usernameAvailable.value, true)
  assert.equal(s.canSubmitUsername.value, true)
  assert.equal(await s.submitUsername(), true)
  assert.equal(s.phase.value, 'form')
  assert.deepEqual(calls.find(c => c.method === 'POST' && c.url.includes('setup-identity'))?.body, { username: 'maker' })
  s.dispose()
})

test('validateUsername mirrors the cloud rule', () => {
  assert.equal(validateUsername('a_b-1'), null)
  assert.equal(validateUsername(''), null)
  assert.ok(validateUsername('x'.repeat(25)))
  assert.ok(validateUsername('UPPER'))
})

test('typing aborts a pending suggestion and the suggestion never overwrites the person', async () => {
  let suggestSignal: AbortSignal | null | undefined
  const { fetchImpl } = mockFetch({
    'GET /api/share/status': OK_STATUS,
    'GET /api/share/links': [],
    'POST /api/share/suggest-title': (_u: string, init: RequestInit) => { suggestSignal = init.signal; return deferred(init, { title: 'Suggested' }) },
    'POST /api/share/pre-check': { blocked: false },
  })
  const s = createShareSession({ fetch: fetchImpl, precheckDebounceMs: 1 })
  await s.start(MEDIA)
  assert.equal(s.suggesting.value, true)
  s.setTitle('Mine')
  assert.equal(suggestSignal?.aborted, true)
  assert.equal(s.suggesting.value, false)
  await tick(50)
  assert.equal(s.title.value, 'Mine')
  s.dispose()
})

test('title/description edits re-run the pre-check (debounced) and abort the one in flight', async () => {
  const prechecks: Call[] = []
  const { fetchImpl } = mockFetch({
    'GET /api/share/status': OK_STATUS,
    'GET /api/share/links': [],
    'POST /api/share/suggest-title': {},
    'POST /api/share/pre-check': (_u: string, init: RequestInit) => {
      prechecks.push({ url: '', method: 'POST', body: JSON.parse(String(init.body)), signal: init.signal })
      return deferred(init, { blocked: false, decision: 'quarantined', reason: 'Held for review' })
    },
  })
  const s = createShareSession({ fetch: fetchImpl, precheckDebounceMs: 10 })
  await s.start(MEDIA)
  assert.equal(prechecks.length, 1)
  assert.equal(s.statusSlot.value, 'checking')
  s.setTitle('A')
  s.description.value = 'B'
  await tick(5)
  assert.equal(prechecks.length, 1, 'debounced')
  await tick(20)
  assert.equal(prechecks.length, 2)
  assert.equal(prechecks[0].signal?.aborted, true, 'previous pre-check aborted')
  assert.deepEqual(prechecks[1].body, { media_id: 7, title: 'A', description: 'B' })
  await tick(50)
  assert.equal(s.statusSlot.value, 'review')
  assert.equal(s.canCreate.value, true, 'review is a warning, not a block')
  s.dispose()
})

test('pre-check outcomes: nsfw locks mature on; blocked / too large / unsupported disable Create', async () => {
  let verdict: any = { blocked: false, nsfw: true, decision: 'approved' }
  const { fetchImpl } = mockFetch({
    'GET /api/share/status': OK_STATUS,
    'GET /api/share/links': [],
    'POST /api/share/suggest-title': {},
    'POST /api/share/pre-check': () => verdict,
  })
  const s = createShareSession({ fetch: fetchImpl })
  await s.start(MEDIA)
  await tick(5)
  assert.equal(s.mature.value, true)
  assert.equal(s.matureLocked.value, true)
  s.matureManual.value = false
  assert.equal(s.mature.value, true, 'cannot be turned off when detected')

  for (const [v, slot] of [
    [{ blocked: true, reason: 'Not allowed' }, 'blocked'],
    [{ blocked: false, decision: 'rejected' }, 'blocked'],
    [{ blocked: false, too_large: true, size_bytes: 120_000_000 }, 'too-large'],
    [{ blocked: false, unsupported_reason: 'Not supported' }, 'unsupported'],
  ] as const) {
    verdict = v
    await s.runPreCheck()
    assert.equal(s.statusSlot.value, slot)
    assert.equal(s.canCreate.value, false)
  }
  s.dispose()
})

test('create sends provenance only when "Include how it was made" is on', async () => {
  const bodies: any[] = []
  const provenance = { version: 2, steps: [{ tool: 'Flux' }] }
  const { fetchImpl } = mockFetch({
    'GET /api/share/status': OK_STATUS,
    'GET /api/share/links': [],
    'POST /api/share/suggest-title': {},
    'POST /api/share/pre-check': { blocked: false, size_bytes: 12_400_000 },
    'POST /api/share': (_u: string, init: RequestInit) => {
      bodies.push(JSON.parse(String(init.body)))
      return { success: true, shortcode: 'xyz', url: 'https://example.test/s/xyz', status: 'quarantined', media_type: 'image' }
    },
  })
  const s = createShareSession({ fetch: fetchImpl, buildPublicProvenance: () => provenance })
  await s.start(MEDIA)
  await tick(5)
  assert.equal(s.sizeBytes.value, 12_400_000)
  s.setTitle('  Harbor  ')
  s.matureManual.value = true
  await s.create()
  assert.equal(s.phase.value, 'created')
  assert.equal(s.result.value?.status, 'quarantined')
  assert.deepEqual(bodies[0], { media_id: 7, title: 'Harbor', description: null, nsfw_override: true, provenance })

  await s.start(MEDIA)
  await tick(5)
  s.includeProvenance.value = false
  await s.create()
  assert.equal(bodies[1].provenance, null)
  s.dispose()
})

test('a failed create shows a friendly error; Try again re-sends', async () => {
  let attempts = 0
  const { fetchImpl } = mockFetch({
    'GET /api/share/status': OK_STATUS,
    'GET /api/share/links': [],
    'POST /api/share/suggest-title': {},
    'POST /api/share/pre-check': { blocked: false },
    'POST /api/share': () => {
      attempts++
      if (attempts === 1) return new Response(JSON.stringify({ success: false, error: 'Traceback (most recent call last): boom' }), { status: 500 })
      return { success: true, shortcode: 'ok', url: 'https://example.test/s/ok', status: 'approved' }
    },
  })
  const s = createShareSession({ fetch: fetchImpl })
  await s.start(MEDIA)
  await tick(5)
  await s.create()
  assert.equal(s.phase.value, 'error')
  assert.match(s.error.value || '', /Something went wrong/)
  await s.create()
  assert.equal(s.phase.value, 'created')
  s.dispose()
})

test('sessions are independent: no shared module state', async () => {
  const { fetchImpl } = mockFetch({
    'GET /api/share/status': OK_STATUS,
    'GET /api/share/links': [],
    'POST /api/share/suggest-title': {},
    'POST /api/share/pre-check': { blocked: false },
  })
  const a = createShareSession({ fetch: fetchImpl })
  const b = createShareSession({ fetch: fetchImpl })
  await a.start(MEDIA)
  a.setTitle('Only A')
  assert.equal(b.title.value, '')
  assert.equal(b.phase.value, 'idle')
  a.dispose()
})

test('a late status response for a previous item never lands', async () => {
  let first = true
  const { fetchImpl } = mockFetch({
    'GET /api/share/status': async () => {
      if (first) { first = false; await tick(30); return { can_share: false, reason_code: 'banned' } }
      return OK_STATUS
    },
    'GET /api/share/links': [],
    'POST /api/share/suggest-title': {},
    'POST /api/share/pre-check': { blocked: false },
  })
  const s = createShareSession({ fetch: fetchImpl })
  const p1 = s.start(MEDIA)
  await s.start({ ...MEDIA, id: 8 })
  await p1
  assert.equal(s.phase.value, 'form')
  assert.equal(s.media.value?.id, 8)
  s.dispose()
})

test('shared links list: pagination, signed-out short-circuit, delete', async () => {
  const all = Array.from({ length: 5 }, (_, i) => ({ shortcode: `s${i}`, url: `u${i}`, title: `T${i}`, status: 'approved', view_count: i, created_at: null }))
  let signedIn = true
  const { fetchImpl, calls } = mockFetch({
    'GET /api/share/status': () => (signedIn ? OK_STATUS : { can_share: false, reason_code: 'signed_out' }),
    'GET /api/share/links': (url: string) => {
      const q = new URL(url, 'http://x').searchParams
      const offset = Number(q.get('offset')), limit = Number(q.get('limit'))
      return { links: all.slice(offset, offset + limit), total: all.length }
    },
    'DELETE /api/share/links/s1': { success: true },
  })
  const list = createSharedLinksList({ fetch: fetchImpl, pageSize: 2 })
  await list.load()
  assert.deepEqual(list.items.value.map(l => l.shortcode), ['s0', 's1'])
  assert.equal(list.hasMore.value, true)
  await list.loadMore()
  await list.loadMore()
  assert.equal(list.items.value.length, 5)
  assert.equal(list.hasMore.value, false)
  await list.remove('s1')
  assert.ok(!list.items.value.some(l => l.shortcode === 's1'))

  signedIn = false
  const before = calls.filter(c => c.url.startsWith('/api/share/links?')).length
  await list.load()
  assert.equal(list.status.value?.reason_code, 'signed_out')
  assert.equal(list.items.value.length, 0)
  assert.equal(calls.filter(c => c.url.startsWith('/api/share/links?')).length, before)
})

test('useShareDialog is a singleton: open by id or object, reopen restarts', () => {
  const a = useShareDialog()
  const b = useShareDialog()
  assert.equal(a.open(0), false)
  assert.equal(a.open(5), true)
  assert.equal(b.state.value.visible, true)
  assert.equal(b.state.value.mediaId, 5)
  const count = b.state.value.openCount
  b.open({ id: 5, file_format: 'png' })
  assert.equal(a.state.value.openCount, count + 1)
  assert.equal(a.state.value.media?.file_format, 'png')
  a.close()
  assert.equal(b.state.value.visible, false)
})

test('type facts and sizes read as one mono fact', () => {
  assert.equal(shareTypeFact({ file_format: 'stimmasprite.json' }, { animationCount: 4 }), 'Sprite · 4 animations')
  assert.equal(shareTypeFact({ file_format: 'mp3', duration: 32 }), 'Audio · 0:32')
  assert.equal(shareTypeFact({ file_format: 'stimmaset.json', raw_metadata: '{"items":[{},{},{},{}]}' }), 'Set · 4 items')
  assert.equal(shareTypeFact({ file_format: 'stimmagrid.json', raw_metadata: { rows: 2, cols: 3 } }), 'Grid · 2 × 3')
  assert.equal(shareTypeFact({ file_format: 'stimmapackage' }, { sizeBytes: 12_400_000 }), 'Package · 12.4 MB')
  assert.equal(shareTypeFact({ file_format: 'png', width: 1024, height: 768 }), 'Image · 1024 × 768')
  assert.equal(shareTypeFact({ file_format: 'md', file_size: 820_000 }), 'Markdown · 820 KB')
  assert.equal(formatBytes(0), '')
  assert.equal(friendlyShareError(null, null), "Couldn't reach Stimma. Check your connection and try again.")
  assert.equal(friendlyShareError(400, 'Title is too long'), 'Title is too long')
})

test('the provenance preview lists exactly the published fields', () => {
  const [step] = publishedStepsPreview({ version: 2, steps: [{
    tool: 'Flux', model: 'flux-2-pro', prompt: 'x'.repeat(400),
    facts: [{ label: 'Seed', value: '1234' }], loras: [{ name: 'grain', weight: 0.8 }],
    inputs: [{ role: 'Reference', ref: { mediaId: 1, hash: 'h' } }], edits: ['Crop'],
  }] })
  assert.equal(step.tool, 'Flux')
  assert.equal(step.prompt?.length, 220)
  assert.deepEqual(step.facts, ['Seed 1234'])
  assert.deepEqual(step.extras, ['LoRAs: grain 0.8', '1 input image: Reference', 'Edits: Crop'])
  assert.deepEqual(publishedStepsPreview(null), [])
})

test('backend error codes become plain sentences', () => {
  assert.match(friendlyShareError(400, 'whatever', 'too_large'), /too large/)
  assert.equal(friendlyShareError(400, 'Policy says no', 'blocked'), 'Policy says no')
  assert.match(friendlyShareError(502, null, 'cloud'), /Something went wrong/)
})
