import test from 'node:test'
import assert from 'node:assert/strict'
import { effectiveWay, foreverSlot, jobContextImages, prepareErrorCode, prepareFailure, programRunActions, shapePromptOptions, type PromptOptionsContext } from './fluentSubmit.ts'

const saved = (extra: Record<string, any> = {}) => ({
  autoImprove: { enabled: true, instructions: '' },  // a new tool: Detail level High
  translate: { enabled: false, language: 'zh-Hans' },
  programPins: { hair: ['bob'] },
  ...extra,
})
const ctx = (extra: Partial<PromptOptionsContext> = {}): PromptOptionsContext => ({
  fluentOn: true,
  llmUnconfigured: false,
  toolHasPrompt: true,
  unsupported: false,
  enhance: { model: 'flux', mode: 'text' },
  program: { enabled: true, pins: {} },
  ...extra,
})

test('no chat model: every run is Direct, whatever Detail level says', () => {
  assert.equal(effectiveWay({ raw: false, direct: false, llmUnconfigured: true }), 'direct')
  assert.equal(effectiveWay({ raw: true, direct: false, llmUnconfigured: true }), 'raw')
  const out = shapePromptOptions(saved({ translate: { enabled: true, language: 'fr' } }), ctx({ llmUnconfigured: true }))
  assert.equal(out.autoImprove.enabled, false, 'no per-image Enhance, so the backend never needs a model')
  assert.equal(out.program, undefined, 'no prepared program')
  assert.equal(out.translate.enabled, false)
  assert.equal(out.raw, undefined)
})

test('no chat model on a tool that cannot be prepared is still Direct', () => {
  const out = shapePromptOptions(saved(), ctx({ llmUnconfigured: true, unsupported: true }))
  assert.equal(out.autoImprove.enabled, false)
})

test('Direct sends no program and no Enhance', () => {
  const out = shapePromptOptions(saved({ direct: true }), ctx())
  assert.equal(out.autoImprove.enabled, false)
  assert.equal(out.program, undefined)
  assert.equal(out.loraTriggers, true)
})

test('Raw goes untouched', () => {
  const out = shapePromptOptions(saved({ raw: true, translate: { enabled: true, language: 'fr' } }), ctx())
  assert.equal(out.raw, true)
  assert.equal(out.autoImprove.enabled, false)
  assert.equal(out.translate.enabled, false)
})

test('Fluent carries the program and the enhancer context', () => {
  const out = shapePromptOptions(saved(), ctx())
  assert.deepEqual(out.program, { enabled: true, pins: {} })
  assert.equal(out.autoImprove.enabled, true)
  assert.equal(out.autoImprove.model, 'flux')
  assert.equal(out.loraNotes, true)
})

test('a tool that cannot be prepared writes a fuller prompt even when Yours was saved', () => {
  const out = shapePromptOptions(saved({ autoImprove: { enabled: false } }), ctx({ unsupported: true, program: undefined }))
  assert.equal(out.autoImprove.enabled, true)
})

test('tools without a prompt never enhance or translate', () => {
  const out = shapePromptOptions(saved({ translate: { enabled: true, language: 'fr' } }), ctx({ toolHasPrompt: false, unsupported: true }))
  assert.equal(out.autoImprove.enabled, false)
  assert.equal(out.translate.enabled, false)
})

test('without the feature, newer settings are dropped and Enhance goes as saved', () => {
  const out = shapePromptOptions(saved({ raw: true, direct: true, loraTriggers: false, loraNotes: false }), ctx({ fluentOn: false, llmUnconfigured: true, program: undefined }))
  assert.equal(out.raw, undefined)
  assert.equal(out.direct, undefined)
  assert.equal(out.loraTriggers, undefined)
  assert.equal(out.autoImprove.enabled, true, 'classic Enhance fails visibly with no model')
})

test('forever: a failed read stops instead of running the old prompt', () => {
  assert.deepEqual(foreverSlot({ needsPrepare: true, status: 'error', readyPrompt: 'old prompt', editing: false }), { kind: 'failed' })
})

test('forever: runs the previous prompt while the new one is written or prepared', () => {
  assert.deepEqual(foreverSlot({ needsPrepare: true, status: 'stale', readyPrompt: 'old', editing: false }), { kind: 'previous', prompt: 'old', prepare: true })
  assert.deepEqual(foreverSlot({ needsPrepare: true, status: 'stale', readyPrompt: 'old', editing: true }), { kind: 'previous', prompt: 'old', prepare: false })
  assert.deepEqual(foreverSlot({ needsPrepare: true, status: 'busy', readyPrompt: 'old', editing: false }), { kind: 'previous', prompt: 'old', prepare: false })
  assert.deepEqual(foreverSlot({ needsPrepare: true, status: 'stale', readyPrompt: null, editing: false }), { kind: 'prepare' })
  assert.deepEqual(foreverSlot({ needsPrepare: false, status: 'ready', readyPrompt: 'x', editing: false }), { kind: 'ready' })
})

test('prepare errors: only no response means the chat model is unreachable', () => {
  assert.equal(prepareErrorCode({ code: 'ECONNABORTED' }), 'llm_unavailable')
  assert.equal(prepareErrorCode({ response: { status: 500, data: { detail: 'Internal Server Error' } } }), undefined)
  assert.equal(prepareErrorCode({ response: { status: 502, data: {} } }), undefined)
  assert.equal(prepareErrorCode({ response: { status: 424, data: { detail: { code: 'llm_unavailable' } } } }), 'llm_unavailable')
  assert.equal(prepareErrorCode({ response: { status: 424, data: { detail: { code: 'llm_not_configured' } } } }), 'llm_not_configured')
  assert.match(prepareFailure(undefined, 'Brand').message, /^Brand couldn’t read this prompt/)
  assert.equal(prepareFailure('llm_not_configured', 'Brand').action, 'settings')
  assert.equal(prepareFailure('llm_unavailable', 'Brand').action, 'retry')
})

const run = { key: 'k1', draws: [
  { id: 'hair', value: 'bob' }, { id: 'gone', value: 'x' }, { id: 'coat', value: 'parka' },
  { id: 'param.cfg', kind: 'param', value: 4 }, { id: 'detail', hidden: true, value: 'lamp' },
] }
const options: Record<string, string[]> = { hair: ['bob', 'pixie'], coat: ['trench'] }
const optionsOf = (id: string) => options[id] ?? null

test('Same draws, new seed only against the program the image used', () => {
  assert.equal(programRunActions(run, { key: 'k1', status: 'ready', optionsOf }).replay, true)
  const moved = programRunActions(run, { key: 'k2', status: 'ready', optionsOf })
  assert.equal(moved.replay, false)
  assert.ok(moved.reason)
  assert.equal(programRunActions(run, { key: 'k1', status: 'stale', optionsOf }).replay, false)
  assert.equal(programRunActions(run, { key: null, status: 'off', optionsOf }).replay, false)
  assert.equal(programRunActions({ draws: run.draws }, { key: 'k1', status: 'ready', optionsOf }).replay, false)
})

test('Use these choices pins only what the prompt still offers', () => {
  assert.deepEqual(programRunActions(run, { key: 'k2', status: 'ready', optionsOf }).pins, { hair: ['bob'] })
  assert.deepEqual(programRunActions(run, { key: null, status: 'off', optionsOf: () => null }).pins, {})
})

test('batch mode reads the prompt for one job: one batched image plus fixed references', () => {
  assert.deepEqual(jobContextImages({ inputImages: ['a', 'b', 'c'], refImages: ['r'], batchMode: true, batchField: 'input_images' }), ['a', 'r'])
  assert.deepEqual(jobContextImages({ inputImages: ['a', 'b'], refImages: [], batchMode: true, batchField: null }), ['a'])
  assert.deepEqual(jobContextImages({ inputImages: ['a', 'b'], refImages: [], batchMode: true, batchField: 'input_videos' }), ['a', 'b'])
  assert.deepEqual(jobContextImages({ inputImages: ['a', 'b'], refImages: ['r'], batchMode: false }), ['a', 'b', 'r'])
})
