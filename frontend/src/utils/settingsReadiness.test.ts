import assert from 'node:assert/strict'
import test from 'node:test'
import {
  hasUsableGenerationProvider,
  hasUsableLlmModel,
  isCatalogSelectableModel,
  isSelectableModel,
  modelRejectsImageInput,
  modelSelectionLabel,
  selectableModelForSlug,
} from './settingsReadiness.ts'

test('only explicit text-only metadata rejects image input', () => {
  assert.equal(modelRejectsImageInput({ input_modalities: ['text'] }), true)
  assert.equal(modelRejectsImageInput({ input_modalities: ['text', 'image'] }), false)
  assert.equal(modelRejectsImageInput({}), false)
  assert.equal(modelRejectsImageInput({ input_modalities: null }), false)
})

test('only explicitly available models are selectable', () => {
  assert.equal(isSelectableModel({ available: true }), true)
  assert.equal(isSelectableModel({ available: false }), false)
  assert.equal(isSelectableModel({}), false)
  assert.equal(isSelectableModel(null), false)
})

test('stale model choices are never presented as current models', () => {
  const stale = { slug: 'anthropic:opus', name: 'Claude Opus 4.8', available: false }
  const available = { slug: 'openai:sol', name: 'GPT-5.6 Sol', available: true }

  assert.equal(selectableModelForSlug([stale], stale.slug), undefined)
  assert.equal(modelSelectionLabel([stale], stale.slug), 'No models available')
  assert.equal(modelSelectionLabel([stale, available], stale.slug), 'Choose a model')
  assert.equal(modelSelectionLabel([stale, available], available.slug), 'GPT-5.6 Sol')
})

test('auto only resolves through an available concrete model', () => {
  const auto = { slug: 'auto', name: 'Auto', available: true, resolved_slug: 'anthropic:opus' }
  const stale = { slug: 'anthropic:opus', name: 'Claude Opus 4.8', available: false }

  assert.equal(isCatalogSelectableModel([auto, stale], auto), false)
  assert.equal(selectableModelForSlug([auto, stale], 'auto'), undefined)
  assert.equal(modelSelectionLabel([auto, stale], 'auto'), 'No models available')
})

test('requires a connected external provider that exposes tools', () => {
  assert.equal(hasUsableGenerationProvider([
    { type: 'builtin', status: 'connected', tool_count: 12 },
  ]), false)
  assert.equal(hasUsableGenerationProvider([
    { type: 'websocket', enabled: true, status: 'disconnected', tool_count: 12 },
  ]), false)
  assert.equal(hasUsableGenerationProvider([
    { type: 'stdio', enabled: true, status: 'connected', tool_count: 0 },
  ]), false)
  assert.equal(hasUsableGenerationProvider([
    { type: 'websocket', enabled: true, status: 'connected', tool_count: 12 },
  ]), true)
})

test('stimma cloud only counts toward readiness with a positive balance', () => {
  const cloudModel = { slug: 'stimma:sol', source: 'stimma_cloud', available: true }
  const auto = { slug: 'auto', source: 'auto', available: true, resolved_slug: 'stimma:sol' }
  const local = { slug: 'provider:model', source: 'provider', available: true }

  assert.equal(hasUsableLlmModel([cloudModel]), true)
  assert.equal(hasUsableLlmModel([cloudModel], { stimmaCloudUsable: true }), true)
  assert.equal(hasUsableLlmModel([cloudModel], { stimmaCloudUsable: false }), false)
  // 'auto' resolving to a cloud model is gated with it
  assert.equal(hasUsableLlmModel([auto, cloudModel], { stimmaCloudUsable: false }), false)
  // a non-cloud model still satisfies readiness at zero balance
  assert.equal(hasUsableLlmModel([cloudModel, local], { stimmaCloudUsable: false }), true)

  const cloudProvider = { id: 'stimma-cloud', type: 'websocket', enabled: true, status: 'connected', tool_count: 50 }
  const comfy = { id: 'comfy-1', type: 'websocket', enabled: true, status: 'connected', tool_count: 3 }
  assert.equal(hasUsableGenerationProvider([cloudProvider]), true)
  assert.equal(hasUsableGenerationProvider([cloudProvider], { stimmaCloudUsable: true }), true)
  assert.equal(hasUsableGenerationProvider([cloudProvider], { stimmaCloudUsable: false }), false)
  assert.equal(hasUsableGenerationProvider([cloudProvider, comfy], { stimmaCloudUsable: false }), true)
})

test('requires an available concrete or resolved LLM', () => {
  assert.equal(hasUsableLlmModel([
    { source: 'auto', available: false, resolved_slug: null },
  ]), false)
  assert.equal(hasUsableLlmModel([
    { source: 'provider', available: false },
  ]), false)
  assert.equal(hasUsableLlmModel([
    { slug: 'auto', source: 'auto', available: true, resolved_slug: 'provider:model' },
    { slug: 'provider:model', source: 'provider', available: true },
  ]), true)
  assert.equal(hasUsableLlmModel([
    { slug: 'auto', source: 'auto', available: true, resolved_slug: 'provider:model' },
    { slug: 'provider:model', source: 'provider', available: false },
  ]), false)
  assert.equal(hasUsableLlmModel([
    { source: 'provider', available: true },
  ]), true)
})
