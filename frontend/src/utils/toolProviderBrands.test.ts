import assert from 'node:assert/strict'
import test from 'node:test'

import { DEFAULT_COMFYUI_STP_URL, isComfyUIProvider, nextComfyUIIdentity, preserveConnectingToolProviderStatuses, toolProviderUpdateStartsConnection } from './toolProviderBrands.ts'

test('recognizes existing and guided ComfyUI providers', () => {
  assert.equal(isComfyUIProvider({ id: 'comfyui', name: 'ComfyUI' }), true)
  assert.equal(isComfyUIProvider({ id: 'comfyui-2', name: 'Render workstation' }), true)
  assert.equal(isComfyUIProvider({ id: 'tool-lab', name: 'Tool lab' }), false)
  assert.equal(DEFAULT_COMFYUI_STP_URL, 'ws://localhost:8188/stp-v1')
})

test('assigns stable names without asking during guided setup', () => {
  assert.deepEqual(nextComfyUIIdentity([]), { id: 'comfyui', name: 'ComfyUI' })
  assert.deepEqual(
    nextComfyUIIdentity([{ id: 'comfyui' }, { id: 'comfyui-2' }]),
    { id: 'comfyui-3', name: 'ComfyUI 3' },
  )
})

test('identifies updates that start a provider connection', () => {
  assert.equal(toolProviderUpdateStartsConnection({ enabled: true }), true)
  assert.equal(toolProviderUpdateStartsConnection({ url: 'ws://localhost:8188/stp-v1' }), true)
  assert.equal(toolProviderUpdateStartsConnection({ auth_token: 'secret' }), true)
  assert.equal(toolProviderUpdateStartsConnection({ enabled: false }), false)
  assert.equal(toolProviderUpdateStartsConnection({ name: 'Render box' }), false)
})

test('does not regress an optimistic connection during an intermediate refresh', () => {
  assert.deepEqual(
    preserveConnectingToolProviderStatuses(
      [{ id: 'comfyui', status: 'connecting', enabled: true }],
      [{ id: 'comfyui', status: 'disconnected', enabled: true, url: 'ws://localhost:8188/stp-v1' }],
    ),
    [{ id: 'comfyui', status: 'connecting', enabled: true, url: 'ws://localhost:8188/stp-v1' }],
  )
  assert.equal(
    preserveConnectingToolProviderStatuses(
      [{ id: 'comfyui', status: 'connecting', enabled: true }],
      [{ id: 'comfyui', status: 'error', enabled: true }],
    )[0].status,
    'error',
  )
})
