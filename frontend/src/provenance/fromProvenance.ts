/**
 * The app's provenance model → the provenance view. App-side only (it reads
 * `utils/mediaProvenance`), so the share page's bundle never includes it.
 *
 * Thumbnail references are `AppThumbRef`s, which the app host draws:
 * library media through MediaImage, reference files and preprocessed
 * previews through the backend's preview routes.
 */

import {
  factRows,
  stepFactRows,
  type MediaProvenance,
  type ProvenanceInput,
  type ProvenanceStep,
} from '../utils/mediaProvenance.ts'
import type { ProvenanceView, ViewInput, ViewStep } from './types.ts'

export type AppThumbRef =
  | { kind: 'media'; mediaId: number; hash: string | null; filePath: string | null }
  | { kind: 'file'; filePath: string }
  | { kind: 'preprocessed'; sourcePath: string; preprocessor: string; params: unknown }

function inputThumb(input: ProvenanceInput): AppThumbRef | null {
  if (input.mediaId != null) return { kind: 'media', mediaId: input.mediaId, hash: input.hash, filePath: input.filePath }
  if (input.filePath) return { kind: 'file', filePath: input.filePath }
  return null
}

function inputPreview(input: ProvenanceInput): AppThumbRef | null {
  if (!input.preprocessor || !input.filePath) return null
  return { kind: 'preprocessed', sourcePath: input.filePath, preprocessor: input.preprocessor, params: input.preprocessorParams }
}

function viewInput(input: ProvenanceInput, i: number): ViewInput {
  return {
    key: `input-${i}`,
    role: input.roleLabel,
    preprocessor: input.preprocessorLabel,
    badges: input.marks,
    thumb: inputThumb(input),
    preview: inputPreview(input),
    deleted: input.deleted,
    origin: input,
  }
}

export function viewStepFromProvenance(step: ProvenanceStep): ViewStep {
  return {
    key: step.key,
    tool: step.tool,
    icon: step.icon,
    date: step.date,
    imported: step.imported,
    prompt: step.prompt,
    negativePrompt: step.negativePrompt,
    originalPrompt: step.originalPrompt,
    facts: stepFactRows(step),
    inputs: step.inputs.map(viewInput),
    editSteps: step.editSteps.map(edit => ({
      key: edit.key,
      name: edit.name,
      detail: edit.detail,
      note: edit.note,
      thumb: edit.ref?.mediaId != null
        ? { kind: 'media', mediaId: edit.ref.mediaId, hash: edit.ref.hash, filePath: null } satisfies AppThumbRef
        : null,
    })),
    rawMetadata: step.rawMetadata,
    origin: step,
  }
}

export function viewFromProvenance(provenance: MediaProvenance): ProvenanceView {
  return {
    steps: provenance.steps.map(viewStepFromProvenance),
    file: factRows(provenance.fileFacts),
  }
}
