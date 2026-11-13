import assert from 'node:assert/strict'
import test from 'node:test'
import { isAwaitingSwitch, isNotServed, replacementFor, servedChange } from './servedChange.ts'

const model = (modelId: string, extra = {}) => ({ id: `local-gpu:${modelId}`, model_id: modelId, name: modelId, enabled: true, served: true, ...extra })
const provider = (models: any[], unadded: any[] = [], extra = {}) => ({
  kind: 'local',
  last_test_passed: true,
  models,
  served: { missing: models.filter(m => m.served === false).map(m => m.model_id), unadded },
  ...extra,
})
const served = (id: string) => ({ id, name: id, context_length: 262144 })

test('one gone and one served offers a switch to it', () => {
  const change = servedChange(provider([model('step-3.7', { served: false })], [served('qwen-3.8-flash-next')]))
  assert.equal(change?.target?.id, 'qwen-3.8-flash-next')
  assert.equal(change?.verb, 'Switch')
  assert.equal(change?.description, 'Now serving qwen-3.8-flash-next')
  assert.deepEqual(change?.missing.map(m => m.model_id), ['step-3.7'])
})

test('several served lets the person choose', () => {
  const change = servedChange(provider([model('step-3.7', { served: false })], [served('a'), served('b')]))
  assert.equal(change?.target, null)
  assert.equal(change?.verb, 'Choose model')
  assert.equal(change?.description, 'step-3.7 is no longer served')
})

test('two gone and one served does not guess which it replaces', () => {
  const change = servedChange(provider([model('old-model', { served: false }), model('step-3.7', { served: false })], [served('new-model')]))
  assert.equal(change?.target, null)
  assert.equal(change?.verb, 'Choose model')
  assert.equal(change?.description, 'old-model, step-3.7 are no longer served')
})

test('nothing else served names the model with no action', () => {
  const change = servedChange(provider([model('step-3.7', { served: false })]))
  assert.equal(change?.verb, '')
  assert.equal(change?.description, 'step-3.7 is no longer served')
})

test('a healthy provider, a hosted one or a failed connection offers nothing', () => {
  assert.equal(servedChange(provider([model('step-3.7')], [served('new-model')])), null)
  assert.equal(servedChange({ ...provider([model('step-3.7', { served: false })], [served('x')]), kind: 'openrouter' }), null)
  assert.equal(servedChange(provider([model('step-3.7', { served: false })], [served('x')], { last_test_passed: false })), null)
  assert.equal(servedChange(null), null)
})

test('a disabled model the server dropped is not a change', () => {
  assert.equal(servedChange(provider([model('step-3.7', { served: false, enabled: false })], [served('x')])), null)
})

test('the flag on the model is what makes it not served', () => {
  assert.equal(isNotServed(model('a', { served: false })), true)
  assert.equal(isNotServed(model('a')), false)
  assert.equal(isNotServed({ id: 'x', model_id: 'x' }), false)
})

test('a choice of a model no longer served waits for a switch', () => {
  const catalog = [
    { slug: 'local-gpu:old-model', status: 'not_served' },
    { slug: 'local-gpu:other', status: 'available' },
    { slug: 'stimma:cloud', status: 'cloud_unavailable' },
  ]
  assert.equal(isAwaitingSwitch(catalog, 'local-gpu:old-model'), true)
  assert.equal(isAwaitingSwitch(catalog, 'local-gpu:other'), false)
  assert.equal(isAwaitingSwitch(catalog, 'stimma:cloud'), false)
  // Gone from the catalog altogether: not waiting, ordinary recovery applies.
  assert.equal(isAwaitingSwitch(catalog, 'local-gpu:gone'), false)
  assert.equal(isAwaitingSwitch(catalog, null), false)
  assert.equal(isAwaitingSwitch(null, 'local-gpu:old-model'), false)
})

test('a switch moves only the choices it replaced', () => {
  const replaces = { 'local-gpu:old-model': 'local-gpu:new-model' }
  assert.equal(replacementFor('local-gpu:old-model', replaces), 'local-gpu:new-model')
  assert.equal(replacementFor('local-gpu:other', replaces), null)
  assert.equal(replacementFor('toString', replaces), null)
  assert.equal(replacementFor(null, replaces), null)
  assert.equal(replacementFor('local-gpu:old-model', undefined), null)
})
