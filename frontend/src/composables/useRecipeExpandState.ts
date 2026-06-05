import { reactive, computed, type ComputedRef } from 'vue'

/**
 * Sticky expand/collapse state for recipe step rows and iteration groups.
 *
 * Lives at module scope — survives PhaseNode unmounts that happen whenever
 * the phase tree rebuilds from a program edit / re-parse, which was the bug
 * where previously-expanded rows silently re-collapsed. Keys are scoped by
 * recipeId so forks and parallel recipes don't cross-contaminate.
 *
 * No persistence across page reloads (yet). If users want that, switch the
 * reactive Map to a localStorage-backed ref — the consumer shape doesn't
 * need to change.
 */

type RowKind = 'info' | 'hitl' | 'trace' | 'group'

function stateKey(recipeId: number | string | null, rowKind: RowKind, id: string): string {
  return `${recipeId ?? 'global'}:${rowKind}:${id}`
}

// Keyed by stateKey() → explicit user override. Absence means "use default".
const overrides = reactive(new Map<string, boolean>())

export function useRecipeExpandState(recipeIdRef: ComputedRef<number | string | null> | { value: number | string | null }) {
  function getOverride(rowKind: RowKind, id: string): boolean | undefined {
    return overrides.get(stateKey(recipeIdRef.value, rowKind, id))
  }
  function setOverride(rowKind: RowKind, id: string, value: boolean): void {
    overrides.set(stateKey(recipeIdRef.value, rowKind, id), value)
  }
  function isExpanded(rowKind: RowKind, id: string, defaultExpanded: boolean): boolean {
    const o = getOverride(rowKind, id)
    return o === undefined ? defaultExpanded : o
  }
  function toggle(rowKind: RowKind, id: string, currentlyExpanded: boolean): void {
    setOverride(rowKind, id, !currentlyExpanded)
  }

  return {
    isExpanded,
    toggle,
    setOverride,
    // Exposed so callers can react to state changes (`isExpanded` already
    // reads from the reactive Map, so bare function calls work in template
    // bindings and computed()).
    overridesRef: computed(() => overrides),
  }
}
