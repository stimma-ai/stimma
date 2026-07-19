<template>
  <div class="space-y-6">
    <section>
      <div class="mb-3">
        <div class="flex items-center gap-3">
          <h3 class="text-xs font-semibold text-content-secondary">Preferences</h3>
        </div>
      </div>

      <div class="mt-6 max-w-[680px]">
        <SettingRow label="Theme" description="How Stimma looks on this device.">
          <div class="flex items-center gap-1.5">
            <button
              v-for="option in THEME_OPTIONS"
              :key="option.value"
              @click="selectTheme(option.value)"
              class="flex items-center gap-1.5 px-3 h-8 rounded-md transition-colors duration-150 text-xs font-medium"
              :class="themePreference === option.value
                ? 'bg-accent/10 text-accent-hi'
                : 'text-content-tertiary hover:text-content hover:bg-overlay-subtle'"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" :d="option.icon" />
              </svg>
              {{ option.label }}
            </button>
          </div>
        </SettingRow>

        <SettingRow label="LLM for Quick Tasks" description="Prompt cleanup, chat names, and other background work.">
          <SettingsDropdown
            v-if="quickTaskOptions.length"
            control
            fill
            class="w-72"
            :menu-width="320"
            :model-value="selectedQuickTaskValue"
            :options="quickTaskOptions"
            placeholder="Choose a model"
            @update:model-value="saveQuickTaskModel"
          />
          <span v-else class="w-72 text-right text-[13px] text-content-muted">No models available</span>
        </SettingRow>

        <SettingRow v-if="voiceSupported" label="Voice Input Model">
          <template #description>
            Processed on this device. <span v-if="!voiceModelReady">{{ privacyLockdownActive ? 'Downloads are off during Privacy Lockdown.' : 'Downloads on first use.' }}</span>
          </template>
          <span v-if="voiceModelReady" class="inline-flex items-center gap-1.5 text-[11px] text-content-tertiary">
            <span class="w-2 h-2 rounded-full bg-green-500"></span>
            Ready
          </span>
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
        </SettingRow>
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
import { useTheme } from '../../../composables/useTheme'
import { useSettingsApi } from '../../../composables/useSettingsApi'
import { VOICE_MODELS, voiceModel, isModelReady, supported as voiceSupported } from '../../../composables/useVoiceInput'
import SettingsDropdown from '../../ui/SettingsDropdown.vue'
import SettingRow from '../SettingRow.vue'
import { resolveModelVendorId } from '../../../utils/modelVendors'

const { selectableModels, quickTaskModel, fetchModels } = useAvailableModels()
const { privacyLockdownActive } = usePrivacyLockdown()

// Theme
const { themePreference, setTheme } = useTheme()
const { updateTheme } = useSettingsApi()

const THEME_OPTIONS = [
  { value: 'light', label: 'Light', icon: 'M12 3v2.25m6.364.386l-1.591 1.591M21 12h-2.25m-.386 6.364l-1.591-1.591M12 18.75V21m-4.773-4.227l-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0z' },
  { value: 'dark', label: 'Dark', icon: 'M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z' },
  { value: 'system', label: 'System', icon: 'M9 17.25v1.007a3 3 0 01-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0115 18.257V17.25m6-12V15a2.25 2.25 0 01-2.25 2.25H5.25A2.25 2.25 0 013 15V5.25A2.25 2.25 0 015.25 3h13.5A2.25 2.25 0 0121 5.25z' },
]

function selectTheme(theme) {
  setTheme(theme)
  // Fire-and-forget persist to server
  updateTheme(theme).catch(err => console.error('Failed to persist theme:', err))
}

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
