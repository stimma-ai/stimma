import test from 'node:test'
import assert from 'node:assert/strict'
import { DECLINED_CODE, DECLINED_NOTICE, switchDeclinedToDirect, wasDeclined, withDirect, effectiveWay, foreverSlot, isPrepareFailureCode, prepareBody, fallbackNotice, prepareErrorCode, prepareSettingsSig, WORDS_AS_WRITTEN, programRunActions, shapePromptOptions, type PrepareInputs, type PromptOptionsContext } from './fluentSubmit.ts'

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

test('an image made while the prompt couldn’t be read offers no Same draws', () => {
  const words = programRunActions({ key: null, draws: [], fallback: { rung: 'words', code: 'prepare_timeout' } },
    { key: 'k1', status: 'ready', has: () => false })
  assert.deepEqual(words, { replay: false, reason: 'Made from your words as written.', pins: {} })
  const earlier = programRunActions({ key: 'k0', draws: [{ id: 'hair', value: 'bob' }], fallback: { rung: 'previous' } },
    { key: 'k0', status: 'ready', has: (id) => id === 'hair' })
  assert.equal(earlier.replay, false)
  assert.deepEqual(earlier.pins, { hair: ['bob'] })  // Use these choices still offers what applies
})

const run = { key: 'k1', draws: [
  { id: 'man.hair', value: 'bob' }, { id: 'gone', value: 'x' },
  { id: 'man.outfit', value: 'a navy parka over white jeans', template: 'a {main} parka over {neutral} jeans' },
  { id: 'detail', hidden: true, value: 'lamp' },
] }
const has = (id: string) => ['man.hair', 'man.outfit', 'detail'].includes(id)

test('Same draws, new seed only against the program the image used', () => {
  assert.equal(programRunActions(run, { key: 'k1', status: 'ready', has }).replay, true)
  const moved = programRunActions(run, { key: 'k2', status: 'ready', has })
  assert.equal(moved.replay, false)
  assert.ok(moved.reason)
  assert.equal(programRunActions(run, { key: 'k1', status: 'stale', has }).replay, false)
  assert.equal(programRunActions(run, { key: null, status: 'off', has }).replay, false)
  assert.equal(programRunActions({ draws: run.draws }, { key: 'k1', status: 'ready', has }).replay, false)
})

test('Use these choices keeps what the prompt still has; an outfit as its template', () => {
  assert.deepEqual(programRunActions(run, { key: 'k2', status: 'ready', has }).pins,
    { 'man.hair': ['bob'], 'man.outfit': ['a {main} parka over {neutral} jeans'] })
  assert.deepEqual(programRunActions(run, { key: null, status: 'off', has: () => false }).pins, {})
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
  assert.ok(!isPrepareFailureCode('job_failed') && !isPrepareFailureCode(null))
})

test('a prompt the chat model declined switches the box to Direct, says so plainly, and offers nothing to retry', () => {
  assert.ok(wasDeclined({ status: 'error', code: DECLINED_CODE }))
  // Only this prompt's own outcome: an old error, or any other failure, keeps Fluent.
  assert.ok(!wasDeclined({ status: 'stale', code: DECLINED_CODE }))
  assert.ok(!wasDeclined({ status: 'ready', code: DECLINED_CODE }))
  for (const code of ['prepare_timeout', 'program_failed', 'llm_unavailable', 'prompt_too_long', undefined]) {
    assert.ok(!wasDeclined({ status: 'error', code }), String(code))
  }
  // The same switch as the remix's Use Exact Prompt; Detail level stays for coming back.
  const saved = { raw: true, direct: false, autoImprove: { enabled: true, level: 'fill' }, programChoices: { a: { values: ['x'] } } }
  const next = withDirect(saved)
  assert.equal(next.direct, true)
  assert.equal(next.raw, undefined)
  assert.deepEqual(next.autoImprove, saved.autoImprove)
  assert.deepEqual(next.programChoices, saved.programChoices)
  assert.equal(effectiveWay({ raw: !!next.raw, direct: next.direct, llmUnconfigured: false }), 'direct')
  // Back in Fluent with the same prompt, the menu says the same, with no Try again.
  const n = fallbackNotice(DECLINED_CODE, 'Brand')
  assert.deepEqual(n, { head: 'Your chat model declined this prompt', body: 'It’s sent as written.', action: 'none' })
  assert.ok(isPrepareFailureCode(DECLINED_CODE))
  // In the user's words: no mechanics.
  for (const text of [DECLINED_NOTICE, n.head, n.body ?? '']) {
    assert.doesNotMatch(text, /prepar|writer|program|refus|Fluent|Brand/i)
  }
})

test('a declined prompt Direct can’t run stays put, and is told once', () => {
  const said: string[] = []
  let set = 0
  const run = (extra: Record<string, any>) => switchDeclinedToDirect({
    declined: true, direct: false, promptOptions: {}, set: () => { set++ }, notify: m => said.push(m), ...extra })
  assert.equal(run({ directCantRun: true }), false)
  assert.equal(run({ directCantRun: true, told: true }), false)
  assert.deepEqual([set, said], [0, [DECLINED_NOTICE]])
  assert.equal(run({}), true)
  assert.deepEqual([set, said.length], [1, 2])
})
