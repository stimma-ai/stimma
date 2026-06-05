/**
 * Lightweight reactive store for named wildcards and prompt segments.
 *
 * Wildcards and segments are loaded from settings on app boot and updated when settings change.
 * The submission queue reads from this store to expand {{name}} tokens.
 */
import { ref } from 'vue'
import type { NamedWildcard, PromptSegment } from '../utils/promptProcessor'

const wildcards = ref<NamedWildcard[]>([])
const segments = ref<PromptSegment[]>([])

/**
 * Update the cached wildcards list.
 * Called from App.vue on boot and from SettingsModal when wildcards change.
 */
export function setWildcards(newWildcards: NamedWildcard[]) {
  wildcards.value = newWildcards
}

/**
 * Get the current wildcards list (reactive ref).
 */
export function useWildcards() {
  return { wildcards }
}

/**
 * Get the current wildcards list snapshot (non-reactive, for one-shot use).
 */
export function getWildcards(): NamedWildcard[] {
  return wildcards.value
}

/**
 * Update the cached prompt segments list.
 */
export function setSegments(newSegments: PromptSegment[]) {
  segments.value = newSegments
}

/**
 * Get the current segments list (reactive ref).
 */
export function useSegments() {
  return { segments }
}

/**
 * Get the current segments list snapshot (non-reactive, for one-shot use).
 */
export function getSegments(): PromptSegment[] {
  return segments.value
}
