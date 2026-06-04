import type { RecipeEquation } from './useRecipesApi'

/**
 * Identifies a recipe's surfaced outputs.
 *
 * The `foreach_iteration` wrappers are skipped even when they are outputs:
 * their `result_from` mirrors an inner tool call's media, so including the
 * wrapper would double-count. We take the wrappers' inner tool equations
 * instead when the enclosing foreach primitive is surfaced as an output.
 */

export interface OutputMediaItem {
  mediaId: number
  sourceKey: string
  sourceLabel: string | null
  sourceEquationType: string
  outputName: string | null
  // For iterations, 1-based index within the foreach so the panel can
  // badge/label tiles in a recognisable order.
  iterationIndex: number | null
}

function isForeachPrimitive(eq: RecipeEquation): boolean {
  return eq.equation_type === 'control' && eq.control_kind === 'foreach'
}
function isIterationWrapper(eq: RecipeEquation): boolean {
  return eq.equation_type === 'control' && eq.control_kind === 'foreach_iteration'
}

export function computeRecipeOutputs(
  equationsByKey: Map<string, RecipeEquation>,
): OutputMediaItem[] {
  const items: OutputMediaItem[] = []
  const seenMedia = new Set<number>()

  function push(
    mid: number,
    eq: RecipeEquation,
    iterIdx: number | null,
    outputName: string | null = eq.output_name ?? null,
  ) {
    if (seenMedia.has(mid)) return
    seenMedia.add(mid)
    items.push({
      mediaId: mid,
      sourceKey: eq.equation_key,
      sourceLabel: eq.display_name ?? null,
      sourceEquationType: eq.equation_type,
      outputName,
      iterationIndex: iterIdx,
    })
  }

  for (const eq of equationsByKey.values()) {
    // Terminal foreach primitive → collect media from its iteration wrappers'
    // inner tool calls, preserving iteration order.
    if (isForeachPrimitive(eq) && eq.is_output) {
      const prefix = eq.equation_key + '/'
      const wrappers = [...equationsByKey.values()]
        .filter((w) => isIterationWrapper(w) && w.equation_key.startsWith(prefix))
        // Stable order — use equation_key (iteration suffix encodes position
        // for KEYED sources and literal index for POSITIONAL).
        .sort((a, b) => a.equation_key.localeCompare(b.equation_key))
      for (let i = 0; i < wrappers.length; i++) {
        const w = wrappers[i]
        // Find the child equation that actually produced media inside this
        // iteration. Prefer the one the wrapper mirrors (`result_from`), fall
        // back to any descendant with media.
        const mirror = w.result_from ? equationsByKey.get(w.result_from) : null
        const source = (mirror && (mirror.result_media_ids?.length || 0) > 0)
          ? mirror
          : [...equationsByKey.values()].find(
              (c) => c.equation_key.startsWith(w.equation_key + '/')
                && (c.result_media_ids?.length || 0) > 0,
            ) || null
        const mids = source?.result_media_ids || w.result_media_ids || []
        for (const mid of mids) push(mid, source || w, i + 1, eq.output_name ?? null)
      }
      continue
    }

    // Non-scaffolding leaves with direct media → include as-is.
    if (eq.is_scaffolding) continue
    if ((eq.result_media_ids?.length || 0) === 0) continue
    if (!eq.is_output) continue
    for (const mid of eq.result_media_ids) push(mid, eq, null)
  }

  return items
}
