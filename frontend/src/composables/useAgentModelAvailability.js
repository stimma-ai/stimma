import { computed, ref } from 'vue'
import { useAvailableModels } from './useAvailableModels'

/**
 * Resolve whether an agent input has any model it can actually use.
 *
 * Each input owns its checked flag so it stays interactive while its first
 * availability request is in flight instead of flashing the unavailable
 * treatment during startup. The model catalog itself remains shared.
 */
export function useAgentModelAvailability() {
  const { models, error, loading, fetchModels } = useAvailableModels()
  const checked = ref(false)

  const hasViableAgentModel = computed(() => (
    models.value.some(model => model.available !== false)
  ))

  const agentModelUnavailable = computed(() => (
    checked.value && !loading.value && !error.value && !hasViableAgentModel.value
  ))

  async function checkAgentModels(projectId = null, force = false) {
    try {
      await fetchModels(projectId, force)
    } finally {
      checked.value = true
    }
  }

  return {
    agentModelUnavailable,
    hasViableAgentModel,
    checkAgentModels,
  }
}
