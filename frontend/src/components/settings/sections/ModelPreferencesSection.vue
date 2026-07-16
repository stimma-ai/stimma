<template>
  <div class="space-y-6">
    <section>
      <div class="mb-3">
        <div class="flex items-center gap-3">
          <h3 class="text-base font-medium text-content">Preferences</h3>
        </div>
      </div>

      <div class="mt-8 space-y-9">
        <div>
          <div class="flex items-center justify-between gap-6">
            <div class="min-w-0 max-w-md">
              <h4 class="text-sm font-medium text-content">LLM for Quick Tasks</h4>
              <p class="mt-1 text-xs leading-relaxed text-content-tertiary">Prompt cleanup, chat names, and other background work.</p>
            </div>
            <div v-if="quickTaskOptions.length" class="shrink-0">
              <SettingsDropdown
                control
                fill
                class="w-72"
                :menu-width="320"
                :model-value="selectedQuickTaskValue"
                :options="quickTaskOptions"
                placeholder="Choose a model"
                @update:model-value="saveQuickTaskModel"
              />
            </div>
            <div v-else class="w-72 py-2 text-sm text-content-muted">No models available</div>
          </div>
        </div>

        <div v-if="voiceSupported">
          <div class="flex items-center justify-between gap-6">
            <div class="min-w-0 max-w-md">
              <h4 class="text-sm font-medium text-content">Voice Input Model</h4>
              <p class="mt-1 text-xs leading-relaxed text-content-tertiary">
                Processed on this device. <template v-if="!voiceModelReady"> {{ privacyLockdownActive ? 'Downloads are off during Privacy Lockdown.' : 'Downloads on first use.' }}</template>
              </p>
            </div>
            <div class="flex shrink-0 items-center gap-2">
              <svg v-if="voiceModelReady" class="h-4 w-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
              </svg>
              <SettingsDropdown
                v-model="voiceModel"
                control
                compact
                fill
                hide-trigger-details
                class="w-72"
                :menu-width="320"
                :options="voiceModelOptions"
              />
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../../apiConfig'
import { useAvailableModels } from '../../../composables/useAvailableModels'
import { usePrivacyLockdown } from '../../../composables/usePrivacyLockdown'
import { VOICE_MODELS, voiceModel, isModelReady, supported as voiceSupported } from '../../../composables/useVoiceInput'
import SettingsDropdown from '../../ui/SettingsDropdown.vue'
import { resolveModelVendorId } from '../../../utils/modelVendors'

const { selectableModels, quickTaskModel, fetchModels } = useAvailableModels()
const { privacyLockdownActive } = usePrivacyLockdown()

const voiceModelReady = ref(false)

function endpointHost(url) {
  if (!url) return ''
  try { return new URL(url).host } catch { return url }
}

const quickTaskOptions = computed(() => {
  return selectableModels.value.filter(model => model.source !== 'auto' && !model.collapsed).map(model => ({
    value: model.slug,
    label: model.name,
    description: `via ${model.source === 'stimma_cloud' ? 'Stimma' : (model.provider_name || endpointHost(model.endpoint_url) || 'your endpoint')}`,
    meta: model.cost_tier || '',
    tone: model.source === 'stimma_cloud' ? 'cloud' : undefined,
    vendor: resolveModelVendorId(model) || undefined,
  }))
})
const selectedQuickTaskValue = computed(() => (
  quickTaskOptions.value.some(option => option.value === quickTaskModel.value)
    ? quickTaskModel.value
    : ''
))
const voiceModelOptions = computed(() => VOICE_MODELS.map(model => ({
  value: model.id,
  label: model.label,
  description: model.description,
  meta: model.size,
})))

async function saveQuickTaskModel(model) {
  await axios.patch(`${getApiBase()}/settings/quick-task-model`, { model })
  await fetchModels(null, true)
}

async function refreshVoiceModelReady() { voiceModelReady.value = await isModelReady(voiceModel.value) }
watch(voiceModel, refreshVoiceModelReady)
onMounted(async () => { await refreshVoiceModelReady(); await fetchModels(null, true) })
</script>
