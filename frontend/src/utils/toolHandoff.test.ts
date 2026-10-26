import assert from 'node:assert/strict'
import test from 'node:test'
import { planToolHandoff } from './toolHandoff.ts'
import { convertMaskPixels } from './maskFormat.ts'

function tool(overrides: Record<string, unknown> = {}) {
  return {
    full_tool_id: 'test:tool',
    tool_id: 'tool',
    name: 'Tool',
    task_type: 'image-to-image',
    task_types: ['image-to-image'],
    provider_id: 'test',
    provider_name: 'Test',
    availability: 'available' as const,
    parameter_schema: {
      properties: {
        input_images: { type: 'array', 'x-max-items': 1 },
      },
    },
    output_schema: {},
    metadata: {},
    ...overrides,
  }
}

test('recognizes singular media slots used by provider schemas', () => {
  const plan = planToolHandoff({
    tool: tool({ parameter_schema: { properties: { input_image: { type: 'string' } } } }),
    mediaTypes: ['image'],
    count: 1,
  })
  assert.equal(plan.eligible, true)
  assert.equal(plan.taskType, 'image-to-image')
})

test('uses the video-to-image frame bridge consistently', () => {
  assert.equal(planToolHandoff({ tool: tool(), mediaTypes: ['video'], count: 1 }).eligible, true)
})

test('honors x-accept-media overrides', () => {
  const videoFilter = tool({
    task_type: 'filter',
    task_types: ['filter'],
    parameter_schema: {
      properties: {
        input_images: { type: 'array', 'x-max-items': 1, 'x-accept-media': ['video'] },
      },
    },
  })
  assert.equal(planToolHandoff({ tool: videoFilter, mediaTypes: ['image'], count: 1 }).eligible, false)
  assert.equal(planToolHandoff({ tool: videoFilter, mediaTypes: ['video'], count: 1 }).eligible, true)
})

test('rejects unavailable tools for every handoff surface', () => {
  const plan = planToolHandoff({
    tool: tool({ availability: 'disconnected' }),
    mediaTypes: ['image'],
    count: 1,
  })
  assert.equal(plan.eligible, false)
  assert.match(plan.reason || '', /disconnected/)
})

test('applies batch constraints to multi-item handoffs', () => {
  const maskTool = tool({
    task_type: 'inpaint-image',
    task_types: ['inpaint-image'],
    parameter_schema: {
      properties: {
        input_images: { type: 'array', 'x-max-items': 1 },
        mask: { type: 'string' },
      },
    },
  })
  assert.equal(planToolHandoff({ tool: maskTool, mediaTypes: ['image'], count: 2 }).eligible, false)
})

test('rejects mixed audio and visual selections instead of routing all items to one slot', () => {
  const lipSync = tool({
    task_type: 'lip-sync',
    task_types: ['lip-sync'],
    parameter_schema: {
      properties: {
        input_images: { type: 'array', 'x-max-items': 1 },
        input_audios: { type: 'array', 'x-max-items': 1 },
      },
    },
  })
  const plan = planToolHandoff({ tool: lipSync, mediaTypes: ['image', 'audio'], count: 2 })
  assert.equal(plan.eligible, false)
  assert.match(plan.reason || '', /separately/)
})

test('chooses the compatible facet of a multi-task tool', () => {
  const multiTask = tool({
    task_type: 'image-to-image',
    task_types: ['image-to-image', 'video-to-video'],
    parameter_schema: { properties: { input_videos: { type: 'array', 'x-max-items': 1 } } },
  })
  const plan = planToolHandoff({ tool: multiTask, mediaTypes: ['video'], count: 1 })
  assert.equal(plan.eligible, true)
  assert.equal(plan.taskType, 'video-to-video')
})

test('keeps grids prohibited at the shared boundary', () => {
  assert.equal(planToolHandoff({ tool: tool(), mediaTypes: ['grid'], count: 1 }).eligible, false)
})

test('converts hopped masks between provider mask formats', () => {
  const whiteBlack = new Uint8ClampedArray([
    255, 255, 255, 255, // inpaint
    0, 0, 0, 255,       // preserve
  ])

  assert.deepEqual(
    [...convertMaskPixels(whiteBlack, 'white-black', 'alpha')],
    [255, 255, 255, 0, 0, 0, 0, 255],
  )
  assert.deepEqual(
    [...convertMaskPixels(whiteBlack, 'white-black', 'black-white')],
    [0, 0, 0, 255, 255, 255, 255, 255],
  )

  const alpha = new Uint8ClampedArray([
    255, 255, 255, 0, // inpaint
    0, 0, 0, 255,     // preserve
  ])
  assert.deepEqual(
    [...convertMaskPixels(alpha, 'alpha', 'white-black')],
    [...whiteBlack],
  )
})

// A catalog summary carries the media parameters' structural keys instead of
// the full schema (backend summarize_provider_tool). Every send-to decision
// must come out the same from either.
function summaryOf(full: ReturnType<typeof tool>) {
  const keep = ['type', 'minItems', 'maxItems', 'x-min-items', 'x-max-items', 'x-control', 'x-accept-media']
  const media = new Set(['input_images', 'input_image', 'start_image', 'source_image', 'image', 'input_videos', 'input_video', 'input_audios', 'input_audio', 'mask'])
  const { parameter_schema, output_schema, ...rest } = full as any
  const properties = parameter_schema?.properties
  if (!properties) return { ...rest, parameter_outline: {} }
  const outline: Record<string, any> = {}
  for (const [name, schema] of Object.entries<any>(properties)) {
    if (media.has(name) || 'x-accept-media' in schema) {
      outline[name] = Object.fromEntries(Object.entries(schema).filter(([key]) => keep.includes(key)))
    }
  }
  return { ...rest, parameter_outline: { properties: outline } }
}

test('a catalog summary decides send-to eligibility exactly like the full tool', () => {
  const tools = [
    tool(),
    tool({ parameter_schema: { properties: { prompt: { type: 'string', default: 'x' }, input_images: { type: 'array', minItems: 2, maxItems: 3 } } } }),
    tool({ task_types: ['filter'], task_type: 'filter', parameter_schema: { properties: { input_images: { type: 'array', 'x-accept-media': ['video'] }, strength: { type: 'number' } } } }),
    tool({ task_types: ['image-to-video'], task_type: 'image-to-video', parameter_schema: { properties: { start_image: { type: 'string' }, duration: { type: 'number', default: 5 } } } }),
    tool({ task_types: ['inpaint-image'], task_type: 'inpaint-image', parameter_schema: { properties: { input_images: { type: 'array' }, mask: { type: 'string', 'x-mask-format': 'alpha' } } } }),
    tool({ task_types: ['text-to-audio'], task_type: 'text-to-audio', parameter_schema: { properties: { prompt: { type: 'string' } } } }),
    tool({ task_types: ['text-to-audio'], task_type: 'text-to-audio', parameter_schema: { properties: { input_audios: { type: 'array', 'x-max-items': 1 } } } }),
    tool({ task_types: ['video-to-video'], task_type: 'video-to-video', parameter_schema: { properties: { input_images: { type: 'array', 'x-control': 'video_frame_picker' } } } }),
    tool({ parameter_schema: {} }),
  ]
  const selections: Array<[string[], number]> = [
    [['image'], 1], [['image'], 2], [['image'], 4], [['video'], 1], [['video'], 3],
    [['audio'], 1], [['set'], 1], [['image', 'video'], 2],
  ]
  let ineligible = 0
  for (const full of tools) {
    const summary = summaryOf(full)
    for (const [mediaTypes, count] of selections) {
      const fromFull = planToolHandoff({ tool: full, mediaTypes: mediaTypes as any, count })
      if (!fromFull.eligible) ineligible++
      assert.deepEqual(
        planToolHandoff({ tool: summary as any, mediaTypes: mediaTypes as any, count }),
        fromFull,
        `${JSON.stringify(full.parameter_schema)} ${mediaTypes} x${count}`,
      )
    }
  }
  // The cases exercise both outcomes.
  assert.ok(ineligible > 0 && ineligible < tools.length * selections.length)
})
