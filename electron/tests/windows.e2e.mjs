// Window/profile semantics e2e: registry restore, open/focus profile
// windows, close-one-destroys vs close-last-hides, deleted-profile close,
// input validation on the IPC surface.
//
// Run: node electron/tests/windows.e2e.mjs (repo root; needs electron + frontend builds)

import fs from 'node:fs'
import path from 'node:path'
import {
  assertPrereqs,
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

const { server, port } = await startFrontendServer()
const sandbox = makeSandbox()

// Pre-seed a Tauri-era registry: two windows from the "fielded" install.
fs.mkdirSync(sandbox.dataDir, { recursive: true })
fs.writeFileSync(
  path.join(sandbox.dataDir, 'windows.json'),
  JSON.stringify({
    windows: [
      { label: 'main', profile_id: 'profile-one' },
      { label: 'profile-two', profile_id: 'two' },
    ],
  }),
)

const app = await launchShell({ sandbox, frontendPort: port })

const windowCount = () =>
  app.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows().filter((w) => !w.isDestroyed()).length,
  )

const visibleCount = () =>
  app.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows().filter((w) => !w.isDestroyed() && w.isVisible()).length,
  )

const registryOnDisk = () =>
  JSON.parse(fs.readFileSync(path.join(sandbox.dataDir, 'windows.json'), 'utf8')).windows

try {
  const first = await app.firstWindow()
  await waitForFrontendWindow(first, port)

  // -- session restore -------------------------------------------------------
  check(`restores both registry windows (got ${await windowCount()})`, (await windowCount()) === 2)

  // Identify each page's pinned profile through the real bridge.
  const windows = app.windows()
  const profiles = []
  for (const page of windows) {
    await waitForFrontendWindow(page, port)
    profiles.push(await page.evaluate(() => window.stimmaDesktop.getWindowProfile()))
  }
  check(
    `windows resolve pinned profiles (${JSON.stringify(profiles)})`,
    profiles.includes('profile-one') && profiles.includes('two'),
  )

  const pageFor = async (profileId) => {
    for (const page of app.windows()) {
      if ((await page.evaluate(() => window.stimmaDesktop.getWindowProfile())) === profileId) {
        return page
      }
    }
    return null
  }

  // -- open-profile-window: focus, not duplicate -----------------------------
  const mainPage = await pageFor('profile-one')
  await mainPage.evaluate(() => window.stimmaDesktop.openProfileWindow('two'))
  check('opening an already-open profile focuses instead of duplicating', (await windowCount()) === 2)

  // -- open-profile-window: new profile gets a new window --------------------
  const newWindowPromise = app.waitForEvent('window')
  await mainPage.evaluate(() => window.stimmaDesktop.openProfileWindow('three'))
  const thirdPage = await newWindowPromise
  await waitForFrontendWindow(thirdPage, port)
  check('new profile opens a third window', (await windowCount()) === 3)
  check(
    'third window is pinned to its profile',
    (await thirdPage.evaluate(() => window.stimmaDesktop.getWindowProfile())) === 'three',
  )
  check(
    'registry gained the profile-three entry',
    registryOnDisk().some((w) => w.profile_id === 'three'),
  )

  // -- report-window-profile persists ---------------------------------------
  await thirdPage.evaluate(() => window.stimmaDesktop.reportWindowProfile('three-renamed'))
  check(
    'reportWindowProfile persists to windows.json',
    registryOnDisk().some((w) => w.profile_id === 'three-renamed'),
  )

  // -- deleted-profile close: destroys when others remain --------------------
  // The reply can race the window teardown; a dead page counts as closed.
  const closed = await thirdPage
    .evaluate(() => window.stimmaDesktop.closeDeletedProfileWindow())
    .catch(() => 'window-died')
  check(
    'closeDeletedProfileWindow closes a non-last window',
    closed === true || closed === 'window-died',
  )
  await new Promise((r) => setTimeout(r, 300))
  check('window count back to 2', (await windowCount()) === 2)
  check(
    'registry dropped the deleted-profile entry',
    !registryOnDisk().some((w) => w.profile_id === 'three-renamed'),
  )

  // -- close one of two: destroys + registry removal -------------------------
  const twoPage = await pageFor('two')
  await twoPage.evaluate(() => window.stimmaDesktop.closeCurrentWindow()).catch(() => {})
  await new Promise((r) => setTimeout(r, 300))
  check('closing one of two windows destroys it', (await windowCount()) === 1)
  check(
    'registry dropped the closed window',
    !registryOnDisk().some((w) => w.profile_id === 'two'),
  )

  // -- close last: hides, app stays alive, registry keeps the entry ----------
  const lastPage = await pageFor('profile-one')
  await lastPage.evaluate(() => window.stimmaDesktop.closeCurrentWindow())
  await new Promise((r) => setTimeout(r, 300))
  check('last window survives close (hidden, not destroyed)', (await windowCount()) === 1)
  check('last window is hidden', (await visibleCount()) === 0)
  check(
    'registry still holds the hidden window for restore',
    registryOnDisk().some((w) => w.profile_id === 'profile-one'),
  )

  // The hidden window's renderer is still alive — IPC keeps working.
  check(
    'hidden window still answers IPC',
    (await lastPage.evaluate(() => window.stimmaDesktop.getWindowProfile())) === 'profile-one',
  )

  // -- deleted-profile close refuses on the last window ----------------------
  const refused = await lastPage.evaluate(() => window.stimmaDesktop.closeDeletedProfileWindow())
  check('closeDeletedProfileWindow returns false for the last window', refused === false)

  // -- IPC input validation --------------------------------------------------
  const rejects = (fn) => lastPage.evaluate(fn).then(() => false, () => true)
  check('openExternal rejects file:// URLs', await rejects(() => window.stimmaDesktop.openExternal('file:///etc/passwd')))
  check('openExternal rejects garbage', await rejects(() => window.stimmaDesktop.openExternal('not a url')))
  check('openAuthUrl rejects non-http schemes', await rejects(() => window.stimmaDesktop.openAuthUrl('x-apple.systempreferences:foo')))
  check('openPath rejects relative paths', await rejects(() => window.stimmaDesktop.openPath('../../etc')))
  check('revealItemInDir rejects relative paths', await rejects(() => window.stimmaDesktop.revealItemInDir('relative/path')))
  check('setWindowSize rejects absurd sizes', await rejects(() => window.stimmaDesktop.setWindowSize(-5, 50)))
  check('saveToDownloads rejects non-bytes', await rejects(() => window.stimmaDesktop.saveToDownloads('x.txt', 'stringdata')))
} finally {
  await app.close()
}

// Registry file after quit still holds the restore set (quit preserves it).
check(
  'quit preserves the restore set',
  registryOnDisk().some((w) => w.profile_id === 'profile-one'),
)

server.close()
sandbox.cleanup()

if (failed) process.exit(1)
console.log('electron windows e2e: all checks passed')
