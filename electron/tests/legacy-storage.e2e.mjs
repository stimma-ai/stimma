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
  launchShell,
  makeSandbox,
  startFrontendServer,
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

// Fixture WKWebView database (schema matches the real ItemTable).
const fixtureDb = path.join(sandbox.dir, 'localstorage.sqlite3')
const rows = [
  ['profileId', 'profile-legacy1'],
  ['stimma_bundle_id', 'ai.stimma.stimma.canary'],
  ['stimma_ai.stimma.stimma.canary_default_global_onboarding_completed', '1'],
  ['stimma_ai.stimma.stimma.canary_default_profile-legacy1_workspace_tabs', '{"tabs":[{"id":"tool-1"}]}'],
  ['stimma_global_theme', 'dark'],
]
const inserts = rows
  .map(([k, v]) => `INSERT INTO ItemTable VALUES ('${k}', X'${utf16leHex(v)}');`)
  .join('\n')
execFileSync('sqlite3', [
  fixtureDb,
  `CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB NOT NULL ON CONFLICT FAIL);\n${inserts}`,
])

const markerPath = path.join(sandbox.dataDir, 'webkit-storage-imported.json')
const launch = () =>
  launchShell({ sandbox, frontendPort: port }).then(async (app) => {
    // The harness launches in dev mode; the env override activates the import.
    return app
  })

// launchShell doesn't pass custom env; splice the override into process.env
// for the child (harness spreads process.env).
process.env.STIMMA_LEGACY_STORAGE_DB = fixtureDb

const app = await launch()
try {
  const page = await app.firstWindow()
  await page.waitForLoadState('domcontentloaded')

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
} finally {
  await app.close()
}

// Second launch: marker gates the import; existing values must not be
// clobbered even though the fixture is still present. Mutate a value in the
// fixture to prove nothing is re-read.
execFileSync('sqlite3', [
  fixtureDb,
  `UPDATE ItemTable SET value = X'${utf16leHex('CLOBBERED')}' WHERE key = 'stimma_global_theme';`,
])

const app2 = await launch()
try {
  const page = await app2.firstWindow()
  await page.waitForLoadState('domcontentloaded')
  const theme = await page.evaluate(() => localStorage.getItem('stimma_global_theme'))
  check('second launch does not re-import (marker gate)', theme === 'dark')
} finally {
  await app2.close()
}

delete process.env.STIMMA_LEGACY_STORAGE_DB
server.close()
sandbox.cleanup()

if (failed) process.exit(1)
console.log('legacy-storage e2e: all checks passed')
