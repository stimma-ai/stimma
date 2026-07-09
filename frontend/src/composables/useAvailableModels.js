/**
 * Composable for fetching and caching available LLM models.
 * Used by the chat model picker and settings default model selector.
 */
import { ref, readonly } from 'vue'
import axios from 'axios'
import { getApiBase } from '../apiConfig'

const models = ref([])
const globalDefault = ref('auto')
const cloudStatus = ref('unknown')
const cloudMessage = ref('')
const error = ref(null)
const loading = ref(false)
const lastFetchTime = ref(0)
// The project scope of the most recent fetch, so a background refresh (e.g. on
// window focus) can re-fetch the same scope instead of clobbering it with the
// global list.
const lastProjectId = ref(null)

const CACHE_TTL_MS = 60_000 // 1 minute cache

/**
 * Fetch available models from the backend.
 * Caches results for CACHE_TTL_MS to avoid redundant network calls.
 */
async function fetchModels(projectId = null, force = false) {
  const now = Date.now()
  if (!force && models.value.length > 0 && now - lastFetchTime.value < CACHE_TTL_MS) {
    return
  }

  lastProjectId.value = projectId
  loading.value = true
  try {
    const params = {}
    if (projectId != null) params.project_id = projectId
    const response = await axios.get(`${getApiBase()}/models/available`, { params })
    models.value = response.data.models || []
    globalDefault.value = response.data.global_default || 'auto'
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
  if (!slug) return getModelDisplayName(globalDefault.value)
  const model = models.value.find(m => m.slug === slug)
  if (model?.slug === 'auto' && model.resolved_slug) {
    const resolved = models.value.find(m => m.slug === model.resolved_slug)
    if (resolved?.available !== false) return resolved.name
  }
  if (!model) return models.value.length > 0 ? `${slug} · unavailable` : slug
  if (model.slug === 'auto' && model.available === false) return model.name
  return model.available === false ? `${model.name} · unavailable` : model.name
}

/**
 * Get the concrete model a slug resolves to. Legacy "auto" may resolve to
 * Stimma Agent Max, Local Endpoint, or no usable model depending on availability.
 */
function getResolvedModel(slug) {
  const model = models.value.find(m => m.slug === slug)
  if (model?.slug === 'auto' && model.resolved_slug) {
    return models.value.find(m => m.slug === model.resolved_slug) || model
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
    models: readonly(models),
    globalDefault: readonly(globalDefault),
    cloudStatus: readonly(cloudStatus),
    cloudMessage: readonly(cloudMessage),
    error: readonly(error),
    loading: readonly(loading),
    fetchModels,
    getModelDisplayName,
    getResolvedModel,
    invalidateCache,
  }
}
