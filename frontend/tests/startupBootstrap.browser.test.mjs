// Startup request budget for the shared Vue app.
//
// Boots the real application (Vite dev server, real router and App.vue) in
// Chromium against a fixture backend that answers every /api request after a
// fixed latency, then checks which bootstrap reads startup issues, how many
// of them are serial before the shell is usable, and when optional
// maintenance runs. STARTUP_REQUEST_REPORT=1 prints the request table.
import assert from 'node:assert/strict'
import test from 'node:test'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { chromium } from '@playwright/test'
import viteConfig from '../vite.config.js'

const root = fileURLToPath(new URL('..', import.meta.url))
const LATENCY_MS = 60
// Maintenance answers more slowly than the queue's gap between tasks, so a
// task that resolved before its network work finished would overlap the next.
const SLOW = { '/api/boards/7': 800, '/api/headless/status': 1500, '/api/stimpack-marketplace/auto-install': 400, '/api/stimpack-marketplace/check-updates': 400 }
const DESKTOP_CHECK_MS = 800
const MAINTENANCE = ['/api/stimpack-marketplace/auto-install', '/api/stimpack-marketplace/check-updates', '/api/headless/status']
const BUNDLE = 'ai.stimma.stimma.debug'

function profile(id, extra = {}) {
  return { id, name: id, database: `${id}.db`, db_guid: `guid-${id}`, has_pin: false, pin_idle_timeout_minutes: 30, ...extra }
}

const settingsBody = { bundle_id: BUNDLE, sandbox: 'default', theme: 'dark', developer_mode: false, wildcards: [], prompt_segments: [],
  readiness: { ready: true, has_agent_llm: true, has_generation: true, missing: [], wizard_version: 1, wizard_seen_version: 1 } }

const fixed = {
  '/api/models/available': { models: [{ slug: 'auto', name: 'Auto', source: 'auto', available: true, status: 'available', resolved_slug: 'fixture:model' }], llm_configured: true, default: 'auto', role_defaults: {} },
  '/api/processing/stats': { phase_stats: {} },
  '/api/processing/status': {},
  '/api/auth/status': { authenticated: false },
  '/api/feature-flags': {},
  '/api/stimpack-marketplace/auto-install': { installed: [] },
  '/api/telemetry/track': {},
}

let server
let browser
test.before(async () => {
  const config = viteConfig()
  delete config.server.proxy
  const cacheDir = mkdtempSync(join(tmpdir(), 'startup-bootstrap-vite-'))
  // Builds with an update endpoint run the desktop update loop.
  config.define = { ...config.define, 'import.meta.env.VITE_STIMMA_UPDATE_ENDPOINT': JSON.stringify('https://updates.invalid') }
  server = await createServer({ ...config, configFile: false, root, cacheDir, logLevel: 'error',
    server: { port: 0, host: '127.0.0.1', strictPort: false, hmr: false, watch: null } })
  await server.listen()
  browser = await chromium.launch()
  // Warm the dependency optimizer so the first measured boot is not a cold transform.
  const page = await browser.newPage()
  await page.route(/\/api\//, route => route.fulfill({ contentType: 'application/json', body: '[]' }))
  await page.goto(`${server.resolvedUrls.local[0]}home`).catch(() => {})
  await page.waitForTimeout(3000)
  await page.close()
  test.after(() => rmSync(cacheDir, { recursive: true, force: true }))
})
test.after(async () => {
  await browser?.close()
  await server?.close()
})

/**
 * Boot the app. `backend.profiles` is the roster; `backend.pins` maps profile
 * id -> PIN the fixture enforces on profile-scoped routes like the server's
 * middleware does.
 */
async function boot(t, { profiles = [profile('main')], pins = {}, storedProfile = 'main', cachedPin = null, desktop = false, path = 'home', savedRoute = null } = {}) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 860 } })
  t.after(() => context.close())
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const backend = { profiles, pins, log: [] }
  await page.addInitScript(({ bundle, storedProfile, cachedPin, savedRoute }) => {
    if (sessionStorage.getItem('startup-test-seeded')) return
    sessionStorage.setItem('startup-test-seeded', '1')
    localStorage.setItem(`stimma_${bundle}_default_global_onboarding_completed`, '1')
    localStorage.setItem('stimma_install_terms_accepted', JSON.stringify({ version: 999, at: Date.now() }))
    if (storedProfile) localStorage.setItem('profileId', storedProfile)
    if (savedRoute) localStorage.setItem(`stimma_${bundle}_default_${storedProfile}_last_route`, savedRoute)
    if (cachedPin) {
      sessionStorage.setItem('stimma_global_pin_cache', JSON.stringify({
        [cachedPin.profileId]: { pin: cachedPin.pin, lastActivity: Date.now() - (cachedPin.idleMs ?? 0), timeoutMinutes: 30 },
      }))
    }
  }, { bundle: BUNDLE, storedProfile, cachedPin, savedRoute })
  if (desktop) {
    // A minimal Electron bridge: same-origin backend, one ready local device,
    // and an app update check that takes a while (recorded on the page clock).
    const port = Number(new URL(server.resolvedUrls.local[0]).port)
    await page.addInitScript(({ port, checkMs }) => {
      window.updateChecks = []
      const calls = {
        kind: 'electron',
        getBackendPort: async () => port,
        getWindowProfile: async () => null,
        mdGetState: async () => ({ activeDeviceId: 'local', devices: [], connectionState: 'ready' }),
        mdOnConnectionState: () => () => {},
        mdRefreshDevices: async () => [],
        mdLocalStatus: async () => ({}),
        getAppVersion: async () => '1.0.0',
        authLocal: async () => ({ ok: true, status: 200, data: { authenticated: false } }),
        checkForUpdate: async () => {
          const check = { start: performance.now() }
          window.updateChecks.push(check)
          await new Promise(resolve => setTimeout(resolve, checkMs))
          check.end = performance.now()
          return null
        },
      }
      window.stimmaDesktop = new Proxy(calls, { get: (target, key) => (key in target ? target[key] : async () => null) })
    }, { port, checkMs: DESKTOP_CHECK_MS })
  }
  // Page-clock timeline: when the shell first renders, and every API request's
  // start and response end (Resource Timing), so ordering is exact.
  await page.addInitScript(() => {
    performance.setResourceTimingBufferSize(10_000)
    new MutationObserver((_, observer) => {
      if (!document.querySelector('.top-bar')) return
      window.__shellAt = performance.now()
      observer.disconnect()
    }).observe(document, { childList: true, subtree: true })
  })
  await page.routeWebSocket(/\/ws/, () => {})
  await page.route(/\/api\//, async route => {
    const request = route.request()
    const url = new URL(request.url())
    const path = url.pathname
    const profileId = request.headers()['x-profile-id'] || null
    await new Promise(resolve => setTimeout(resolve, SLOW[path] ?? LATENCY_MS))
    let status = 200
    let body = []
    const exempt = path === '/api/profiles' || /^\/api\/profiles\/[^/]+\/verify-pin$/.test(path) || path.startsWith('/api/telemetry')
    const pin = backend.pins[profileId]
    if (!exempt && pin && request.headers()['x-profile-pin'] !== pin) {
      status = 403
      body = { detail: 'PIN required', requires_pin: true, profile_id: profileId }
    } else if (path === '/api/profiles') {
      body = { profiles: backend.profiles }
    } else if (path.endsWith('/verify-pin')) {
      const id = path.split('/')[3]
      const ok = JSON.parse(request.postData() || '{}').pin === backend.pins[id]
      status = ok ? 200 : 401
      body = ok ? { valid: true } : { detail: 'Invalid PIN' }
    } else if (path === '/api/settings') {
      body = { ...settingsBody, profile_id: profileId }
    } else if (path === '/api/boards/7') {
      body = { id: 7, name: 'Deep-linked board', project_id: null, items: [], sections: [] }
    } else if (path === '/api/headless/status') {
      status = 404
      body = {}
    } else if (fixed[path]) {
      body = fixed[path]
    }
    backend.log.push({ method: request.method(), path, profileId, status })
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }).catch(() => {})
  })
  await page.goto(`${server.resolvedUrls.local[0]}${path}`)
  t.after(() => assert.deepEqual(errors, []))
  return { page, backend }
}

async function shellVisibleAt(page) {
  await page.locator('.top-bar').first().waitFor({ state: 'visible', timeout: 30_000 })
  return page.evaluate(() => window.__shellAt)
}

async function timeline(page) {
  return page.evaluate(() => performance.getEntriesByType('resource')
    .filter(e => new URL(e.name).pathname.startsWith('/api/'))
    .map(e => ({ path: new URL(e.name).pathname, start: e.startTime, end: e.responseEnd })))
}

function count(backend, path, { method = 'GET', status } = {}) {
  return backend.log.filter(r => r.path === path && r.method === method && (status === undefined || r.status === status)).length
}

// Longest chain of requests where each starts only after the previous one
// answered, among requests that finished before `until`: the number of
// network round trips the user waited for in sequence.
function serialDepth(log, until) {
  const done = log.filter(r => r.end <= until).sort((a, b) => a.start - b.start)
  const depth = []
  done.forEach((r, i) => {
    depth[i] = 1 + Math.max(0, ...done.slice(0, i).map((q, j) => (q.end <= r.start + 1 ? depth[j] : 0)))
  })
  return Math.max(0, ...depth)
}

function report(title, entries, shellAt) {
  if (!process.env.STARTUP_REQUEST_REPORT) return
  const rows = new Map()
  for (const r of entries) {
    const key = r.path
    const row = rows.get(key) || { total: 0, beforeShell: 0, first: r.start }
    row.total++
    if (r.end <= shellAt) row.beforeShell++
    rows.set(key, row)
  }
  console.log(`\n${title}: shell at ${Math.round(shellAt)} ms, serial round trips before shell ${serialDepth(entries, shellAt)}, ${entries.length} requests`)
  console.log('| Request | Total | Before shell | First start (ms) |\n| --- | ---: | ---: | ---: |')
  for (const [key, row] of [...rows].sort((a, b) => a[1].first - b[1].first)) {
    console.log(`| ${key} | ${row.total} | ${row.beforeShell} | ${Math.round(row.first)} |`)
  }
}

// Let deferred maintenance run to completion before counting.
async function settle(page, backend, path = MAINTENANCE[1]) {
  await page.waitForFunction(() => true)
  const deadline = Date.now() + 15_000
  while (!backend.log.some(r => r.path === path) && Date.now() < deadline) await page.waitForTimeout(100)
  await page.waitForTimeout(1500)
}

test('startup reads one profile roster and one settings snapshot, two serial round trips before the shell', async t => {
  const { page, backend } = await boot(t)
  const shellAt = await shellVisibleAt(page)
  await settle(page, backend)
  const entries = await timeline(page)
  report('Startup (unlocked profile)', entries, shellAt)

  assert.equal(count(backend, '/api/profiles'), 1, 'one /profiles roster per server scope')
  assert.equal(count(backend, '/api/settings'), 1, 'one /settings snapshot per profile scope')
  assert.ok(serialDepth(entries, shellAt) <= 2, `serial round trips before the shell: ${serialDepth(entries, shellAt)}`)
})

test('optional maintenance waits for the usable shell, runs one task at a time, and still runs', async t => {
  const { page, backend } = await boot(t)
  const shellAt = await shellVisibleAt(page)
  await settle(page, backend)

  const maintenance = (await timeline(page)).filter(r => MAINTENANCE.includes(r.path))
  for (const path of MAINTENANCE) assert.ok(maintenance.some(r => r.path === path), `${path} still runs`)
  for (const r of maintenance) assert.ok(r.start >= shellAt, `${r.path} started at ${Math.round(r.start)} before the shell at ${Math.round(shellAt)}`)
  assertSequential(maintenance)
})

// Each maintenance task's network work ends before the next task's begins.
function assertSequential(work) {
  const first = work.filter((r, i) => work.findIndex(o => o.path === r.path) === i).sort((a, b) => a.start - b.start)
  for (let i = 1; i < first.length; i++) {
    assert.ok(first[i].start >= first[i - 1].end, `${first[i].path} at ${Math.round(first[i].start)} overlapped ${first[i - 1].path} ending ${Math.round(first[i - 1].end)}`)
  }
}

test('the desktop update loop finishes its first check before the next maintenance task', async t => {
  const { page, backend } = await boot(t, { desktop: true })
  const shellAt = await shellVisibleAt(page)
  await settle(page, backend)
  const checks = await page.evaluate(() => window.updateChecks)
  assert.equal(checks.length, 1, 'the desktop update check still runs')
  assert.ok(checks[0].start >= shellAt, 'after the shell')
  const work = [...(await timeline(page)).filter(r => MAINTENANCE.includes(r.path)), { path: 'app update check', ...checks[0] }]
  for (const path of MAINTENANCE) assert.ok(work.some(r => r.path === path), `${path} still runs`)
  assertSequential(work)
})

test('a PIN-locked start sees only profile metadata, then unlock fetches its settings fresh', async t => {
  const { page, backend } = await boot(t, { profiles: [profile('main', { has_pin: true })], pins: { main: '2468' } })
  await page.locator('.lock-screen-profile-dropdown').waitFor({ timeout: 30_000 })
  await page.waitForTimeout(500)
  // Pre-unlock: the roster is the only metadata read; nothing protected was served or requested.
  assert.equal(count(backend, '/api/profiles'), 1)
  assert.equal(count(backend, '/api/settings', { status: 200 }), 0)
  assert.ok(count(backend, '/api/settings') <= 1, 'at most the early settings request, refused')
  assert.equal(count(backend, '/api/projects'), 0)
  assert.equal(await page.evaluate(async () => (await import('/src/composables/useBootstrapSnapshot.js')).peekSettingsSnapshot()), null)
  const before = count(backend, '/api/settings')
  await page.keyboard.type('2468')
  await page.keyboard.press('Enter')
  await page.locator('.top-bar').first().waitFor({ state: 'visible', timeout: 30_000 })
  await page.waitForTimeout(500)
  assert.equal(count(backend, '/api/settings') - before, 1, 'unlock fetches settings once, fresh')
  assert.equal(count(backend, '/api/settings', { status: 200 }), 1)

  // Locking discards the protected snapshot: the next unlock must refetch.
  await page.keyboard.press(process.platform === 'darwin' ? 'Meta+Shift+L' : 'Control+Shift+L')
  await page.locator('.lock-screen-profile-dropdown').waitFor({ timeout: 10_000 })
  const locked = count(backend, '/api/settings')
  await page.keyboard.type('2468')
  await page.keyboard.press('Enter')
  await page.locator('.top-bar').first().waitFor({ state: 'visible', timeout: 30_000 })
  await page.waitForTimeout(500)
  assert.equal(count(backend, '/api/settings') - locked, 1, 'unlock after a lock refetches settings')
  // Unlocking still runs deferred maintenance for the profile.
  await settle(page, backend)
  assert.ok(count(backend, '/api/stimpack-marketplace/check-updates') >= 1)
})

test('a deep link whose route guard is still fetching is not replaced by the saved route', async t => {
  // Startup now finishes before the board's owner check answers.
  const { page, backend } = await boot(t, { path: 'boards/7', savedRoute: '/browse' })
  await shellVisibleAt(page)
  await settle(page, backend)
  assert.equal(new URL(page.url()).pathname, '/boards/7')
})

test('a profile unlocked by a cached PIN reuses the roster for its PIN policy', async t => {
  const { page, backend } = await boot(t, { profiles: [profile('main', { has_pin: true })], pins: { main: '2468' }, cachedPin: { profileId: 'main', pin: '2468' } })
  const shellAt = await shellVisibleAt(page)
  await settle(page, backend)
  assert.equal(await page.locator('.lock-screen-profile-dropdown').count(), 0)
  assert.equal(count(backend, '/api/profiles'), 1, 'lock check and idle policy share the startup roster')
  assert.equal(count(backend, '/api/settings'), 1)
  assert.equal(count(backend, '/api/settings', { status: 200 }), 1)
  assert.ok(serialDepth(await timeline(page), shellAt) <= 2)
})

test('a PIN past its deadline while timers were suspended is not satisfied from the snapshot', async t => {
  const { page, backend } = await boot(t, {
    profiles: [profile('main', { has_pin: true })], pins: { main: '2468' },
    cachedPin: { profileId: 'main', pin: '2468' },
  })
  await shellVisibleAt(page)
  const before = count(backend, '/api/settings')
  const result = await page.evaluate(async () => {
    const { useSettingsApi } = await import('/src/composables/useSettingsApi.js')
    const pinLock = await import('/src/composables/usePinLock.js')
    const { fetchSettings } = useSettingsApi()
    // A 15-second limit, a fresh unlock, and a fresh snapshot.
    pinLock.syncPinTimeouts([{ id: 'main', has_pin: true, pin_idle_timeout_minutes: 0.25 }])
    pinLock.cachePin('main', '2468')
    await fetchSettings()
    const early = (await fetchSettings({ reuse: true })).profile_id
    // The wall clock moves past the PIN deadline without delivering any timer
    // (sleep), still well inside the snapshot's own reuse window, and the very
    // next thing the page does is reuse settings.
    const realNow = Date.now
    const jumped = realNow() + 16_000
    Date.now = () => jumped
    let pending
    try {
      pending = fetchSettings({ reuse: true })
    } finally {
      Date.now = realNow
    }
    const late = await pending.then(s => s.profile_id, e => e.response?.status ?? e.message)
    return { early, late, pin: pinLock.getCachedPin('main') }
  })
  assert.deepEqual(result, { early: 'main', late: 403, pin: null }, 'past the deadline only the server may answer, and it refuses')
  assert.equal(count(backend, '/api/settings') - before, 2, 'one fresh read, then the refused one; the early reuse asked nothing')
})

test('a refusal after a successful read leaves nothing protected to reuse', async t => {
  const { page, backend } = await boot(t)
  await shellVisibleAt(page)
  await settle(page, backend)
  backend.pins.main = '1357' // e.g. a PIN set from another client
  const result = await page.evaluate(async () => {
    const { useSettingsApi } = await import('/src/composables/useSettingsApi.js')
    const { fetchSettings } = useSettingsApi()
    const status = e => e.response?.status ?? e.message
    const fresh = await fetchSettings().then(() => 'served', status)
    const reused = await fetchSettings({ reuse: true }).then(() => 'served', status)
    return { fresh, reused }
  })
  assert.deepEqual(result, { fresh: 403, reused: 403 })
})

test('profile switches, server switches, and lock events invalidate the right snapshots', async t => {
  const { page, backend } = await boot(t, { profiles: [profile('main'), profile('other')] })
  await shellVisibleAt(page)
  await settle(page, backend)
  const result = await page.evaluate(async () => {
    const snap = await import('/src/composables/useBootstrapSnapshot.js')
    const { setCurrentProfileId } = await import('/src/composables/useProfile.js')
    const { useSettingsApi } = await import('/src/composables/useSettingsApi.js')
    const { fetchSettings } = useSettingsApi()
    const out = {}
    out.reused = (await fetchSettings({ reuse: true })).profile_id
    setCurrentProfileId('other')
    out.switched = (await fetchSettings({ reuse: true })).profile_id
    setCurrentProfileId('main')
    out.back = (await fetchSettings({ reuse: true })).profile_id
    window.dispatchEvent(new CustomEvent('pin-auto-locked', { detail: { profileId: 'main' } }))
    out.afterLock = snap.peekSettingsSnapshot() === null
    await fetchSettings({ reuse: true })
    window.dispatchEvent(new Event('stimma:workspace-changing'))
    out.afterServerSwitch = snap.peekSettingsSnapshot() === null && snap.peekProfilesSnapshot() === null
    return out
  })
  assert.deepEqual(result, { reused: 'main', switched: 'other', back: 'main', afterLock: true, afterServerSwitch: true })
  const settings = backend.log.filter(r => r.path === '/api/settings').map(r => r.profileId)
  // Startup, then 'other' and 'main' again (switching away discards the old profile's snapshot), then after the lock.
  assert.deepEqual(settings, ['main', 'other', 'main', 'main'])
})
