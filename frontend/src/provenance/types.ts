/**
 * The provenance view model: everything the "how it was made" components
 * render, already formatted. Two producers fill it:
 *
 *   viewFromProvenance(MediaProvenance)   the app, from local metadata
 *   viewFromPublished(sidecar v2 | v3)    the share page, from a published sidecar
 *
 * so the in-app history and the public panel are one set of components fed
 * one shape. Thumbnail references (`thumb`, `preview`) are opaque here: only
 * the host that draws them (see `host.ts`) knows what they point at — a
 * library media id in the app, a data-URI key on the share page.
 */

/** One single-line fact (KeyValueList row shape). */
export interface ViewFact {
  key: string
  label: string
  value: string
  /** Facts voice (numbers, ids, sizes); false for names and words. */
  mono: boolean
  /** Single-line ellipsis, full value in the title. */
  truncate: boolean
  /** Semantic value color override (a non-default LoRA weight reads accent). */
  valueClass?: string
  /** Render the host's trailing actions beside the value. */
  actions?: boolean
}

export interface ViewInput {
  key: string
  /** Sentence-case role ("Reference", "Start frame"). */
  role: string
  /** What the tool saw when a preprocessor ran ("Depth", "Canny (100-200)"). */
  preprocessor: string | null
  /** Other prep applied to the input: Painted, Extended, Flip H, Cropped. */
  badges: string[]
  /** Host-specific reference to the input's thumbnail, or null. */
  thumb: unknown
  /** Host-specific reference to the preprocessed preview, or null. */
  preview: unknown
  /** The source was purged; only a tombstone remains. */
  deleted: boolean
  /** Host-only context (the app keeps the full input here). */
  origin?: unknown
}

export interface ViewEditStep {
  key: string
  /** What the step was called in the editor's Edits list. */
  name: string
  /** The one supporting fact, or ''. */
  detail: string
  /** A second line: the prompt, or what a container holds. */
  note: string
  /** Host-specific thumbnail reference (a reference image), or null. */
  thumb: unknown
}

export interface ViewStep {
  key: string
  /** Display name of whatever made this step. Always set. */
  tool: string
  /** Task-type icon key; unknown keys draw the default glyph. */
  icon: string | null
  /** ISO-8601 UTC, or null. */
  date: string | null
  imported: boolean
  prompt: string | null
  negativePrompt: string | null
  originalPrompt: string | null
  /** Params, post-processing chain and LoRAs, in that order. */
  facts: ViewFact[]
  inputs: ViewInput[]
  /** What the image editor did, newest first. */
  editSteps: ViewEditStep[]
  /** External metadata carried by an import (app only). */
  rawMetadata: string | null
  /** Host-only context (the app keeps its ProvenanceStep here). */
  origin?: unknown
}

export interface ProvenanceView {
  /** Newest first: the item's own step, then its ancestors. */
  steps: ViewStep[]
  /** File facts (format, resolution, size…). */
  file: ViewFact[]
}

// ---------------------------------------------------------------------------
// Published sidecar (what GET /api/s/:code/history returns)
// ---------------------------------------------------------------------------

export interface PublishedFact { label: string; value: string }

export interface PublishedInput {
  role?: string
  thumb?: string
  badges?: string[]
  preprocessor?: string
  preview?: string
}

export interface PublishedEditStep { label: string; thumb?: string }

export interface PublishedStep {
  tool: string
  icon?: string
  model?: string | null
  date?: string | null
  prompt?: string | null
  negativePrompt?: string | null
  originalPrompt?: string | null
  facts?: PublishedFact[]
  loras?: { name: string; weight?: number | null }[]
  inputs?: PublishedInput[]
  editSteps?: PublishedEditStep[]
  /** v2 readers' edit list; superseded by `editSteps` when present. */
  edits?: string[]
}

export interface PublishedSidecar {
  version: 2 | 3
  file?: PublishedFact[]
  steps: PublishedStep[]
  thumbnails?: Record<string, string>
}
