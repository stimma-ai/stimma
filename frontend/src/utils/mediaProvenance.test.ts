import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildProvenance,
  fileFacts,
  formatLoraWeight,
  formatParamLabel,
  formatParamValue,
  formatSourceRole,
  looksLikeAbsolutePath,
  paramFacts,
  parseGenerationMetadata,
  publicStepCount,
  stepParameters,
  toPublicProvenance,
} from './mediaProvenance.ts'

const tools = [{ full_tool_id: 'acme:flux-pro', name: 'Flux 2 Pro' }]

function generated(overrides: Record<string, unknown> = {}) {
  return {
    id: 42,
    width: 1024,
    height: 768,
    file_path: '/home/someone/library/out.png',
    file_format: 'png',
    file_size: 2048,
    generation_metadata: JSON.stringify({
      version: 3,
      source: 'stimma',
      task_type: 'image-to-image',
      tool_id: 'acme:flux-pro',
      model: 'flux-2-pro',
      prompt: 'a lighthouse at dusk',
      negative_prompt: 'blurry',
      prompt_metadata: { original_prompt: 'a {lighthouse|windmill} at dusk' },
      seed: 1234,
      parameters: {
        width: 1024,
        height: 768,
        cfg: 3.5,
        guidance: 2.333333,
        steps: 28,
        generation_time: 4.2,
        mask_path: '/home/someone/masks/m.png',
        input_media_ids: [7],
        loras: [{ lora: 'styles/film-grain.safetensors', weight: 0.8 }],
        post_processing_chain: [{ kind: 'filter', filter_id: 'sepia' }, { kind: 'tool', tool_id: 'acme:upscale-x' }],
      },
      source_inputs: [
        { media_id: 7, file_path: '/home/someone/library/in.png', role: 'reference', preprocessor: 'canny', preprocessor_params: { low: 100, high: 200 } },
        { file_path: 'C:\\Users\\someone\\pic.png', role: 'start_image' },
      ],
      generated_at: '2026-10-01T12:00:00',
      lineage_trace: [
        { media_id: 1, task_type: 'text-to-image', tool_id: 'acme:flux-pro', prompt: 'oldest', generated_at: '2026-09-01T00:00:00Z' },
        { media_id: 7, task_type: 'image-to-image', tool_id: 'builtin:stimma:image-editor', parameters: { stack: [{ class: 'crop', label: 'Crop', exec: { kind: 'crop' } }] }, generated_at: '2026-09-15T00:00:00Z' },
      ],
      flow_id: 9,
    }),
    ...overrides,
  }
}

test('parses string and object metadata, rejects garbage', () => {
  assert.deepEqual(parseGenerationMetadata('{"a":1}'), { a: 1 })
  assert.deepEqual(parseGenerationMetadata({ a: 1 }), { a: 1 })
  assert.equal(parseGenerationMetadata('{not json'), null)
  assert.equal(parseGenerationMetadata('[1,2]'), null)
  assert.equal(parseGenerationMetadata(null), null)
})

test('seed is lifted into parameters without overriding a recorded one', () => {
  assert.equal(stepParameters({ seed: 5 }).seed, 5)
  assert.equal(stepParameters({ seed: 5, parameters: { seed: 9 } }).seed, 9)
  assert.equal(stepParameters({ seed: null }).seed, undefined)
})

test('steps are newest first: own step, then lineage_trace reversed', () => {
  const p = buildProvenance(generated(), { tools })
  assert.deepEqual(p.steps.map(s => s.mediaId), [42, 7, 1])
  assert.equal(p.steps[0].tool, 'Flux 2 Pro')
  assert.equal(p.steps[1].tool, 'Image Editor')
  assert.deepEqual(p.steps[1].edits, ['Crop'])
  assert.equal(p.steps[2].prompt, 'oldest')
  assert.equal(p.steps[0].date, '2026-10-01T12:00:00.000Z')
})

test('own step: facts, loras, inputs, original prompt, chain and settings', () => {
  const p = buildProvenance(generated(), { tools, filterLabel: id => id.toUpperCase() })
  const step = p.steps[0]
  const facts = Object.fromEntries(step.facts.map(f => [f.label, f.value]))
  assert.equal(facts.Model, 'flux-2-pro')
  assert.equal(facts.Seed, '1234')
  assert.equal(facts.CFG, '3.50')
  assert.equal(facts.Guidance, '2.33')
  assert.equal(facts['Generation time'], '4.2s')
  assert.equal(facts.Size, undefined, 'own size repeats the file resolution')
  assert.equal(facts['Input media ids'], undefined, 'media references are inputs, not facts')
  assert.deepEqual(step.loras, [{ name: 'film-grain', weight: 0.8 }])
  assert.equal(step.inputs[0].roleLabel, 'Reference')
  assert.equal(step.inputs[0].preprocessorLabel, 'Canny (100-200)')
  assert.equal(step.inputs[1].roleLabel, 'Start frame')
  assert.equal(step.originalPrompt, 'a {lighthouse|windmill} at dusk')
  assert.deepEqual(step.postProcessing, ['SEPIA', 'Upscale X'])
  assert.equal(step.settings?.toolId, 'acme:flux-pro')
  assert.equal(step.settings?.parameters.seed, 1234)
  assert.deepEqual(p.flow, null, 'flow origin only for source=flow')
})

test('flow origin is read from flow-made media', () => {
  const p = buildProvenance({ id: 1, generation_metadata: { source: 'flow', flow_id: 3, phase_path: ['Look', 'Hero'] } })
  assert.deepEqual(p.flow, { flowId: 3, equationKey: null, phasePath: ['Look', 'Hero'] })
})

test('regression: imported LoRAs without a numeric weight never crash', () => {
  const media = {
    id: 5,
    raw_metadata: 'Steps: 20, Sampler: Euler',
    generation_metadata: {
      source: 'external',
      prompt: 'a cat',
      loras: [{ name: 'detail' }, { name: 'style', weight: '0.6' }, { name: 'odd', weight: null }],
    },
  }
  const p = buildProvenance(media)
  assert.equal(p.imported, true)
  assert.equal(p.steps[0].tool, 'Imported')
  assert.deepEqual(p.steps[0].loras, [
    { name: 'detail', weight: null },
    { name: 'style', weight: 0.6 },
    { name: 'odd', weight: null },
  ])
  assert.equal(p.steps[0].rawMetadata, 'Steps: 20, Sampler: Euler')
  assert.equal(formatLoraWeight(undefined), '')
  assert.equal(formatLoraWeight('abc'), '')
  assert.equal(formatLoraWeight(1), '1.0')
  assert.equal(formatLoraWeight(0.75), '0.75')
})

test('plain files read as a single imported step', () => {
  const p = buildProvenance({ id: 3, extracted_prompt: 'from exif', width: 10, height: 10 })
  assert.equal(p.raw, true)
  assert.equal(p.steps.length, 1)
  assert.equal(p.steps[0].prompt, 'from exif')
  assert.deepEqual(p.steps[0].facts, [])
})

test('labels are sentence case; values formatted once', () => {
  assert.equal(formatParamLabel('aspect_ratio'), 'Aspect ratio')
  assert.equal(formatParamLabel('clipSkip'), 'Clip skip')
  assert.equal(formatParamLabel('cfg'), 'CFG')
  assert.equal(formatParamValue('padding_percent', 0.25), '25%')
  assert.equal(formatParamValue('scale', 2), '2\u00d7')
  assert.equal(formatParamValue('method', 'rembg_ai'), 'AI (rembg)')
  assert.equal(formatParamValue('enabled', true), 'Yes')
  assert.equal(formatSourceRole('end_image'), 'End frame')
  assert.equal(formatSourceRole(null), 'Input')
  assert.equal(formatSourceRole('style_reference'), 'Style reference')
  const facts = paramFacts({ input_width: 512, input_height: 512, output_width: 1024, output_height: 1024 })
  assert.deepEqual(facts.map(f => f.label), ['Input size', 'Output size'])
})

test('file facts name sets and use the shared duration format', () => {
  const facts = Object.fromEntries(fileFacts({
    file_path: 'C:\\lib\\board.stimmaset.json', file_format: 'stimmaset.json', duration: 75, file_size: 3 * 1024 * 1024,
  }).map(f => [f.label, f.value]))
  assert.equal(facts.Name, 'board.stimmaset.json')
  assert.equal(facts.Format, 'Set')
  assert.equal(facts.Duration, '1:15')
  assert.equal(facts.Size, '3.0 MB')
})

test('public provenance matches the v2 request contract', () => {
  const pub = toPublicProvenance(buildProvenance(generated(), { tools }))
  assert.ok(pub)
  assert.equal(pub.version, 2)
  assert.equal(publicStepCount(pub), 3)
  const [own] = pub.steps
  assert.equal(own.tool, 'Flux 2 Pro')
  assert.equal(own.model, 'flux-2-pro')
  assert.equal(own.prompt, 'a lighthouse at dusk')
  assert.equal(own.negativePrompt, 'blurry')
  assert.equal(own.originalPrompt, 'a {lighthouse|windmill} at dusk')
  assert.deepEqual(own.loras, [{ name: 'film-grain', weight: 0.8 }])
  // Only inputs that resolve to library media are referenced; no paths.
  assert.deepEqual(own.inputs, [{ role: 'Reference', ref: { mediaId: 7, hash: null } }])
  assert.ok(own.facts?.some(f => f.label === 'Seed' && f.value === '1234'))
  assert.ok(own.facts?.some(f => f.label === 'Post-processing'))
  assert.ok(!own.facts?.some(f => f.label === 'Model'), 'model is its own field')
  assert.deepEqual(pub.steps[1].edits, ['Crop'])
  const allowed = new Set(['tool', 'model', 'date', 'prompt', 'negativePrompt', 'originalPrompt', 'facts', 'loras', 'inputs', 'edits'])
  for (const step of pub.steps) {
    for (const key of Object.keys(step)) assert.ok(allowed.has(key), `unexpected field ${key}`)
  }
})

test('public provenance never carries absolute paths', () => {
  const media = generated()
  const meta = JSON.parse(media.generation_metadata)
  meta.parameters.output_dir = 'outputs'
  meta.parameters.note = '/Users/someone/secret/thing.png'
  meta.parameters.win = 'C:\\Users\\someone\\x.png'
  meta.parameters.share = '\\\\server\\share\\x.png'
  meta.parameters.uri = 'file:///home/someone/x.png'
  meta.lineage_trace[0].prompt = 'see /home/someone/refs/a.png'
  const pub = toPublicProvenance(buildProvenance({ ...media, generation_metadata: meta }, { tools }))
  const text = JSON.stringify(pub)
  for (const needle of ['/home/', '/Users/', 'C:\\\\', '\\\\\\\\server', 'file://', 'someone', 'mask_path', 'outputs']) {
    assert.ok(!text.includes(needle), `leaked ${needle}: ${text}`)
  }
  assert.equal(pub?.steps[2].prompt, undefined, 'a prompt holding a path is dropped')
  assert.ok(looksLikeAbsolutePath('/home/x'))
  assert.ok(!looksLikeAbsolutePath('16:9 aspect, 1/2 scale'))
})

test('nothing meaningful publishes null', () => {
  assert.equal(toPublicProvenance(buildProvenance({ id: 1, width: 5, height: 5 })), null)
  assert.equal(toPublicProvenance(buildProvenance(null)), null)
  assert.equal(publicStepCount(null), 0)
  const withPrompt = toPublicProvenance(buildProvenance({ id: 1, extracted_prompt: 'hello' }))
  assert.equal(withPrompt?.steps[0].tool, 'Imported')
})

test('public strings are capped', () => {
  const long = 'x'.repeat(9000)
  const pub = toPublicProvenance(buildProvenance({ id: 1, generation_metadata: { tool_id: 'a:b', prompt: long, parameters: { note: 'y'.repeat(500) } } }))
  assert.equal(pub?.steps[0].prompt?.length, 8000)
  assert.equal(pub?.steps[0].facts?.[0].value.length, 200)
})

test('editor and agent-edit steps offer no "use these settings"', () => {
  const p = buildProvenance(generated(), { tools })
  assert.ok(p.steps[0].settings)
  assert.equal(p.steps[1].settings, null)
  const agent = buildProvenance({ id: 2, generation_metadata: { task_type: 'agent_edit', tool_id: 'a:b' } })
  assert.equal(agent.steps[0].tool, 'Edited by agent')
  assert.equal(agent.steps[0].settings, null)
})
