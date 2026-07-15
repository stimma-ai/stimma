/**
 * Composable for fetching and caching available LLM models.
 * Used by the chat model picker and settings default model selector.
 */
import { computed, ref, readonly } from 'vue'
import axios from 'axios'
import { getApiBase } from '../apiConfig'
import { isPrivacyLockdownActive } from './usePrivacyLockdown'
import { sortModelsByBrand } from '../utils/modelVendors'

const models = ref([])
const globalDefault = ref('auto')
const quickTaskModel = ref('stimma:minimax-m3')
const reasoningLevels = ref({})
const cloudStatus = ref('unknown')
const cloudMessage = ref('')
const error = ref(null)
const loading = ref(false)
const lastFetchTime = ref(0)
// The project scope of the most recent fetch, so a background refresh (e.g. on
// window focus) can re-fetch the same scope instead of clobbering it with the
// global list.
const lastProjectId = ref(null)

const LEGACY_MODEL_SLUGS = {
  'agent-max': 'stimma:minimax-m3',
  default: 'stimma:minimax-m3',
}

export function normalizeModelSlug(slug) {
  return LEGACY_MODEL_SLUGS[slug] || slug
}

const CACHE_TTL_MS = 60_000 // 1 minute cache
const hasFetched = computed(() => lastFetchTime.value > 0)
const visibleModels = computed(() => {
  if (!isPrivacyLockdownActive()) return models.value

  const nonCloudModels = models.value.filter(
    model => model.source !== 'stimma_cloud' && model.source !== 'auto'
  )
  const cachedAuto = models.value.find(model => model.source === 'auto')
  if (!cachedAuto) return nonCloudModels
  if (cachedAuto.resolved_slug === 'auto') return [cachedAuto, ...nonCloudModels]

  const localModel = nonCloudModels.find(
    model => model.source === 'endpoint' && model.available !== false
  )
  const localAuto = localModel
    ? {
        ...cachedAuto,
        name: `Auto: ${localModel.name}`,
        description: 'Uses your configured model endpoint.',
        available: true,
        status: 'available',
        resolved_slug: localModel.slug,
        max_context_tokens: localModel.max_context_tokens,
      }
    : {
        ...cachedAuto,
        name: 'Set up a local model',
        description: 'Add a model endpoint in Settings > LLM Providers.',
        available: false,
        status: 'llm_not_configured',
        resolved_slug: null,
      }

  return [localAuto, ...nonCloudModels]
})
const effectiveGlobalDefault = computed(() => {
  if (!isPrivacyLockdownActive()) return globalDefault.value
  return [null, 'auto', 'local'].includes(globalDefault.value) ? globalDefault.value : 'auto'
})

/**
 * Fetch available models from the backend.
 * Caches results for CACHE_TTL_MS to avoid redundant network calls.
 */
async function fetchModels(projectId = null, force = false) {
  const now = Date.now()
  const requestedProjectId = projectId ?? null
  if (
    !force
    && models.value.length > 0
    && lastProjectId.value === requestedProjectId
    && now - lastFetchTime.value < CACHE_TTL_MS
  ) {
    return
  }

  lastProjectId.value = requestedProjectId
  loading.value = true
  try {
    const params = {}
    if (projectId != null) params.project_id = projectId
    const response = await axios.get(`${getApiBase()}/models/available`, { params })
    models.value = sortModelsByBrand(response.data.models || [])
    globalDefault.value = normalizeModelSlug(response.data.global_default || 'auto')
    quickTaskModel.value = normalizeModelSlug(response.data.quick_task_model || 'stimma:minimax-m3')
    reasoningLevels.value = response.data.reasoning_levels || {}
    cloudStatus.value = response.data.cloud_status || 'unknown'
    cloudMessage.value = response.data.cloud_message || ''
    error.value = null
    lastFetchTime.value = now
  } catch (err) {
    console.warn('Failed to fetch available models:', err)
    error.value = err
  } finally {
    loading.value = false
  }
}

/**
 * Force a re-fetch of model availability at the last-used project scope.
 * Used to re-sync after returning from an external flow (e.g. Stripe checkout),
 * where a new subscription changes which cloud models are available but nothing
 * else would refetch. Safe to call frequently — it's a single lightweight GET.
 */
export function refreshAvailableModels() {
  return fetchModels(lastProjectId.value, true)
}

/**
 * Get the display name for a model slug.
 * Falls back to the slug itself if not found.
 */
function getModelDisplayName(slug) {
  slug = normalizeModelSlug(slug)
  if (!slug) return getModelDisplayName(effectiveGlobalDefault.value)
  const model = visibleModels.value.find(m => m.slug === slug)
  if (model?.slug === 'auto' && model.resolved_slug) {
    const resolved = visibleModels.value.find(m => m.slug === model.resolved_slug)
    if (resolved?.available !== false) return resolved.name
  }
  if (!model) return visibleModels.value.length > 0 ? `${slug} · unavailable` : slug
  if (model.slug === 'auto' && model.available === false) return model.name
  return model.available === false ? `${model.name} · unavailable` : model.name
}

/**
 * Get the concrete model a slug resolves to. Legacy "auto" may resolve to
 * MiniMax M3, a local endpoint, or no usable model depending on availability.
 */
function getResolvedModel(slug) {
  slug = normalizeModelSlug(slug)
  const model = visibleModels.value.find(m => m.slug === slug)
  if (model?.slug === 'auto' && model.resolved_slug) {
    return visibleModels.value.find(m => m.slug === model.resolved_slug) || model
  }
  return model
}

/**
 * Invalidate the cache so next access triggers a re-fetch.
 */
function invalidateCache() {
  lastFetchTime.value = 0
}

export function useAvailableModels() {
  return {
    models: readonly(visibleModels),
    globalDefault: readonly(effectiveGlobalDefault),
    quickTaskModel: readonly(quickTaskModel),
    reasoningLevels: readonly(reasoningLevels),
    cloudStatus: readonly(cloudStatus),
    cloudMessage: readonly(cloudMessage),
    error: readonly(error),
    loading: readonly(loading),
    hasFetched: readonly(hasFetched),
    fetchModels,
    getModelDisplayName,
    getResolvedModel,
    invalidateCache,
  }
}
