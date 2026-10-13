import assert from 'node:assert/strict'
import test from 'node:test'

import { buildProvenance, toPublicProvenance, type PublicProvenance } from '../utils/mediaProvenance.ts'
import { viewFromProvenance } from './fromProvenance.ts'
import { publishedThumbnails, viewFromPublished } from './fromPublished.ts'

const tools = [{ full_tool_id: 'acme:klein', name: 'Flux.2 Klein 9B' }, { full_tool_id: 'acme:turbo', name: 'Z-Image Turbo' }]

const media = {
  id: 23,
  width: 1216,
  height: 832,
  file_path: '/home/someone/library/gen_1.webp',
  file_format: 'webp',
  file_size: 312_000,
  created_date: '2026-10-12T10:00:00',
  generation_metadata: {
    task_type: 'image-to-image',
    tool_id: 'acme:klein',
    model: 'flux2-klein-9b',
    prompt: 'same harbor, blue hour',
    seed: 88,
    parameters: { generation_time: 6.68, loras: [{ lora: 'film-grain.safetensors', weight: 0.8 }, { lora: 'clean', weight: 1 }] },
    source_inputs: [{ media_id: 22, role: 'reference', preprocessor: 'depth', crop: { x: 0 } }],
    generated_at: '2026-10-12T10:00:00Z',
    lineage_trace: [
      { media_id: 22, task_type: 'text-to-image', tool_id: 'acme:turbo', model: 'z-image-turbo', prompt: 'a quiet harbor', parameters: { width: 1216, height: 832, seed: 4127 }, generated_at: '2026-10-12T09:00:00Z' },
    ],
  },
}

/** What the desktop backend does to a request: refs → opaque thumbnail keys. */
function publish(request: PublicProvenance) {
  const thumbnails: Record<string, string> = {}
  const keyFor = (ref: unknown) => {
    if (!ref) return undefined
    const key = `t${Object.keys(thumbnails).length}`
    thumbnails[key] = 'data:image/webp;base64,AAAA'
    return key
  }
  const steps = request.steps.map(step => ({
    ...step,
    inputs: step.inputs?.map(({ ref, previewRef, ...rest }) => ({ ...rest, thumb: keyFor(ref), preview: keyFor(previewRef) })),
    editSteps: step.editSteps?.map(({ ref, ...rest }) => ({ ...rest, thumb: keyFor(ref) })),
  }))
  return JSON.parse(JSON.stringify({ version: 3, file: request.file, steps, thumbnails }))
}

test('the app and the share page render the same rows for the same history', () => {
  const provenance = buildProvenance(media, { tools })
  const app = viewFromProvenance(provenance)
  const sidecar = publish(toPublicProvenance(provenance)!)
  const pub = viewFromPublished(sidecar)

  assert.equal(pub.steps.length, app.steps.length)
  pub.steps.forEach((step, i) => {
    const mine = app.steps[i]
    assert.equal(step.tool, mine.tool)
    assert.equal(step.icon, mine.icon)
    assert.equal(step.date, mine.date)
    assert.equal(step.prompt, mine.prompt)
    const strip = (rows: typeof step.facts) => rows.map(({ label, value, mono, truncate, valueClass }) => ({ label, value, mono, truncate, valueClass }))
    assert.deepEqual(strip(step.facts), strip(mine.facts))
    assert.deepEqual(step.inputs.map(x => [x.role, x.preprocessor, x.badges]), mine.inputs.map(x => [x.role, x.preprocessor, x.badges]))
  })
  // LoRA weight off the default reads accent in both.
  assert.equal(pub.steps[0].facts.find(f => f.value.startsWith('film-grain'))?.valueClass, 'text-accent-hi')
  // File facts: the same rows minus the name and the date.
  assert.deepEqual(pub.file.map(f => f.label), ['Format', 'Size', 'Resolution'])
  assert.deepEqual(pub.file, app.file.filter(f => ['format', 'size', 'resolution'].includes(f.key)))
  assert.equal(pub.steps[0].inputs[0].thumb, 't0')
})

test('v2 sidecars render (edit names, no icons or badges)', () => {
  const view = viewFromPublished({
    version: 2,
    steps: [{ tool: 'Image Editor', edits: ['Crop', 'Exposure'], inputs: [{ role: 'Reference', thumb: 't0' }] }],
    thumbnails: { t0: 'data:image/webp;base64,AAAA' },
  })
  assert.equal(view.steps[0].icon, null)
  assert.deepEqual(view.steps[0].editSteps.map(e => e.name), ['Crop', 'Exposure'])
  assert.deepEqual(view.steps[0].inputs[0].badges, [])
  assert.deepEqual(view.file, [])
})

test('garbage in a sidecar is dropped, not rendered', () => {
  assert.deepEqual(viewFromPublished(null), { steps: [], file: [] })
  assert.deepEqual(viewFromPublished('nope'), { steps: [], file: [] })
  const view = viewFromPublished({
    version: 3,
    steps: [
      { tool: '' },
      {
        tool: 'X',
        icon: '<svg onload=alert(1)>',
        facts: [{ label: 'Seed' }, { label: 'Steps', value: 20 }, 'junk'],
        inputs: [{ thumb: '../../etc/passwd', preview: 'javascript:alert(1)' }],
        editSteps: [{ label: 'Crop', thumb: 'https://example.com/x.png' }],
      },
    ],
  })
  assert.equal(view.steps.length, 1)
  const [step] = view.steps
  assert.equal(step.icon, null)
  assert.deepEqual(step.facts.map(f => [f.label, f.value]), [['Steps', '20']])
  assert.equal(step.inputs[0].role, 'Input')
  assert.equal(step.inputs[0].thumb, null)
  assert.equal(step.inputs[0].preview, null)
  assert.equal(step.editSteps[0].thumb, null)
})

test('only data-URI images are used as thumbnails', () => {
  assert.deepEqual(publishedThumbnails({
    thumbnails: {
      t0: 'data:image/webp;base64,AAAA',
      t1: 'https://tracker.example/pixel.gif',
      t2: 'data:text/html;base64,PHNjcmlwdD4=',
      evil: 'data:image/png;base64,AAAA',
    },
  }), { t0: 'data:image/webp;base64,AAAA' })
})
