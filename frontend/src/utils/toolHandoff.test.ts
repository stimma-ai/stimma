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
