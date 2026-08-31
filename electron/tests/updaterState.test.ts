import assert from 'node:assert/strict'
import test from 'node:test'
import { UpdaterState } from '../src/updaterState.ts'

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
