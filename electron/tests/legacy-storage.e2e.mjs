// Legacy-storage import e2e: a fixture WKWebView localstorage.sqlite3 is
// injected via STIMMA_LEGACY_STORAGE_DB; the shell must seed the page's
// localStorage before any script runs, write the one-shot marker, and skip
// the import on the next launch.
//
// Run: node electron/tests/legacy-storage.e2e.mjs (repo root; needs electron +
// frontend + stimma-native builds; uses the system sqlite3 CLI for fixtures)

import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import {
  assertPrereqs,
  electronBinary,
  electronRoot,
  launchShell,
  makeSandbox,
  startFrontendServer,
  waitForFrontendWindow,
} from './harness.mjs'

assertPrereqs()

let failed = false
const check = (label, condition) => {
  if (condition) console.log(`ok - ${label}`)
  else {
    failed = true
    console.error(`FAIL - ${label}`)
  }
}

const utf16leHex = (text) =>
  Buffer.from(text, 'utf16le').toString('hex')

const { server, port } = await startFrontendServer()
const sandbox = makeSandbox()
fs.mkdirSync(sandbox.dataDir, { recursive: true })

// Fixture Tauri database: WebView2/Chromium LevelDB on Windows, WebKit's
// SQLite/flat-file storage on macOS/Linux.
const fixtureDb = process.platform === 'win32'
  ? path.join(sandbox.dataDir, 'browser', 'EBWebView', 'Default', 'Local Storage', 'leveldb')
  : process.platform === 'linux'
  ? path.join(sandbox.dataDir, 'browser', 'localstorage', 'tauri_localhost_0.localstorage')
  : path.join(sandbox.dir, 'localstorage.sqlite3')
const rows = [
  ['profileId', 'profile-legacy1'],
  ['stimma_bundle_id', 'ai.stimma.stimma.canary'],
  ['stimma_ai.stimma.stimma.canary_default_global_onboarding_completed', '1'],
  ['stimma_ai.stimma.stimma.canary_default_profile-legacy1_workspace_tabs', '{"tabs":[{"id":"tool-1"}]}'],
  ['stimma_global_theme', 'dark'],
]

const writeWindowsFixture = (fixtureRows) => {
  const env = { ...process.env }
  delete env.ELECTRON_RUN_AS_NODE
  execFileSync(electronBinary, [
    path.join(electronRoot, 'tests', 'write-chromium-storage-fixture.cjs'),
    path.join(sandbox.dataDir, 'browser', 'EBWebView', 'Default'),
    Buffer.from(JSON.stringify(fixtureRows)).toString('base64'),
  ], { env, stdio: 'inherit' })
}

if (process.platform === 'win32') {
  writeWindowsFixture(rows)
} else {
  fs.mkdirSync(path.dirname(fixtureDb), { recursive: true })
  const inserts = rows
    .map(([k, v]) => `INSERT INTO ItemTable VALUES ('${k}', X'${utf16leHex(v)}');`)
    .join('\n')
  execFileSync('sqlite3', [
    fixtureDb,
    `CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB NOT NULL ON CONFLICT FAIL);\n${inserts}`,
  ])
}

const markerPath = path.join(sandbox.dataDir, 'webkit-storage-imported.json')
// A prior transient helper/read failure may have left a negative marker.
// It must not permanently suppress migration once the source is readable.
fs.writeFileSync(markerPath, JSON.stringify({ imported: false, reason: 'no-stimma-origin' }))
const launch = () => launchShell({ sandbox, frontendPort: port })

// macOS uses a direct fixture override. Linux/Windows exercise their real
// platform discovery paths.
if (process.platform === 'darwin') process.env.STIMMA_LEGACY_STORAGE_DB = fixtureDb

const app = await launch()
try {
  const page = await app.firstWindow()
  await waitForFrontendWindow(page, port)

  const values = await page.evaluate((keys) => {
    const out = {}
    for (const key of keys) out[key] = localStorage.getItem(key)
    return out
  }, rows.map(([k]) => k))

  check('profileId imported', values['profileId'] === 'profile-legacy1')
  check(
    'onboarding flag imported (no welcome replay)',
    values['stimma_ai.stimma.stimma.canary_default_global_onboarding_completed'] === '1',
  )
  check(
    'workspace tabs imported',
    values['stimma_ai.stimma.stimma.canary_default_profile-legacy1_workspace_tabs'] ===
      '{"tabs":[{"id":"tool-1"}]}',
  )
  check('theme imported', values['stimma_global_theme'] === 'dark')

  // Marker written and reports the import.
  const marker = JSON.parse(fs.readFileSync(markerPath, 'utf8'))
  check(`marker written (imported=${marker.imported}, written=${marker.written})`, marker.imported === true)
  check('marker counted the writes', marker.written === rows.length)

  // Remove one imported value from Electron. A marker-gated second launch
  // must leave it absent even after the Tauri source changes.
  await page.evaluate(() => localStorage.removeItem('stimma_global_theme'))
} finally {
  await app.close()
}

// Second launch: marker gates the import; existing values must not be
// clobbered even though the fixture is still present. Mutate a value in the
// fixture to prove nothing is re-read.
if (process.platform === 'win32') {
  writeWindowsFixture([['stimma_global_theme', 'CLOBBERED']])
} else {
  execFileSync('sqlite3', [
    fixtureDb,
    `UPDATE ItemTable SET value = X'${utf16leHex('CLOBBERED')}' WHERE key = 'stimma_global_theme';`,
  ])
}

const app2 = await launch()
try {
  const page = await app2.firstWindow()
  await waitForFrontendWindow(page, port)
  const theme = await page.evaluate(() => localStorage.getItem('stimma_global_theme'))
  check('second launch does not re-import (marker gate)', theme === null)
} finally {
  await app2.close()
}

delete process.env.STIMMA_LEGACY_STORAGE_DB
server.close()
sandbox.cleanup()

if (failed) process.exit(1)
console.log('legacy-storage e2e: all checks passed')
