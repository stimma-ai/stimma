/**
 * A published sidecar (v2 or v3, as served at /api/s/:code/history) → the
 * provenance view. Defensive: the sidecar arrives over the network, so every
 * field is checked and anything unexpected is dropped rather than rendered.
 *
 * Thumbnail references stay as the sidecar's opaque keys (`t0`…); the public
 * host looks them up in `sidecar.thumbnails`.
 */

import { factKeyFromLabel, factRow, ICON_KEY, loraRow, normalizeDate } from './format.ts'
import type { ProvenanceView, ViewEditStep, ViewFact, ViewInput, ViewStep } from './types.ts'

const THUMB_KEY = /^t\d{1,4}$/

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function obj(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

function thumbKey(value: unknown): string | null {
  return typeof value === 'string' && THUMB_KEY.test(value) ? value : null
}

function facts(raw: unknown): ViewFact[] {
  const out: ViewFact[] = []
  for (const item of list(raw)) {
    const fact = obj(item)
    const label = text(fact?.label)
    const value = fact?.value == null ? null : String(fact.value).trim() || null
    if (!label || !value) continue
    out.push(factRow(factKeyFromLabel(label), label, value, value.length > 16))
  }
  return out
}

function step(raw: Record<string, unknown>, index: number): ViewStep | null {
  const tool = text(raw.tool)
  if (!tool) return null
  const rows: ViewFact[] = []
  const model = text(raw.model)
  // The model row only when it says more than the step header (the app's rule).
  if (model && model.toLowerCase() !== tool.toLowerCase()) rows.push(factRow('model', 'Model', model, true))
  rows.push(...facts(raw.facts))
  list(raw.loras).forEach((item, i) => {
    const lora = obj(item)
    const name = text(lora?.name)
    if (!name) return
    const weight = typeof lora?.weight === 'number' && Number.isFinite(lora.weight) ? lora.weight : null
    rows.push(loraRow(`lora-${i}`, name, weight))
  })

  const inputs: ViewInput[] = []
  list(raw.inputs).forEach((item, i) => {
    const input = obj(item)
    if (!input) return
    inputs.push({
      key: `input-${i}`,
      role: text(input.role) || 'Input',
      preprocessor: text(input.preprocessor),
      badges: list(input.badges).map(text).filter((b): b is string => !!b).slice(0, 6),
      thumb: thumbKey(input.thumb),
      preview: thumbKey(input.preview),
      deleted: false,
    })
  })

  let editSteps: ViewEditStep[] = []
  if (Array.isArray(raw.editSteps)) {
    raw.editSteps.forEach((item, i) => {
      const edit = obj(item)
      const name = text(edit?.label)
      if (name) editSteps.push({ key: `edit-${i}`, name, detail: '', note: '', thumb: thumbKey(edit?.thumb) })
    })
  } else {
    // v2: a plain list of edit names.
    editSteps = list(raw.edits)
      .map(text)
      .filter((name): name is string => !!name)
      .map((name, i) => ({ key: `edit-${i}`, name, detail: '', note: '', thumb: null }))
  }

  const icon = typeof raw.icon === 'string' && ICON_KEY.test(raw.icon) ? raw.icon : null
  return {
    key: `step-${index}`,
    tool,
    icon,
    date: normalizeDate(raw.date),
    imported: false,
    prompt: text(raw.prompt),
    negativePrompt: text(raw.negativePrompt),
    originalPrompt: text(raw.originalPrompt),
    facts: rows,
    inputs,
    editSteps,
    rawMetadata: null,
  }
}

/** The view for a published sidecar; an empty view when it can't be read. */
export function viewFromPublished(sidecar: unknown): ProvenanceView {
  const root = obj(sidecar)
  if (!root) return { steps: [], file: [] }
  const steps: ViewStep[] = []
  list(root.steps).forEach((item, i) => {
    const raw = obj(item)
    const built = raw ? step(raw, i) : null
    if (built) steps.push(built)
  })
  return { steps, file: facts(root.file) }
}

/** The sidecar's thumbnail map, keeping only data-URI images. */
export function publishedThumbnails(sidecar: unknown): Record<string, string> {
  const map = obj(obj(sidecar)?.thumbnails)
  const out: Record<string, string> = {}
  if (!map) return out
  for (const [key, value] of Object.entries(map)) {
    if (THUMB_KEY.test(key) && typeof value === 'string' && /^data:image\/(webp|png|jpeg|gif);base64,/.test(value)) {
      out[key] = value
    }
  }
  return out
}
