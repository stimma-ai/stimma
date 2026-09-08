import assert from 'node:assert/strict'
import test from 'node:test'
import { UpdaterState } from '../src/updaterState.ts'

test('closing repeated check handles leaves the Windows deferred update downloadable', () => {
  const state = new UpdaterState()
  const update = { version: '1.0.14-canary.982' }
  state.recordCheck(update) // Windows UI retains this handle; no download yet.
  for (let check = 0; check < 3; check++) {
    state.recordCheck({ ...update })
    state.closeAvailableHandle() // UI disposes the duplicate check handle.
    assert.deepEqual(state.available, update)
    assert.equal(state.hasDownloadedUpdate(), false)
  }
  state.markDownloaded(state.available!.version) // Actual button can download.
  assert.equal(state.hasDownloadedAvailableUpdate(), true)
  state.closeAvailableHandle()
  assert.equal(state.hasDownloadedUpdate(), true)
})

test('closing an older renderer handle does not erase a newly available version', () => {
  const state = new UpdaterState()
  state.recordCheck({ version: '1.0.14-canary.981' })
  state.recordCheck({ version: '1.0.14-canary.982' })
  state.closeAvailableHandle() // resetStaged closes the superseded UI handle.
  assert.equal(state.available?.version, '1.0.14-canary.982')
  state.recordCheck(null)
  assert.equal(state.available, null)
})

test('scheduled checks preserve a staged update until relaunch', () => {
  const state = new UpdaterState()

  state.recordCheck({ version: '1.0.14-canary.832' })
  state.markDownloaded('1.0.14-canary.832')
  state.closeAvailableHandle()

  // The periodic checker sees the same release while the UI still says
  // "Restart to finish". This was the production crash: recordCheck used to
  // clear the downloaded bit, selecting app.relaunch() while the quit hook
  // replaced and unmounted the running AppImage.
  state.recordCheck({ version: '1.0.14-canary.832' })
  state.closeAvailableHandle()

  assert.equal(state.hasDownloadedUpdate(), true)
  assert.equal(state.downloadedVersion, '1.0.14-canary.832')
})

test('a newer check does not masquerade the old staged package as downloaded', () => {
  const state = new UpdaterState()

  state.recordCheck({ version: '1.0.14-canary.832' })
  state.markDownloaded('1.0.14-canary.832')
  state.recordCheck({ version: '1.0.14-canary.833' })

  assert.equal(state.hasDownloadedUpdate(), true)
  assert.equal(state.hasDownloadedAvailableUpdate(), false)

  state.markDownloaded('1.0.14-canary.833')
  assert.equal(state.hasDownloadedAvailableUpdate(), true)
})
