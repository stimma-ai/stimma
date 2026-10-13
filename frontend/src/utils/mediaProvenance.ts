/**
 * How a piece of media was made, read once.
 *
 * Every surface that shows an asset's details (the slideshow Info panel, the
 * media details modal, the lineage tree's node card, job and flow-step
 * details) and the public "how it was made" sidecar used to parse
 * `generation_metadata` on its own, each with a slightly different idea of
 * which parameters to hide, how to label them and how to round them. This is
 * the one reading:
 *
 *   parseGenerationMetadata(raw)    the stored JSON (string or object) → object
 *   buildProvenance(media, opts)    → MediaProvenance, steps newest first
 *   toPublicProvenance(provenance)  → the share request's `provenance` (v2)
 *
 * Pure and framework-free so it runs under `node --test`. Anything that needs
 * app state (the tools cache for display names, the filter catalogue) comes in
 * through `ProvenanceOptions`; `composables/useMediaProvenance` wires those for
 * components.
 */

import { toolDisplayName, type ToolLikeRecord } from './toolDisplay.ts'
import { formatDuration } from './mediaTypes.ts'
import { parseServerTime } from './timeFormat.js'
import { summarizeStack } from '../imageEditor/stack/stackSummary.ts'
import type {
  GenerationMetadata,
  GenerationSourceInput,
  LineageTraceEntry,
} from '../types/generationMetadata.ts'

// ---------------------------------------------------------------------------
// Model
// ---------------------------------------------------------------------------

/** One read-only fact row (KeyValueList shape). */
export interface ProvenanceFact {
  key: string
  label: string
  value: string
  /** Long or free-text value: single-line ellipsis in fact lists. */
  long?: boolean
}

export interface ProvenanceLora {
  name: string
  /** null when the producer did not record one (imports often don't). */
  weight: number | null
}

export interface ProvenanceInput {
  /** Raw role id (input_image, start_image…), null when unrecorded. */
  role: string | null
  /** Sentence-case role label for display ("Start frame"). */
  roleLabel: string
  mediaId: number | null
  hash: string | null
  /** Local file path. Display/remix only; never published. */
  filePath: string | null
  preprocessor: string | null
  preprocessorParams: unknown
  /** "Canny (100-200)", null when no preprocessor ran. */
  preprocessorLabel: string | null
  /** Other prep applied to the input: Painted, Extended, Flip H, Cropped. */
  marks: string[]
  /** Source was purged; only a tombstone remains. */
  deleted: boolean
}

/** The settings a step ran with, in the shape the tool handoff consumes. */
export interface ProvenanceSettings {
  toolId: string
  mediaId: number | null
  prompt: string
  negativePrompt: string
  generator: string | null
  model: string | null
  parameters: Record<string, unknown>
  sourceInputs: GenerationSourceInput[]
}

export interface ProvenanceStep {
  key: string
  /** The media this step produced (the item itself for step 0). */
  mediaId: number | null
  toolId: string | null
  taskType: string | null
  /** Display name of whatever made this step. Always set. */
  tool: string
  model: string | null
  /** Normalised ISO-8601 UTC timestamp, or null. */
  date: string | null
  /** Imported from outside Stimma (no tool ran here). */
  imported: boolean
  prompt: string | null
  negativePrompt: string | null
  /** Pre-enhancement prompt when it differs from the rendered one. */
  originalPrompt: string | null
  /** Parameter facts (Model row first when it says more than the tool name). */
  facts: ProvenanceFact[]
  loras: ProvenanceLora[]
  inputs: ProvenanceInput[]
  /** One label per image-editor edit, newest first. */
  edits: string[]
  /** The raw recorded edit stack, for EditStackSummary. */
  editStack: unknown
  /** Post-processing chain that ran after the tool, in order. */
  postProcessing: string[]
  /** External metadata blob carried by imports, for the raw-metadata view. */
  rawMetadata: string | null
  /** What "Use these settings" sends to the tool; null without a tool id. */
  settings: ProvenanceSettings | null
}

export interface ProvenanceFlowOrigin {
  flowId: number
  equationKey: string | null
  phasePath: string[]
}

export interface MediaProvenance {
  mediaId: number | null
  /** Newest first: the item's own step, then its ancestors. */
  steps: ProvenanceStep[]
  flow: ProvenanceFlowOrigin | null
  /** Media this was remixed from. */
  inspiredBy: number | null
  /** The item's own step is an import (A1111 metadata, a dropped file…). */
  imported: boolean
  /** No generation metadata at all: a plain file. */
  raw: boolean
  fileFacts: ProvenanceFact[]
}

export interface ProvenanceOptions {
  /** Tools cache for display names (`useProvidersApi().cachedTools`). */
  tools?: ToolLikeRecord[]
  /** Override the tool display name resolver entirely. */
  toolName?: (toolId: string) => string
  /** Filter catalogue labels (`utils/filterDefs` getFilterDisplayLabel). */
  filterLabel?: (filterId: string) => string
  /** Include file facts (name, format, size…). Default true. */
  fileFacts?: boolean
}

/** Any media-shaped record: browser items, media rows, lineage tree nodes. */
export interface MediaLike {
  id?: number | null
  media_id?: number | null
  generation_metadata?: unknown
  raw_metadata?: string | null
  extracted_prompt?: string | null
  indexed_date?: string | null
  created_date?: string | null
  file_path?: string | null
  file_format?: string | null
  file_size?: number | null
  width?: number | null
  height?: number | null
  duration?: number | null
  audio_sample_rate?: number | null
  audio_bit_depth?: number | null
  audio_channels?: number | null
  audio_bitrate?: number | null
  [key: string]: unknown
}

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

/** `generation_metadata` as stored (JSON string or object) → object, or null. */
export function parseGenerationMetadata(raw: unknown): GenerationMetadata | null {
  if (raw == null || raw === '') return null
  if (typeof raw === 'string') {
    try {
      const parsed = JSON.parse(raw)
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null
    } catch {
      return null
    }
  }
  return typeof raw === 'object' && !Array.isArray(raw) ? (raw as GenerationMetadata) : null
}

/**
 * A step's parameters with the seed lifted in. Older producers wrote `seed`
 * beside `parameters` rather than inside it.
 */
export function stepParameters(stepLike: { parameters?: unknown; seed?: unknown } | null | undefined): Record<string, unknown> {
  const params: Record<string, unknown> = {
    ...((stepLike?.parameters && typeof stepLike.parameters === 'object') ? stepLike.parameters as Record<string, unknown> : {}),
  }
  if (params.seed === undefined && stepLike?.seed !== undefined && stepLike?.seed !== null) {
    params.seed = stepLike.seed
  }
  return params
}

// ---------------------------------------------------------------------------
// Formatting (the one copy)
// ---------------------------------------------------------------------------

/** Parameters never shown as generic facts: shown elsewhere or meaningless. */
const EXCLUDED_PARAMS = new Set([
  'prompt', 'negative_prompt', 'selected_loras', 'loras',
  'width', 'height', 'input_width', 'input_height', 'output_width', 'output_height',
  'output_size', 'bbox',
  'checkpoint', // the step's model
  'stack', // the edit stack, summarised separately
  'post_processing_chain', // summarised separately
])

/** Label overrides; everything else is sentence-cased from the key. */
const PARAM_LABELS: Record<string, string> = {
  seed: 'Seed',
  cfg: 'CFG',
  fps: 'FPS',
  generation_time: 'Generation time',
  frame_count: 'Frames',
  target_megapixels: 'Target MP',
  padding_percent: 'Padding',
  item_count: 'Items',
  cell_count: 'Cells',
  checkpoint: 'Model',
  filter_id: 'Filter',
  negative_prompt: 'Negative prompt',
  n: 'Count',
}

const METHOD_LABELS: Record<string, string> = {
  color_based: 'Color-based',
  rembg_ai: 'AI (rembg)',
  ai_upscale: 'AI upscale',
  lanczos: 'Lanczos',
  u2net: 'U²Net',
  u2net_human_seg: 'U²Net portrait',
  'isnet-anime': 'ISNet anime',
}

const PREPROCESSOR_LABELS: Record<string, string> = {
  canny: 'Canny',
  depth: 'Depth',
  lineart: 'Line art',
  pose: 'Pose',
  pose_hands: 'Pose + hands',
}

const ROLE_LABELS: Record<string, string> = {
  input_image: 'Input image',
  source_image: 'Source image',
  start_image: 'Start frame',
  end_image: 'End frame',
  reference: 'Reference',
  input_video: 'Input video',
  image: 'Image',
  style: 'Style',
  mask: 'Mask',
  depth: 'Depth',
  pose: 'Pose',
  item: 'Item',
  cell: 'Cell',
}

const FILE_FORMAT_LABELS: Record<string, string> = {
  'stimmaset.json': 'Set',
  'stimmagrid.json': 'Grid',
  'stimmasprite.json': 'Sprite',
  stimmapackage: 'Package',
  stimmalayout: 'Layout',
  md: 'Markdown',
  txt: 'Text',
}

function sentenceCase(text: string): string {
  const words = text.trim().split(/\s+/).filter(Boolean)
  if (!words.length) return ''
  return words
    .map((word, i) => (i === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word))
    .join(' ')
}

/** snake_case / camelCase / kebab-case key → sentence-case label. */
export function formatParamLabel(key: string): string {
  if (PARAM_LABELS[key]) return PARAM_LABELS[key]
  const spaced = String(key)
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .toLowerCase()
  return sentenceCase(spaced) || String(key)
}

/** Non-integers to two places; integers as-is. */
export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return String(value)
  return Number.isInteger(value) ? String(value) : value.toFixed(2)
}

/**
 * A parameter value for display. Objects become pretty JSON (job details show
 * whole payloads); provenance facts skip objects before they get here.
 */
export function formatParamValue(
  key: string,
  value: unknown,
  filterLabel: (id: string) => string = humanizeId,
): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (key === 'filter_id' || key === 'filter') return filterLabel(String(value))
  if (typeof value === 'number') {
    if (key === 'generation_time') return `${parseFloat(value.toFixed(2))}s`
    if (key === 'resolution') return `${value}p`
    if (key === 'padding_percent' || key === 'confidence') return `${(value * 100).toFixed(0)}%`
    if (key === 'scale') return `${formatNumber(value)}×`
    return formatNumber(value)
  }
  if (typeof value === 'string') {
    if (key === 'method') return METHOD_LABELS[value] || value
    if (key === 'optimization') return value.charAt(0).toUpperCase() + value.slice(1)
    if (key === 'color_correction') return value.toUpperCase()
    if (key === 'resolution' && /^\d+$/.test(value)) return `${value}p`
    return value
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/** Keys that reference library media; those belong in the input thumbnails. */
export function isMediaReferenceParam(key: string): boolean {
  const normalized = key.replace(/([a-z])([A-Z])/g, '$1_$2').toLowerCase()
  return /(^|_)media_ids?$/.test(normalized)
}

function dims(w: unknown, h: unknown): string | null {
  return w && h ? `${w}×${h}` : null
}

/** A step's parameters as display facts (sizes first, then the rest in order). */
export function paramFacts(
  params: Record<string, unknown> | null | undefined,
  opts: { filterLabel?: (id: string) => string } = {},
): ProvenanceFact[] {
  if (!params) return []
  const facts: ProvenanceFact[] = []
  const size = !params.input_width ? dims(params.width, params.height) : null
  if (size) facts.push({ key: 'size', label: 'Size', value: size })
  const inputSize = dims(params.input_width, params.input_height)
  if (inputSize) facts.push({ key: 'input_size', label: 'Input size', value: inputSize })
  const outputSize = dims(params.output_width, params.output_height)
  if (outputSize) facts.push({ key: 'output_size', label: 'Output size', value: outputSize })
  const os = params.output_size as { width?: unknown; height?: unknown } | null | undefined
  const outputSize2 = os && typeof os === 'object' ? dims(os.width, os.height) : null
  if (outputSize2 && !outputSize) facts.push({ key: 'output_size', label: 'Output size', value: outputSize2 })
  const bbox = params.bbox as { x?: number; y?: number; width?: number; height?: number } | null | undefined
  if (bbox && typeof bbox === 'object') {
    facts.push({
      key: 'bbox',
      label: 'Crop region',
      value: `${bbox.x},${bbox.y} → ${bbox.width}×${bbox.height}`,
      long: true,
    })
  }

  for (const [key, value] of Object.entries(params)) {
    if (EXCLUDED_PARAMS.has(key)) continue
    if (isMediaReferenceParam(key)) continue
    if (value === null || value === undefined || value === '') continue
    if (typeof value === 'object') continue
    const formatted = formatParamValue(key, value, opts.filterLabel)
    facts.push({
      key,
      label: formatParamLabel(key),
      value: formatted,
      long: formatted.length > 16,
    })
  }
  return facts
}

/** Accepts a LoRA record in any producer's shape. */
export function formatLoraName(lora: unknown): string {
  if (typeof lora === 'string') return stripLoraPath(lora)
  const record = (lora && typeof lora === 'object' ? lora : {}) as Record<string, unknown>
  const raw = String(record.lora || record.path || record.name || record.filename || '')
  return stripLoraPath(raw)
}

function stripLoraPath(raw: string): string {
  const filename = raw.split(/[\\/]/).pop() || raw
  return filename.replace(/\.(safetensors|ckpt|pt|bin)$/i, '') || 'Unknown LoRA'
}

/** 0.8 → "0.8", 1 → "1.0", 0.75 → "0.75"; missing → "" (never throws). */
export function formatLoraWeight(weight: unknown): string {
  const n = typeof weight === 'number' ? weight : typeof weight === 'string' && weight.trim() !== '' ? Number(weight) : NaN
  if (!Number.isFinite(n)) return ''
  return n.toFixed(2).replace(/(\.\d)0$/, '$1')
}

/** Normalises every LoRA list shape (loras, selected_loras, imports' loras). */
export function normalizeLoras(list: unknown): ProvenanceLora[] {
  if (!Array.isArray(list)) return []
  return list
    .filter(item => item != null && item !== false)
    .filter(item => typeof item !== 'object' || (item as Record<string, unknown>).enabled !== false)
    .map(item => {
      const record = (typeof item === 'object' ? item : {}) as Record<string, unknown>
      const rawWeight = record.weight ?? record.strength
      const weight = typeof rawWeight === 'number' && Number.isFinite(rawWeight)
        ? rawWeight
        : typeof rawWeight === 'string' && Number.isFinite(Number(rawWeight)) && rawWeight.trim() !== ''
          ? Number(rawWeight)
          : null
      return { name: formatLoraName(item), weight }
    })
}

export function formatSourceRole(role: string | null | undefined): string {
  if (!role) return 'Input'
  return ROLE_LABELS[role] || sentenceCase(String(role).replace(/[_-]+/g, ' ').toLowerCase()) || 'Input'
}

export function formatPreprocessor(id: string | null | undefined, params?: unknown): string | null {
  if (!id) return null
  const label = PREPROCESSOR_LABELS[id] || sentenceCase(String(id).replace(/[_-]+/g, ' '))
  const p = (params && typeof params === 'object' ? params : null) as Record<string, unknown> | null
  if (!p) return label
  if (id === 'canny' && p.low != null && p.high != null) return `${label} (${p.low}-${p.high})`
  if (id === 'lineart' && p.sigma != null) return `${label} (σ${p.sigma})`
  return label
}

export function formatFlip(flip: unknown): string {
  if (!flip || typeof flip !== 'object') return ''
  const f = flip as { horizontal?: boolean; vertical?: boolean; rotation?: number }
  const parts: string[] = []
  if (f.horizontal) parts.push('H')
  if (f.vertical) parts.push('V')
  const rot = (((Number(f.rotation) || 0) % 360) + 360) % 360
  if (rot !== 0) parts.push(`${rot}°`)
  return parts.length ? `Flip ${parts.join(' ')}` : ''
}

function humanizeId(id: string): string {
  return sentenceCase(String(id).replace(/[_-]+/g, ' ').toLowerCase()) || String(id)
}

/** "text-to-image" → "Text to image". */
export function formatTaskType(taskType: string): string {
  return humanizeId(String(taskType).replace(/^.*:/, ''))
}

// --- File facts -------------------------------------------------------------

export function formatFileFormat(format: string | null | undefined): string {
  if (!format) return ''
  const lower = String(format).toLowerCase()
  return FILE_FORMAT_LABELS[lower] || String(format).toUpperCase()
}

export function formatFileSize(bytes: number | null | undefined): string {
  if (!bytes || bytes < 0) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

export function formatSampleRate(hz: number | null | undefined): string {
  if (!hz) return ''
  if (hz >= 1000) return `${(hz / 1000).toFixed(hz % 1000 === 0 ? 0 : 1)} kHz`
  return `${hz} Hz`
}

export function formatChannels(channels: number | null | undefined): string {
  if (channels === 1) return 'Mono'
  if (channels === 2) return 'Stereo'
  return channels ? `${channels} channels` : ''
}

export function formatBitrate(bps: number | null | undefined): string {
  if (!bps) return ''
  if (bps >= 1_000_000) return `${(bps / 1_000_000).toFixed(1)} Mbps`
  if (bps >= 1000) return `${Math.round(bps / 1000)} kbps`
  return `${bps} bps`
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

/** Last path segment, either separator. */
export function fileBasename(path: string | null | undefined): string {
  if (!path) return ''
  return String(path).split(/[\\/]/).pop() || String(path)
}

export function fileFacts(media: MediaLike | null | undefined): ProvenanceFact[] {
  const m = media
  if (!m) return []
  const facts: ProvenanceFact[] = []
  if (m.file_path) facts.push({ key: 'name', label: 'Name', value: fileBasename(m.file_path), long: true })
  if (m.file_format) facts.push({ key: 'format', label: 'Format', value: formatFileFormat(m.file_format) })
  if (m.file_size) facts.push({ key: 'size', label: 'Size', value: formatFileSize(m.file_size) })
  if (m.width && m.height && m.width > 0 && m.height > 0) {
    facts.push({ key: 'resolution', label: 'Resolution', value: `${m.width} × ${m.height}` })
  }
  if (m.duration) facts.push({ key: 'duration', label: 'Duration', value: formatDuration(m.duration) })
  if (m.audio_sample_rate) facts.push({ key: 'sample_rate', label: 'Sample rate', value: formatSampleRate(m.audio_sample_rate) })
  if (m.audio_bit_depth) facts.push({ key: 'bit_depth', label: 'Bit depth', value: `${m.audio_bit_depth}-bit` })
  if (m.audio_channels) facts.push({ key: 'channels', label: 'Channels', value: formatChannels(m.audio_channels) })
  if (m.audio_bitrate) facts.push({ key: 'bitrate', label: 'Bitrate', value: formatBitrate(m.audio_bitrate) })
  if (m.created_date) facts.push({ key: 'created', label: 'Created', value: formatDateTime(m.created_date) })
  return facts
}

// ---------------------------------------------------------------------------
// Building
// ---------------------------------------------------------------------------

function str(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function buildInputs(list: unknown): ProvenanceInput[] {
  if (!Array.isArray(list)) return []
  return list
    .filter((s): s is GenerationSourceInput & Record<string, unknown> => !!s && typeof s === 'object')
    .map(source => {
      const marks: string[] = []
      if (source.paint_layer) marks.push('Painted')
      if (source.extend_padding) marks.push('Extended')
      const flip = formatFlip(source.flip)
      if (flip) marks.push(flip)
      if (source.crop) marks.push('Cropped')
      return {
        role: str(source.role),
        roleLabel: formatSourceRole(source.role),
        mediaId: num(source.media_id),
        hash: str(source.file_hash) || str(source.hash),
        filePath: str(source.file_path),
        preprocessor: str(source.preprocessor),
        preprocessorParams: source.preprocessor_params ?? null,
        preprocessorLabel: formatPreprocessor(source.preprocessor, source.preprocessor_params),
        marks,
        deleted: !!source.deleted,
      }
    })
}

function chainNames(
  chain: unknown,
  toolName: (id: string) => string,
  filterLabel: (id: string) => string,
): string[] {
  if (!Array.isArray(chain)) return []
  return chain
    .map(step => {
      if (!step || typeof step !== 'object') return ''
      const s = step as Record<string, unknown>
      if (s.enabled === false) return ''
      if (s.kind === 'filter') return s.filter_id ? filterLabel(String(s.filter_id)) : ''
      if (s.tool_name) return String(s.tool_name)
      return s.tool_id ? toolName(String(s.tool_id)) : ''
    })
    .filter(Boolean)
}

interface StepSource {
  media_id?: number | null
  task_type?: string | null
  tool_id?: string | null
  model?: string | null
  generator?: string | null
  prompt?: string | null
  prompt_preview?: string | null
  negative_prompt?: string | null
  parameters?: Record<string, unknown>
  seed?: unknown
  generated_at?: string | null
  source_inputs?: GenerationSourceInput[]
  prompt_metadata?: GenerationMetadata['prompt_metadata']
  loras?: GenerationMetadata['loras']
}

function stepToolName(
  source: StepSource,
  imported: boolean,
  toolName: (id: string) => string,
): string {
  if (source.task_type === 'agent_edit') return 'Edited by agent'
  if (source.tool_id) return toolName(source.tool_id)
  if (source.task_type === 'filter') return 'Filter'
  if (imported || !source.task_type) return 'Imported'
  return formatTaskType(source.task_type)
}

function buildStep(
  source: StepSource,
  ctx: {
    key: string
    mediaId: number | null
    imported: boolean
    rawMetadata: string | null
    toolName: (id: string) => string
    filterLabel: (id: string) => string
    hideSize?: string | null
  },
): ProvenanceStep {
  const params = stepParameters(source)
  const tool = stepToolName(source, ctx.imported, ctx.toolName)
  const model = str(source.model)
  const prompt = str(source.prompt) || str(source.prompt_preview)
  const negativePrompt = str(source.negative_prompt) || str(params.negative_prompt)
  const original = str(source.prompt_metadata?.original_prompt)
  const originalPrompt = original && original.trim() !== (prompt || '').trim() ? original : null

  const facts: ProvenanceFact[] = []
  // The model row only when it says more than the step header already does.
  if (model && model.toLowerCase() !== tool.toLowerCase()) {
    facts.push({ key: 'model', label: 'Model', value: model, long: true })
  }
  for (const fact of paramFacts(params, { filterLabel: ctx.filterLabel })) {
    // The item's own output size repeats the file's resolution fact.
    if (ctx.hideSize && fact.key === 'size' && fact.value === ctx.hideSize) continue
    facts.push(fact)
  }

  const loras = normalizeLoras(params.loras ?? params.selected_loras ?? (ctx.imported ? source.loras : null))
  const inputs = buildInputs(source.source_inputs)
  const editStack = params.stack ?? null
  const edits = editStack
    ? summarizeStack(editStack, id => ctx.toolName(String(id || ''))).steps.map(step => step.name).filter(Boolean)
    : []
  const postProcessing = chainNames(params.post_processing_chain, ctx.toolName, ctx.filterLabel)

  const toolId = str(source.tool_id)
  const settings: ProvenanceSettings | null = toolId
    ? {
        toolId,
        mediaId: ctx.mediaId,
        prompt: prompt || '',
        negativePrompt: negativePrompt || '',
        generator: str(source.generator),
        model,
        parameters: params,
        sourceInputs: Array.isArray(source.source_inputs) ? source.source_inputs : [],
      }
    : null

  return {
    key: ctx.key,
    mediaId: ctx.mediaId,
    toolId,
    taskType: str(source.task_type),
    tool,
    model,
    date: normalizeDate(source.generated_at),
    imported: ctx.imported,
    prompt,
    negativePrompt,
    originalPrompt,
    facts,
    loras,
    inputs,
    edits,
    editStack,
    postProcessing,
    rawMetadata: ctx.rawMetadata,
    settings,
  }
}

/**
 * The normalised account of how `media` was made. Never throws: unreadable
 * metadata reads as a plain import.
 */
export function buildProvenance(media: MediaLike | null | undefined, opts: ProvenanceOptions = {}): MediaProvenance {
  const toolName = opts.toolName || ((id: string) => toolDisplayName(id, opts.tools || []))
  const filterLabel = opts.filterLabel || humanizeId
  const mediaId = media ? num(media.media_id) ?? num(media.id) : null
  const files = media && opts.fileFacts !== false ? fileFacts(media) : []
  if (!media) {
    return { mediaId: null, steps: [], flow: null, inspiredBy: null, imported: false, raw: true, fileFacts: [] }
  }
  const ownSize = media.width && media.height ? `${media.width}×${media.height}` : null
  const rawMetadata = str(media.raw_metadata)
  const meta = parseGenerationMetadata(media.generation_metadata)

  if (!meta) {
    // A plain file: one "Imported" step carrying whatever the file said about itself.
    const step = buildStep(
      {
        prompt: str(media.extracted_prompt),
        generated_at: str(media.indexed_date) || str(media.created_date),
      },
      { key: 'step-0', mediaId, imported: true, rawMetadata, toolName, filterLabel },
    )
    return { mediaId, steps: [step], flow: null, inspiredBy: null, imported: true, raw: true, fileFacts: files }
  }

  const imported = meta.source === 'external'
  const steps: ProvenanceStep[] = [
    buildStep(meta as StepSource, {
      key: 'step-0',
      mediaId,
      imported,
      rawMetadata: imported ? rawMetadata : null,
      toolName,
      filterLabel,
      hideSize: ownSize,
    }),
  ]

  // lineage_trace is oldest-first (each parent is appended after its own
  // ancestors), so walk it backwards to keep the history newest-first.
  const trace = Array.isArray(meta.lineage_trace) ? meta.lineage_trace : []
  for (let i = trace.length - 1; i >= 0; i--) {
    const ancestor = trace[i] as LineageTraceEntry & StepSource
    if (!ancestor || typeof ancestor !== 'object') continue
    steps.push(buildStep(ancestor, {
      key: `step-${steps.length}`,
      mediaId: num(ancestor.media_id),
      imported: false,
      rawMetadata: null,
      toolName,
      filterLabel,
    }))
  }

  const flowId = num(meta.flow_id)
  const flow = meta.source === 'flow' && flowId != null
    ? {
        flowId,
        equationKey: str(meta.equation_key),
        phasePath: Array.isArray(meta.phase_path) ? meta.phase_path.map(String) : [],
      }
    : null

  return {
    mediaId,
    steps,
    flow,
    inspiredBy: num(meta.inspired_by?.media_id),
    imported,
    raw: false,
    fileFacts: files,
  }
}

// ---------------------------------------------------------------------------
// Public ("how it was made") projection — the share request's `provenance`
// ---------------------------------------------------------------------------

export interface PublicProvenanceFact { label: string; value: string }
export interface PublicProvenanceLora { name: string; weight: number | null }
export interface PublicProvenanceInput { role: string; ref: { mediaId: number | null; hash: string | null } }

export interface PublicProvenanceStep {
  tool: string
  model?: string | null
  date?: string | null
  prompt?: string | null
  negativePrompt?: string | null
  originalPrompt?: string | null
  facts?: PublicProvenanceFact[]
  loras?: PublicProvenanceLora[]
  inputs?: PublicProvenanceInput[]
  edits?: string[]
}

export interface PublicProvenance {
  version: 2
  steps: PublicProvenanceStep[]
}

export const PUBLIC_PROVENANCE_LIMITS = {
  prompt: 8000,
  factValue: 200,
  label: 60,
  facts: 40,
  loras: 20,
  inputs: 16,
  steps: 32,
} as const

/** Strings that look like local filesystem locations never leave the machine. */
const ABSOLUTE_PATH = /(^|[\s"'(=:,])(\/Users\/|\/home\/|\/root\/|\/private\/|\/var\/folders\/|\/tmp\/|\/mnt\/|\/Volumes\/|[A-Za-z]:[\\/]|\\\\[^\\\s]+\\|file:\/\/|~\/)/
/** Parameters that name files, places or internal ids rather than settings. */
const PRIVATE_PARAM = /(^|_)(path|paths|file|files|filename|dir|directory|folder|url|uri|hash|ids?|token|key|secret)$/i

export function looksLikeAbsolutePath(value: unknown): boolean {
  return typeof value === 'string' && ABSOLUTE_PATH.test(value)
}

function cap(value: string | null | undefined, max: number): string | null {
  if (value == null) return null
  const text = String(value).trim()
  if (!text || looksLikeAbsolutePath(text)) return null
  return text.length > max ? text.slice(0, max) : text
}

function publicStep(step: ProvenanceStep): PublicProvenanceStep | null {
  const L = PUBLIC_PROVENANCE_LIMITS
  const tool = cap(step.tool, L.label) || 'Imported'
  const facts: PublicProvenanceFact[] = []
  for (const fact of step.facts) {
    if (fact.key === 'model') continue // published as `model`
    if (PRIVATE_PARAM.test(fact.key) || isMediaReferenceParam(fact.key)) continue
    const label = cap(fact.label, L.label)
    const value = cap(fact.value, L.factValue)
    if (label && value) facts.push({ label, value })
  }
  if (step.postProcessing.length) {
    const value = cap(step.postProcessing.join(' → '), L.factValue)
    if (value) facts.push({ label: 'Post-processing', value })
  }
  const loras = step.loras
    .map(lora => ({ name: cap(lora.name, L.label), weight: lora.weight }))
    .filter((lora): lora is PublicProvenanceLora => !!lora.name)
    .slice(0, L.loras)
  const inputs = step.inputs
    .filter(input => !input.deleted && (input.mediaId != null || input.hash))
    .map(input => ({
      role: cap(input.roleLabel, L.label) || 'Input',
      ref: { mediaId: input.mediaId, hash: input.hash },
    }))
    .slice(0, L.inputs)
  const edits = step.edits
    .map(edit => cap(edit, L.label))
    .filter((edit): edit is string => !!edit)

  const out: PublicProvenanceStep = { tool }
  const model = cap(step.model, L.label)
  if (model) out.model = model
  if (step.date) out.date = step.date
  const prompt = cap(step.prompt, L.prompt)
  if (prompt) out.prompt = prompt
  const negativePrompt = cap(step.negativePrompt, L.prompt)
  if (negativePrompt) out.negativePrompt = negativePrompt
  const originalPrompt = cap(step.originalPrompt, L.prompt)
  if (originalPrompt) out.originalPrompt = originalPrompt
  if (facts.length) out.facts = facts.slice(0, L.facts)
  if (loras.length) out.loras = loras
  if (inputs.length) out.inputs = inputs
  if (edits.length) out.edits = edits
  return out
}

function isMeaningful(step: PublicProvenanceStep, source: ProvenanceStep): boolean {
  if (step.prompt || step.negativePrompt || step.originalPrompt || step.model) return true
  if (step.loras?.length || step.inputs?.length || step.edits?.length) return true
  if (source.toolId) return true
  // An import whose only facts are its size says nothing about how it was made.
  return !!step.facts?.some(fact => fact.label !== 'Size')
}

/**
 * Exactly what the share request publishes as `provenance` (version 2,
 * newest-first steps), or null when there is nothing worth publishing.
 * Carries no file paths, raw params, provider internals or raw metadata; input
 * references (`ref`) are resolved to opaque thumbnails by the desktop backend.
 */
export function toPublicProvenance(provenance: MediaProvenance | null | undefined): PublicProvenance | null {
  if (!provenance?.steps?.length) return null
  const steps: PublicProvenanceStep[] = []
  for (const source of provenance.steps.slice(0, PUBLIC_PROVENANCE_LIMITS.steps)) {
    const step = publicStep(source)
    if (step) steps.push(step)
  }
  if (!steps.some((step, i) => isMeaningful(step, provenance.steps[i]))) return null
  return { version: 2, steps }
}

/** How many steps a share would publish (0 when none). */
export function publicStepCount(provenance: PublicProvenance | null | undefined): number {
  return provenance?.steps?.length ?? 0
}
