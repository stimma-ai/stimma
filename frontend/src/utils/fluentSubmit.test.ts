import test from 'node:test'
import assert from 'node:assert/strict'
import { directImproves, effectiveWay, foreverSlot, isPrepareFailureCode, prepareBody, fallbackNotice, prepareErrorCode, prepareSettingsSig, readPending, shownKey, WORDS_AS_WRITTEN, programRunActions, shapePromptOptions, type PrepareInputs, type PromptOptionsContext } from './fluentSubmit.ts'

const saved = (extra: Record<string, any> = {}) => ({
  autoImprove: { enabled: true, instructions: '' },  // a new tool: Detail level High
  translate: { enabled: false, language: 'zh-Hans' },
  programChoices: { hair: { values: ['bob'] } },
  ...extra,
})
const ctx = (extra: Partial<PromptOptionsContext> = {}): PromptOptionsContext => ({
  fluentOn: true,
  llmUnconfigured: false,
  toolHasPrompt: true,
  unsupported: false,
  enhance: { model: 'flux', mode: 'text' },
  program: { enabled: true, choices: {} },
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

test('Direct sends no program, and is improved at the Detail level where its prompt describes a picture', () => {
  const out = shapePromptOptions(saved({ direct: true, autoImprove: { enabled: true, level: 'fill' } }), ctx({ directImproves: true }))
  assert.equal(out.direct, true)
  assert.equal(out.autoImprove.enabled, true)
  assert.equal(out.autoImprove.level, 'fill')
  assert.equal(out.program, undefined)
  assert.equal(out.loraTriggers, true)
})

test('Direct at Yours, on a prompt that is not a picture, or with no chat model, sends no Enhance', () => {
  const yours = shapePromptOptions(saved({ direct: true, autoImprove: { enabled: false } }), ctx({ directImproves: true }))
  assert.equal(yours.autoImprove.enabled, false)
  const edit = shapePromptOptions(saved({ direct: true }), ctx({ directImproves: false }))
  assert.equal(edit.autoImprove.enabled, false)
  const noModel = shapePromptOptions(saved({ direct: true }), ctx({ directImproves: true, llmUnconfigured: true }))
  assert.equal(noModel.autoImprove.enabled, false)
})

test('Direct improves a picture or a clip, never an edit, a sound or a structured format', () => {
  const t = { ideogram: false, h3: false, audio: false, inputImageCount: 0 }
  assert.equal(directImproves(t), true)
  assert.equal(directImproves({ ...t, inputImageCount: 1 }), false)
  assert.equal(directImproves({ ...t, ideogram: true }), false)
  assert.equal(directImproves({ ...t, h3: true }), false)
  assert.equal(directImproves({ ...t, audio: true }), false)
})

test('Raw goes untouched', () => {
  const out = shapePromptOptions(saved({ raw: true, translate: { enabled: true, language: 'fr' } }), ctx())
  assert.equal(out.raw, true)
  assert.equal(out.autoImprove.enabled, false)
  assert.equal(out.translate.enabled, false)
})

test('Fluent carries the program and the enhancer context', () => {
  const out = shapePromptOptions(saved(), ctx())
  assert.deepEqual(out.program, { enabled: true, choices: {} })
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

test('forever: a failed read keeps running, on the words as written, never the old prompt', () => {
  assert.deepEqual(foreverSlot({ needsPrepare: true, status: 'error', readyPrompt: 'old prompt', editing: false }), { kind: 'words' })
  assert.deepEqual(foreverSlot({ needsPrepare: true, status: 'error', readyPrompt: null, editing: true }), { kind: 'words' })
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
})

test('a prompt that couldn’t be read says so quietly, by cause, with one action and never “nothing ran”', () => {
  for (const code of [undefined, 'prepare_timeout', 'program_failed']) {
    assert.deepEqual(fallbackNotice(code, 'Brand'), { head: WORDS_AS_WRITTEN, action: 'retry' })
  }
  assert.deepEqual(fallbackNotice('llm_unavailable', 'Brand'), { head: 'Can’t reach your chat model', body: 'Using your words as written for now.', action: 'retry' })
  assert.deepEqual(fallbackNotice('llm_insufficient_balance', 'Brand'), { head: 'Your chat model has no balance left', body: 'Using your words as written for now.', action: 'settings' })
  assert.deepEqual(fallbackNotice('prompt_too_long', 'Brand'), { head: 'This prompt is too long to read', body: 'Using your words as written. Shorten it for variety.', action: 'none' })
  assert.equal(fallbackNotice('llm_not_configured', 'Brand').head, 'Brand needs a chat model')
  for (const code of ['prepare_timeout', 'llm_unavailable', 'llm_insufficient_balance', 'prompt_too_long', 'llm_not_configured']) {
    const n = fallbackNotice(code, 'Brand')
    assert.ok(!/nothing ran|turn it off|Direct/.test(`${n.head} ${n.body ?? ''}`), code)
  }
})

const world = {
  slots: [{ id: 'man', n: 1, kind: 'person' as const, label: 'Man', words: 'man' }],
  choices: [{ id: 'man', slot: 'man', kind: 'variants' as const, label: 'Man' }],
  states: {}, pools: {},
}
const run = { key: 'k1', version: 'slots-1', draws: [
  { id: 'man', value: 'tall man with a bob', about: 'man' }, { id: 'gone', value: 'x', about: 'gone' },
] }

test('an image made while the prompt couldn’t be read offers no Same draws and nothing to keep', () => {
  const words = programRunActions({ key: null, draws: [], fallback: { rung: 'words', code: 'prepare_timeout' } },
    { key: 'k1', status: 'ready', world })
  assert.deepEqual(words, { replay: false, reason: 'Made from your words as written.', use: false })
  const earlier = programRunActions({ ...run, key: 'k0', fallback: { rung: 'previous' } }, { key: 'k1', status: 'ready', world })
  assert.equal(earlier.replay, false)
  assert.equal(earlier.use, true)  // Use still offers what applies
})

test('Same draws, new seed only against the program the image used', () => {
  assert.equal(programRunActions(run, { key: 'k1', status: 'ready', world }).replay, true)
  const moved = programRunActions(run, { key: 'k2', status: 'ready', world })
  assert.equal(moved.replay, false)
  assert.ok(moved.reason)
  assert.equal(programRunActions(run, { key: 'k1', status: 'stale', world }).replay, false)
  assert.equal(programRunActions(run, { key: null, status: 'off', world }).replay, false)
  assert.equal(programRunActions({ draws: run.draws }, { key: 'k1', status: 'ready', world }).replay, false)
})

test('Use only for images made from slots, and only while the prompt is read and has a part', () => {
  assert.equal(programRunActions(run, { key: 'k2', status: 'ready', world }).use, true)
  assert.equal(programRunActions(run, { key: 'k1', status: 'stale', world }).use, false)
  // The old writer's images carry no slot version.
  assert.equal(programRunActions({ ...run, version: undefined }, { key: 'k1', status: 'ready', world }).use, false)
  assert.equal(programRunActions(run, { key: 'k1', status: 'ready', world: { ...world, choices: [] } }).use, false)
  // The slot's words changed since: nothing of it is in the prompt now.
  assert.equal(programRunActions(run, { key: 'k2', status: 'ready', world: { ...world, slots: [{ ...world.slots[0], words: 'old man' }] } }).use, false)
})

test('a program depends on the prompt and the tool only', () => {
  const inputs = (prompt: string, toolId = 't'): PrepareInputs => ({ toolId, prompt, projectId: 3 })
  assert.deepEqual(prepareBody(inputs('a <cat>'), { cache_only: true }), { tool_id: 't', prompt: 'a <cat>', project_id: 3, cache_only: true })
  assert.equal(prepareSettingsSig(inputs('a <cat>')), prepareSettingsSig(inputs('a <dog>')))
  assert.notEqual(prepareSettingsSig(inputs('a <cat>')), prepareSettingsSig(inputs('a <cat>', 'u')))
})

test('a prompt too long or no balance says what to do, without mechanics', () => {
  const long = fallbackNotice('prompt_too_long', 'Brand')
  assert.equal(long.action, 'none')
  assert.match(long.head, /too long/)
  assert.doesNotMatch(`${long.head} ${long.body}`, /\d|character/)
  assert.equal(fallbackNotice('llm_insufficient_balance', 'Brand').action, 'settings')
  assert.ok(isPrepareFailureCode('prompt_too_long') && isPrepareFailureCode('llm_unavailable'))
  // A slot reading the chat model got wrong runs on the words as written, and can be tried again.
  assert.ok(isPrepareFailureCode('reader_failed'))
  assert.equal(fallbackNotice('reader_failed', 'Brand').action, 'retry')
  // The old writer's refusal is gone: no route answers it now.
  assert.ok(!isPrepareFailureCode('prepare_declined'))
  assert.ok(!isPrepareFailureCode('job_failed') && !isPrepareFailureCode(null))
})

test('a prepare names the program the editor shows, only when it was prepared under these settings', () => {
  const settings = prepareSettingsSig({ toolId: 'flux', prompt: '', projectId: null })
  const sig = JSON.stringify({ prompt: 'a <man>', settings })
  assert.equal(shownKey({ key: 'abc' }, sig, settings), 'abc')
  assert.equal(shownKey({ key: 'abc' }, sig, prepareSettingsSig({ toolId: 'sdxl', prompt: '', projectId: null })), null)
  assert.equal(shownKey(null, sig, settings), null)
  assert.equal(shownKey({ key: null }, sig, settings), null)
  assert.equal(shownKey({ key: 'abc' }, null, settings), null)
})

test('a looked-up prompt whose readings were kept from before an edit is sent to be checked', () => {
  // every slot ready (carried), but the edit not checked yet: reading, and nothing working
  assert.equal(readPending('ready', { reading: true, working: false }, false), true)
  assert.equal(readPending('ready', { reading: true, working: false }, true), false, 'its read already started')
  assert.equal(readPending('ready', { reading: true, working: true }, false), false, 'being checked or read now')
  assert.equal(readPending('ready', { reading: false, working: false }, false), false, 'checked and kept')
  assert.equal(readPending('stale', null, true), true)
  assert.equal(readPending('busy', { reading: true }, false), false)
})
