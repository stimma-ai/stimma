import assert from 'node:assert/strict'
import test from 'node:test'

import { shouldPlayStageVideo } from '../src/utils/stageVideoPlayback.js'

const foregroundStage = {
  viewActive: true,
  layoutMode: 'stage',
  slideshowActive: false,
  compareActive: false,
  documentVisible: true,
  windowFocused: true,
}

test('stage video plays only on the foreground stage surface', () => {
  assert.equal(shouldPlayStageVideo(foregroundStage), true)

  for (const hiddenState of [
    { viewActive: false },
    { layoutMode: 'studio' },
    { slideshowActive: true },
    { compareActive: true },
    { documentVisible: false },
    { windowFocused: false },
  ]) {
    assert.equal(
      shouldPlayStageVideo({ ...foregroundStage, ...hiddenState }),
      false,
      `expected playback to stop for ${JSON.stringify(hiddenState)}`,
    )
  }
})
