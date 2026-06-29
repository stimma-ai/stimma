/**
 * Canonical shape of `media_items.generation_metadata`.
 *
 * This MIRRORS the backend single source of truth in
 * `backend/generation_metadata.py` (build_generation_metadata). Every producer —
 * the generation queue (tool view / agent / flow tool calls), composite-media
 * tools (sets/grids/layouts), document creation, code-save, the edit endpoint,
 * and external-import normalization — writes this exact envelope, so consumers
 * can rely on the same keys regardless of media type or origin.
 *
 * Keep this in sync with the Python builder. Treat every field as possibly
 * absent when reading: rows written before the builder existed won't have the
 * full set (hence the `?` everywhere), so always default when consuming.
 */

export interface GenerationSourceInput {
  media_id?: number
  file_path?: string
  /** start_image | end_image | input_image | source_image | item | cell | ... */
  role?: string
  filename?: string
  // Image-edit preprocessing hints (present for image-to-image source inputs)
  preprocessor?: string | null
  preprocessor_params?: unknown
  paint_layer?: string | null
  extend_padding?: unknown
  extend_bg_color?: string | null
  scale?: unknown
  flip?: unknown
  /** Set by the hard-delete tombstoner when a source media item is purged. */
  deleted?: boolean
}

/** Pre-enhancement prompt + enhance settings, captured at submission. */
export interface PromptMetadata {
  original_prompt?: string
  auto_improve_enabled?: boolean
  auto_improve_instructions?: string
  translate_enabled?: boolean
  translate_language?: string
}

/** One ancestor in the embedded generation history (newest-first). */
export interface LineageTraceEntry {
  media_id: number
  task_type?: string
  model?: string
  generator?: string
  prompt?: string
  negative_prompt?: string
  parameters?: Record<string, unknown>
  generated_at?: string
  source_inputs?: GenerationSourceInput[]
  tool_id?: string
}

export interface GenerationMetadata {
  /** Schema version. Currently 3. */
  version?: number
  /** "stimma" | "flow" | "external" | "batch" | "agent_v2_*" | "flow_create_layout" ... */
  source?: string
  /** text-to-image, image-to-image, image-to-video, layout, document-creation, ... */
  task_type?: string
  tool_id?: string | null
  generator?: string | null
  model?: string | null
  prompt?: string
  negative_prompt?: string
  /** Flat dict of the params actually used (seed, steps, cfg, fps, generation_time, ...). */
  parameters?: Record<string, unknown>
  prompt_metadata?: PromptMetadata | null
  source_inputs?: GenerationSourceInput[]
  lineage_trace?: LineageTraceEntry[]
  generated_at?: string
  inspired_by?: { media_id: number }

  // Producer-specific extras carried in the same envelope:
  /** Flow context (added by _tag_media_with_flow). */
  flow_id?: number
  equation_key?: string
  phase_path?: string[]
  /** Document/fetch media type specifics. */
  format?: string
  source_url?: string
  /** External imports (A1111/etc.) carry their LoRA list here. */
  loras?: Array<{ name?: string; lora?: string; path?: string; weight?: number }>
  /** Composite counts. */
  item_count?: number
  cell_count?: number
  batch_id?: string
}
