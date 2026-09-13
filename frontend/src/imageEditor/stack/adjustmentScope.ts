import type { GradientMask, SelectionSemantic } from './types.ts'
import type { WorkspaceMaskGesture } from './workspaceMaskComposition.ts'

/** What a recomputable semantic selection was a selection OF. */
export type AdjustmentScopeSemantic = SelectionSemantic

/**
 * The selection an Adjust action saw at the instant it was activated.
 *
 * Creating an adjustment may first remove an untouched provisional step. That
 * work can render and reproject workspace state, so reading the live selection
 * afterwards makes the click race the housekeeping that precedes it. Capture
 * the representation the scoped step will consume up front: editable geometry
 * for a matching gradient, the gesture COMPOSITION when the selection was built
 * from more than one tracked gesture (each ingredient becomes an editable
 * mask component), or an immutable raster copy for everything else — carrying
 * its semantic identity when the selection IS one recomputable semantic
 * gesture, so the step's base component can keep the name.
 */
export type AdjustmentScopeSnapshot<TMask> =
  | { kind: 'gradient'; gradient: GradientMask }
  | { kind: 'raster'; mask: TMask; semantic?: AdjustmentScopeSemantic }
  | { kind: 'composition'; entries: WorkspaceMaskGesture<TMask>[] }

export function captureAdjustmentScope<TMask>(
  selection: TMask | null,
  copyMask: (source: TMask) => TMask,
  workspaceGradient: GradientMask | null,
  workspaceGradientKey: string | null,
  selectionAppliedKey: string | null,
  workspaceSemantic: AdjustmentScopeSemantic | null = null,
  workspaceSemanticKey: string | null = null,
  workspaceComposition: WorkspaceMaskGesture<TMask>[] | null = null,
  workspaceCompositionKey: string | null = null,
): AdjustmentScopeSnapshot<TMask> | null {
  if (!selection) return null
  if (workspaceGradient && workspaceGradientKey === selectionAppliedKey) {
    return { kind: 'gradient', gradient: { ...workspaceGradient } }
  }
  // One tracked gesture is exactly the raster/semantic capture below; the
  // composition only earns its structure once there are ingredients to keep.
  if (
    workspaceComposition
    && workspaceComposition.length >= 2
    && workspaceCompositionKey === selectionAppliedKey
  ) {
    return {
      kind: 'composition',
      entries: workspaceComposition.map(entry => ({
        ...entry,
        ...(entry.mask !== undefined ? { mask: copyMask(entry.mask) } : {}),
        ...(entry.gradient ? { gradient: { ...entry.gradient } } : {}),
        ...(entry.semantic ? { semantic: { ...entry.semantic } } : {}),
      })),
    }
  }
  const semantic =
    workspaceSemantic && workspaceSemanticKey === selectionAppliedKey
      ? { ...workspaceSemantic }
      : undefined
  return { kind: 'raster', mask: copyMask(selection), ...(semantic ? { semantic } : {}) }
}
