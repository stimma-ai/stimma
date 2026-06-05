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
 * Get the display name for a model slug.
 * Falls back to the slug itself if not found.
 */
function getModelDisplayName(slug) {
  if (!slug) return getModelDisplayName(globalDefault.value)
  const model = models.value.find(m => m.slug === slug)
  if (!model) return models.value.length > 0 ? `${slug} · unavailable` : slug
  return model.available === false ? `${model.name} · unavailable` : model.name
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
    invalidateCache,
  }
}
