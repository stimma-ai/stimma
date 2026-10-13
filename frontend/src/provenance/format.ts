/**
 * Display formatting shared by the app's provenance model
 * (`utils/mediaProvenance`) and the published-sidecar adapter, so a fact row
 * reads the same whether it came from local metadata or a share link.
 *
 * Pure: no Vue, no app state. Runs under `node --test`.
 */

import { parseServerTime } from '../utils/timeFormat.js'
import type { ViewFact } from './types.ts'

/** Facts whose values are names or words, not numbers: plain text, not mono. */
const PROSE_FACTS = new Set(['model', 'channels', 'method', 'filter_id', 'filter', 'post_processing'])

/** A label as a fact key ("Post-processing" → "post_processing"). */
export function factKeyFromLabel(label: string): string {
  return String(label).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
}

/** One fact row in the KeyValueList shape. `long` facts truncate. */
export function factRow(key: string, label: string, value: string, long = false): ViewFact {
  return { key, label, value, mono: !PROSE_FACTS.has(key), truncate: long }
}

/** 0.8 → "0.8", 1 → "1.0", 0.75 → "0.75"; missing → "" (never throws). */
export function formatLoraWeight(weight: unknown): string {
  const n = typeof weight === 'number' ? weight : typeof weight === 'string' && weight.trim() !== '' ? Number(weight) : NaN
  if (!Number.isFinite(n)) return ''
  return n.toFixed(2).replace(/(\.\d)0$/, '$1')
}

/** A LoRA as a fact row; the weight reads accent when it isn't the 1.0 default. */
export function loraRow(key: string, name: string, weight: number | null): ViewFact {
  const w = formatLoraWeight(weight)
  return {
    key,
    label: 'LoRA',
    value: w ? `${name} · ${w}` : name,
    mono: true,
    truncate: true,
    valueClass: weight != null && weight !== 1 ? 'text-accent-hi' : undefined,
  }
}

/** Server timestamp (naive UTC or zoned) → ISO-8601 UTC, or null. */
export function normalizeDate(value: unknown): string | null {
  if (typeof value !== 'string' || !value) return null
  const ms = parseServerTime(value)
  return ms ? new Date(ms).toISOString() : null
}

/** Exact local timestamp for tooltips and fact rows. */
export function formatDateTime(value: string | null | undefined): string {
  const iso = normalizeDate(value ?? null)
  if (!iso) return ''
  return new Date(iso).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

/** Task-type keys as published (`icon`): lowercase, digits, dashes. */
export const ICON_KEY = /^[a-z0-9-]{1,40}$/

/** A step's task type as an icon key ("acme:image-to-image" → "image-to-image"), or null. */
export function iconKey(taskType: string | null | undefined): string | null {
  if (!taskType) return null
  const key = String(taskType).replace(/^.*:/, '').toLowerCase()
  return ICON_KEY.test(key) ? key : null
}
