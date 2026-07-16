import assert from 'node:assert/strict'
import test from 'node:test'
import {
  STIMMA_TOOL_PROVIDER_DISPLAY_NAME,
  isStimmaCloudTool,
  toolProviderDisplayName,
} from './stimmaCloud.ts'

test('uses Stimma as the canonical cloud tool-provider display name', () => {
  const provider = { provider_id: 'stimma-cloud', provider_name: 'Stimma Cloud' }
  assert.equal(STIMMA_TOOL_PROVIDER_DISPLAY_NAME, 'Stimma')
  assert.equal(isStimmaCloudTool(provider), true)
  assert.equal(toolProviderDisplayName(provider), 'Stimma')
})

test('normalizes legacy provider-only metadata', () => {
  assert.equal(isStimmaCloudTool({ provider_name: 'Stimma Cloud' }), true)
  assert.equal(isStimmaCloudTool({ provider_name: 'Stimma' }), true)
  assert.equal(toolProviderDisplayName({ provider_name: 'Stimma Cloud' }), 'Stimma')
})

test('leaves third-party provider names unchanged', () => {
  assert.equal(toolProviderDisplayName({ provider_id: 'comfyui', provider_name: 'ComfyUI' }), 'ComfyUI')
})
