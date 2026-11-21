import assert from 'node:assert/strict'
import test from 'node:test'
import { initHelper, helperRequest } from '../src/helper.ts'
import { makeScratchDir } from './scratch.mjs'

test('a helper that cannot start rejects its calls instead of throwing', async () => {
  const scratch = makeScratchDir('helper-test-')
  const unhandled: unknown[] = []
  const onUncaught = (error: unknown) => unhandled.push(error)
  process.on('uncaughtException', onUncaught)
  const previous = (process as any).resourcesPath
  try {
    // No stimma-native binary here, so the spawn fails with ENOENT.
    ;(process as any).resourcesPath = scratch.dir
    initHelper({ dev: false, cacheDir: scratch.dir } as any)
    await assert.rejects(helperRequest('voice_model_status'), /helper failed/)
    // The next request spawns afresh and settles the same way.
    await assert.rejects(helperRequest('voice_model_status'), /helper failed/)
    await new Promise((resolve) => setTimeout(resolve, 50))
    assert.deepEqual(unhandled, [])
  } finally {
    process.off('uncaughtException', onUncaught)
    ;(process as any).resourcesPath = previous
    scratch.cleanup()
  }
})
