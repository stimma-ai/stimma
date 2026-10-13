/**
 * Components' handle on `utils/mediaProvenance`: the same pure builder, wired
 * to the tools cache (display names) and the filter catalogue (labels), and
 * reactive to both. Loads the tools cache on first use so tool names resolve
 * on a cold start instead of falling back to humanized ids.
 */
import { computed, onMounted, type MaybeRefOrGetter, toValue } from 'vue'
import { useProvidersApi } from './useProvidersApi'
import { getFilterDisplayLabel } from '../utils/filterDefs'
import { toolDisplayName } from '../utils/toolDisplay'
import {
  buildProvenance,
  toPublicProvenance,
  type MediaLike,
  type MediaProvenance,
  type ProvenanceOptions,
  type PublicProvenance,
} from '../utils/mediaProvenance'

export function useProvenanceBuilder() {
  const { cachedTools, fetchProvidersAndTools } = useProvidersApi()
  // Cached and shared; a failure leaves humanized tool ids in place.
  onMounted(() => { fetchProvidersAndTools().catch(() => {}) })

  function build(media: MediaLike | null | undefined, opts: ProvenanceOptions = {}): MediaProvenance {
    return buildProvenance(media, {
      tools: cachedTools.value,
      filterLabel: getFilterDisplayLabel,
      ...opts,
    })
  }

  function toolName(toolId: string | null | undefined): string {
    return toolDisplayName(toolId, cachedTools.value)
  }

  return { build, toolName }
}

/** Reactive provenance for one media item. */
export function useMediaProvenance(media: MaybeRefOrGetter<MediaLike | null | undefined>) {
  const { build } = useProvenanceBuilder()
  const provenance = computed(() => build(toValue(media)))
  const publicProvenance = computed<PublicProvenance | null>(() => toPublicProvenance(provenance.value))
  return { provenance, publicProvenance }
}
