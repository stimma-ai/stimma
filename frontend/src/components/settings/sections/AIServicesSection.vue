<template>
  <div>
    <div class="flex items-center gap-3 mb-4">
      <h3 class="text-base font-medium text-content">LLM Services</h3>
      <div class="flex items-center gap-1.5 text-xs text-blue-500 bg-blue-500/10 border border-blue-500/30 rounded-full px-2.5 py-1">
        <svg class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="m11.25 11.25.041-.02a.75.75 0 0 1 1.063.852l-.708 2.836a.75.75 0 0 0 1.063.853l.041-.021M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9-3.75h.008v.008H12V8.25Z" />
        </svg>
        <span>Applies to all profiles</span>
      </div>
    </div>

    <!-- Default Model Pickers -->
    <div class="p-4 rounded-lg border border-edge mb-3">
      <div class="flex items-center justify-between gap-4">
        <div class="flex-1 min-w-0">
          <h4 class="text-sm font-medium text-content">Default Chat Model</h4>
          <p class="text-xs text-content-tertiary mt-0.5">Used for new chats unless overridden per-chat or per-project</p>
        </div>
        <select
          :value="defaultModelSelectValue"
          @change="updateDefaultModel($event.target.value)"
          class="w-56 bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500"
        >
          <option
            v-for="model in selectableDefaultModels"
            :key="model.slug"
            :value="model.slug"
            :disabled="model.available === false"
          >
            {{ model.name }}{{ model.available === false && model.source !== 'auto' ? ' · unavailable' : '' }}
          </option>
        </select>
      </div>
      <p v-if="defaultModelStatus" class="mt-3 text-xs flex items-start gap-1.5" :class="defaultModelStatus.available ? 'text-content-tertiary' : 'text-amber-500/80'">
        <svg v-if="!defaultModelStatus.available" class="w-3.5 h-3.5 flex-shrink-0 mt-px" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
        </svg>
        <span>{{ defaultModelStatus.message }}</span>
      </p>
    </div>

    <div class="p-4 rounded-lg border border-edge mb-3">
      <div class="flex items-center justify-between gap-4">
        <div class="flex-1 min-w-0">
          <h4 class="text-sm font-medium text-content">Quick Tasks</h4>
          <p class="text-xs text-content-tertiary mt-0.5">Used for prompt enhancement, the tool assistant, chat naming, and other quick tasks</p>
        </div>
        <select
          :value="utilityModelSource"
          @change="updateUtilityModel($event.target.value)"
          class="w-56 bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500"
        >
          <option value="auto" :disabled="!hasAnyUtilityModel">{{ utilityAutoLabel }}</option>
          <option value="endpoint" :disabled="!hasLocalEndpoint">Local Endpoint{{ !hasLocalEndpoint ? ' · configure first' : '' }}</option>
        </select>
      </div>
      <p v-if="utilityModelStatus" class="mt-3 text-xs flex items-start gap-1.5" :class="utilityModelStatus.available ? 'text-content-tertiary' : 'text-amber-500/80'">
        <svg v-if="!utilityModelStatus.available" class="w-3.5 h-3.5 flex-shrink-0 mt-px" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
        </svg>
        <span>{{ utilityModelStatus.message }}</span>
      </p>
    </div>

    <!-- Voice Input (on-device Whisper) -->
    <div v-if="voiceSupported" class="p-4 rounded-lg border border-edge mb-6">
      <div class="flex items-center justify-between gap-4">
        <div class="flex-1 min-w-0">
          <h4 class="text-sm font-medium text-content">Voice Input</h4>
          <p class="text-xs text-content-tertiary mt-0.5">Audio is processed entirely on your device</p>
        </div>
        <div class="flex items-center gap-2 flex-shrink-0">
          <svg
            v-if="voiceModelReady"
            class="w-4 h-4 text-green-500"
            fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"
            title="Model downloaded"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <select
            :value="voiceModel"
            @change="voiceModel = $event.target.value"
            class="w-52 bg-surface-raised border border-edge rounded px-3 py-1.5 text-sm text-content focus:outline-none focus:border-blue-500"
          >
            <option value="base.en">Whisper Base (142 MB)</option>
            <option value="small.en">Whisper Small (466 MB)</option>
          </select>
        </div>
      </div>
      <p v-if="!voiceModelReady" class="mt-3 text-xs text-content-tertiary">
        Downloads automatically the first time you use voice input.
      </p>
    </div>

    <!-- Local Endpoint -->
    <h4 class="text-sm font-medium text-content mb-1">Local Endpoint</h4>
    <p class="text-xs text-content-tertiary mb-4">
      Use a self-hosted OpenAI-compatible model endpoint. Works with vLLM, LM Studio, OpenRouter, etc.
    </p>

    <div class="p-4 rounded-lg border border-edge">
      <div class="space-y-3">
        <!-- Endpoint URL -->
        <div>
          <label class="block text-xs text-content-tertiary mb-1">Endpoint URL</label>
          <input
            type="text"
            :value="sharedEndpoint.url"
            @input="updateSharedField('url', $event.target.value)"
            @blur="scheduleProbe"
            placeholder="e.g., http://localhost:8000/v1"
            class="w-full bg-surface-raised border border-edge rounded px-3 py-2 text-sm text-content focus:outline-none focus:border-blue-500"
          />
        </div>

        <!-- API Key -->
        <div>
          <label class="block text-xs text-content-tertiary mb-1">API Key (optional)</label>
          <input
            type="text"
            :value="sharedApiKeyDisplay"
            @input="updateSharedField('api_key', $event.target.value)"
            @blur="scheduleProbe"
            placeholder="Leave empty if not required"
            class="w-full bg-surface-raised border border-edge rounded px-3 py-2 text-sm text-content focus:outline-none focus:border-blue-500"
          />
        </div>

        <!-- Model -->
        <div>
          <label class="block text-xs text-content-tertiary mb-1">Model</label>
          <select
            v-if="endpointModels.length"
            :value="sharedEndpoint.model"
            @change="onModelChange($event.target.value)"
            class="w-full bg-surface-raised border border-edge rounded px-3 py-2 text-sm text-content focus:outline-none focus:border-blue-500"
          >
            <option v-for="m in endpointModels" :key="m" :value="m">{{ m }}</option>
          </select>
          <input
            v-else
            type="text"
            :value="sharedEndpoint.model"
            @input="updateSharedField('model', $event.target.value)"
            @blur="scheduleProbe"
            placeholder="e.g., my-model-name"
            class="w-full bg-surface-raised border border-edge rounded px-3 py-2 text-sm text-content focus:outline-none focus:border-blue-500"
          />
          <p v-if="modelsLoading" class="mt-1 flex items-center gap-1.5 text-[11px] text-content-muted">
            <svg class="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
            </svg>
            Loading models…
          </p>
          <p v-else-if="endpointModels.length" class="mt-1 text-[11px] text-content-muted">
            {{ endpointModels.length }} model{{ endpointModels.length === 1 ? '' : 's' }} available
          </p>
        </div>

        <!-- Connection status / auto-test -->
        <div v-if="hasLocalEndpoint" class="rounded-lg border border-edge p-3 space-y-2">
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2 text-xs min-w-0">
              <template v-if="testStatus.testing">
                <svg class="w-3.5 h-3.5 animate-spin text-content-muted" fill="none" viewBox="0 0 24 24">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                  <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                </svg>
                <span class="text-content-secondary">Testing…</span>
              </template>
              <template v-else-if="sharedEndpoint.last_tested_at && sharedEndpoint.last_test_passed">
                <svg class="w-4 h-4 text-green-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span class="font-medium text-content">Ready</span>
                <span class="text-content-muted">· tested {{ lastTestedAgo }}</span>
              </template>
              <template v-else-if="sharedEndpoint.last_tested_at">
                <svg class="w-4 h-4 text-red-500 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9.75 9.75l4.5 4.5m0-4.5l-4.5 4.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span class="text-red-500 truncate" :title="testStatus.error">{{ testStatus.error || 'Last test failed' }}</span>
                <span class="text-content-muted flex-shrink-0">· {{ lastTestedAgo }}</span>
              </template>
              <template v-else>
                <span class="text-content-muted">Not tested yet</span>
              </template>
            </div>
            <button
              @click="runProbe"
              :disabled="testStatus.testing || !sharedEndpoint.url"
              class="text-[11px] text-blue-400 hover:underline disabled:opacity-50 disabled:no-underline flex-shrink-0"
            >{{ sharedEndpoint.last_tested_at ? 'Re-test' : 'Test connection' }}</button>
          </div>

          <!-- capability badges -->
          <div v-if="testStatus.scenarios" class="flex flex-wrap items-center gap-1.5">
            <span
              v-for="(result, name) in testStatus.scenarios"
              :key="name"
              class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md border text-[11px]"
              :class="result.passed ? 'border-green-500/30 text-green-500' : 'border-red-500/30 text-red-500'"
              :title="result.detail || result.error || ''"
            >
              <svg v-if="result.passed" class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
              <svg v-else class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
              {{ name }}
              <span v-if="result.elapsed_ms" class="text-content-muted">({{ fmtMs(result.elapsed_ms) }})</span>
            </span>
          </div>

        </div>

        <!-- Advanced -->
        <div>
          <button
            @click="advancedOpen = !advancedOpen"
            class="flex items-center gap-1.5 text-xs font-medium text-content-secondary"
          >
            <svg class="w-3.5 h-3.5 text-content-muted transition-transform" :class="advancedOpen ? 'rotate-90' : ''" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            Advanced
          </button>

          <div v-if="advancedOpen" class="mt-3 space-y-3">
            <!-- System prompt -->
            <div class="rounded-lg border border-edge p-3 space-y-3">
              <div class="text-xs font-medium text-content">System prompt</div>
              <label class="flex gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  :checked="sharedEndpoint.content_policy_enabled"
                  @change="updateSharedField('content_policy_enabled', $event.target.checked)"
                  class="mt-0.5 accent-blue-500 w-3.5 h-3.5 shrink-0"
                />
                <div class="min-w-0">
                  <div class="text-xs text-content">Include Stimma's Content Policy in the system prompt</div>
                  <div class="text-[11px] text-content-muted mt-0.5 leading-relaxed">
                    When using aligned models, stating a policy typically increases permissiveness and creative control, while improving clarity around refusals.
                  </div>
                </div>
              </label>
              <div>
                <label class="block text-[11px] text-content-tertiary mb-1">Additional instructions</label>
                <textarea
                  :value="sharedEndpoint.extra_system_prompt"
                  @input="updateSharedField('extra_system_prompt', $event.target.value)"
                  rows="3"
                  placeholder="Appended to the system prompt for every request."
                  class="w-full bg-surface-raised border border-edge rounded px-2.5 py-2 text-[11px] text-content focus:outline-none focus:border-blue-500"
                ></textarea>
              </div>
            </div>

            <!-- Reasoning control -->
            <div class="rounded-lg border border-edge p-3">
              <div class="flex items-center justify-between gap-3">
                <div class="min-w-0">
                  <div class="text-xs font-medium text-content">Reasoning control</div>
                  <div class="text-[11px] text-content-muted mt-0.5">How thinking is toggled per request.</div>
                </div>
                <div class="inline-flex rounded-md border border-edge overflow-hidden text-[11px] shrink-0 self-start">
                  <button @click="setReasoningSource('auto')" class="px-2 py-1" :class="reasoningManual ? 'text-content-tertiary' : 'bg-blue-500/15 text-blue-400'">Auto</button>
                  <button @click="setReasoningSource('manual')" class="px-2 py-1" :class="reasoningManual ? 'bg-blue-500/15 text-blue-400' : 'text-content-tertiary'">Manual</button>
                </div>
              </div>
              <div class="mt-2">
                <div v-if="!reasoningManual" class="text-[11px] text-content-tertiary">
                  <span class="text-content-muted">Method</span> <span class="font-medium">{{ sharedEndpoint.reasoning_method || 'none' }}</span>
                </div>
                <div v-else class="relative max-w-[280px]">
                  <select
                    :value="sharedEndpoint.reasoning_method || 'none'"
                    @change="onReasoningMethodChange($event.target.value)"
                    class="w-full bg-surface-raised border border-edge rounded px-2.5 py-1.5 text-xs text-content focus:outline-none focus:border-blue-500"
                  >
                    <option value="reasoning_effort">reasoning_effort</option>
                    <option value="openrouter">reasoning (OpenRouter)</option>
                    <option value="enable_thinking">enable_thinking</option>
                    <option value="think">think (Ollama)</option>
                    <option value="reasoning_budget">reasoning_budget (llama.cpp)</option>
                    <option value="none">Always on — no control</option>
                  </select>
                </div>
              </div>
            </div>

            <!-- Context window -->
            <div class="rounded-lg border border-edge p-3">
              <div class="flex items-baseline justify-between mb-1">
                <label class="block text-xs font-medium text-content">Context window</label>
                <span class="text-xs text-content-secondary tabular-nums">{{ contextWindowLabel }}</span>
              </div>
              <input
                type="range"
                min="32768"
                max="262144"
                step="32768"
                :value="sharedEndpoint.max_context_tokens"
                @input="updateSharedField('max_context_tokens', Number($event.target.value))"
                class="w-full accent-blue-500"
              />
              <p class="mt-1 text-[11px] text-content-muted">
                Match your model's configured context length. Stimma compacts history at ~80% of this.
              </p>
            </div>

            <!-- Extra request body -->
            <div class="rounded-lg border border-edge p-3">
              <div class="text-xs font-medium text-content">Extra request body</div>
              <div class="text-[11px] text-content-muted mt-0.5 mb-2">Merged into every request.</div>
              <textarea
                :value="extraBodyText"
                @input="onExtraBodyInput($event.target.value)"
                rows="3"
                placeholder='{ "repetition_penalty": 1.05 }'
                class="w-full bg-surface-raised border border-edge rounded px-2.5 py-2 text-[11px] font-mono text-content focus:outline-none focus:border-blue-500"
              ></textarea>
              <p v-if="extraBodyError" class="mt-1 text-[11px] text-red-400">{{ extraBodyError }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="saving" class="mt-4 text-xs text-content-muted">Saving...</div>
  </div>
</template>

<script setup>
import { ref, watch, computed, onMounted } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../../apiConfig'
import { useAvailableModels } from '../../../composables/useAvailableModels'
import { voiceModel, isModelReady, supported as voiceSupported } from '../../../composables/useVoiceInput'

const props = defineProps({
  llmSettings: {
    type: Array,
    default: () => []
  },
})

const emit = defineEmits(['update'])

// --- Voice input model (on-device Whisper) ---
const voiceModelReady = ref(false)
async function refreshVoiceModelReady() {
  voiceModelReady.value = await isModelReady(voiceModel.value)
}
onMounted(refreshVoiceModelReady)
watch(voiceModel, refreshVoiceModelReady)

// --- Available models (for chat dropdown) ---
const { models: availableModelsRaw, globalDefault, fetchModels, invalidateCache } = useAvailableModels()
const defaultModelSlug = ref('auto')
const availableModelsList = computed(() => {
  if (availableModelsRaw.value.length > 0) return availableModelsRaw.value
  return [{
    slug: 'auto',
    name: 'Set up AI models',
    source: 'auto',
    available: false,
    description: 'Sign in to Stimma Cloud or configure a local endpoint in Settings > Advanced.',
  }]
})
const autoDefaultModel = computed(() => availableModelsList.value.find(m => m.slug === 'auto'))
const selectableDefaultModels = computed(() => {
  const explicitModels = availableModelsList.value.filter(m => m.source !== 'auto')
  if (defaultModelSlug.value === 'auto' && autoDefaultModel.value && !autoDefaultModel.value.resolved_slug) {
    return [autoDefaultModel.value, ...explicitModels]
  }
  return explicitModels.length > 0 ? explicitModels : availableModelsList.value
})
const defaultModelSelectValue = computed(() => {
  if (defaultModelSlug.value === 'auto' && autoDefaultModel.value?.resolved_slug) {
    return autoDefaultModel.value.resolved_slug
  }
  return defaultModelSlug.value
})
const selectedDefaultModel = computed(() => {
  return selectableDefaultModels.value.find(m => m.slug === defaultModelSelectValue.value)
    || availableModelsList.value.find(m => m.slug === defaultModelSlug.value)
})
const defaultModelStatus = computed(() => {
  if (!selectedDefaultModel.value) return null
  if (selectedDefaultModel.value.available === false) {
    return {
      available: false,
      message: selectedDefaultModel.value.description || 'The saved default model is not available right now.',
    }
  }
  return null
})

// --- Shared local endpoint state ---
const sharedEndpoint = ref({
  url: '', model: '', api_key_set: false, max_context_tokens: 131072,
  content_policy_enabled: true, extra_system_prompt: '', extra_body: null,
  reasoning_method: null, reasoning_method_source: 'auto',
  detected_runtime: null, reasoning_mode: null, reasoning_output: null,
  last_tested_at: null, last_test_passed: null,
})
const editedSharedKey = ref(undefined)  // tracks unsaved key input

// Models advertised by the endpoint's /models route (drives the dropdown).
const endpointModels = ref([])
const modelsLoading = ref(false)

// Advanced section UI state
const advancedOpen = ref(false)
const extraBodyText = ref('')
const extraBodyError = ref('')

const contextWindowLabel = computed(() => {
  const k = Math.round((sharedEndpoint.value.max_context_tokens || 0) / 1024)
  return `${k}k tokens`
})

const reasoningManual = computed(() => sharedEndpoint.value.reasoning_method_source === 'manual')

function fmtMs(ms) {
  return ms > 999 ? (ms / 1000).toFixed(1) + 's' : ms + 'ms'
}

function timeAgo(iso) {
  if (!iso) return ''
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

const lastTestedAgo = computed(() => timeAgo(sharedEndpoint.value.last_tested_at))

const hasLocalEndpoint = computed(() => !!sharedEndpoint.value.url)
const hasCloudAvailable = computed(() => availableModelsRaw.value.some(m => m.source === 'stimma_cloud' && m.available !== false))
const hasAnyUtilityModel = computed(() => hasCloudAvailable.value || hasLocalEndpoint.value)
const utilityAutoLabel = computed(() => {
  if (hasCloudAvailable.value) return 'Auto: Stimma Cloud'
  if (hasLocalEndpoint.value) return 'Auto: Local Endpoint'
  return 'Auto · unavailable'
})

const sharedApiKeyDisplay = computed(() => {
  if (editedSharedKey.value !== undefined) return editedSharedKey.value
  if (sharedEndpoint.value.api_key_set) return '••••••••••••••••'
  return ''
})

// --- Utility model source ---
const utilityModelSource = ref('auto')
const utilityModelStatus = computed(() => {
  if (utilityModelSource.value === 'endpoint' && !hasLocalEndpoint.value) {
    return { available: false, message: 'Configure a local endpoint before using it for quick tasks.' }
  }
  if (utilityModelSource.value === 'auto') {
    if (hasCloudAvailable.value) return { available: true, message: 'Auto uses a fast Stimma Cloud model.' }
    if (hasLocalEndpoint.value) return { available: true, message: 'Auto uses your local endpoint.' }
    return { available: false, message: 'No quick-task model is available. Sign in to Stimma Cloud or configure a local endpoint.' }
  }
  return null
})

// --- Misc ---
const saving = ref(false)
const testStatus = ref({ testing: false, done: false, success: null, error: null, scenarios: null })

let saveTimer = null
let initialLoadDone = false

// --- Load settings ---
watch(() => props.llmSettings, (newSettings) => {
  if (initialLoadDone) return

  const settingsMap = new Map(newSettings.map(s => [s.role, s]))
  const agentCfg = settingsMap.get('agent')
  const fastCfg = settingsMap.get('agent-fast')

  const ep = agentCfg?.endpoint || {}
  sharedEndpoint.value = {
    url: ep.url || '',
    model: ep.model || '',
    api_key_set: ep.api_key_set || false,
    max_context_tokens: ep.max_context_tokens || 131072,
    content_policy_enabled: ep.content_policy_enabled !== false,
    extra_system_prompt: ep.extra_system_prompt || '',
    extra_body: ep.extra_body || null,
    reasoning_method: ep.reasoning_method || null,
    reasoning_method_source: ep.reasoning_method_source || 'auto',
    detected_runtime: ep.detected_runtime || null,
    reasoning_mode: ep.reasoning_mode || null,
    reasoning_output: ep.reasoning_output || null,
    last_tested_at: ep.last_tested_at || null,
    last_test_passed: ep.last_test_passed ?? null,
  }
  extraBodyText.value = ep.extra_body ? JSON.stringify(ep.extra_body, null, 2) : ''
  // 'stimma_cloud' was a selectable pin before Quick Tasks became a two-option
  // routing choice; auto prefers cloud, so legacy configs display as auto.
  const fastSource = fastCfg?.source || 'auto'
  utilityModelSource.value = fastSource === 'stimma_cloud' ? 'auto' : fastSource

  initialLoadDone = true
  if (sharedEndpoint.value.url) fetchEndpointModels()
}, { immediate: true })

onMounted(async () => {
  await fetchModels(null, true)
  defaultModelSlug.value = globalDefault.value
})

// --- Chat model dropdown ---
async function updateDefaultModel(slug) {
  defaultModelSlug.value = slug
  try {
    await axios.patch(`${getApiBase()}/settings/default-model`, { default_model: slug })
    invalidateCache()
  } catch (err) {
    console.error('Failed to update default model:', err)
  }
}

// --- Utility model dropdown ---
async function updateUtilityModel(source) {
  utilityModelSource.value = source
  try {
    await emit('update', { role: 'agent-fast', data: { source } })
  } catch (err) {
    console.error('Failed to update utility model:', err)
  }
}

// --- Local endpoint form ---
function updateSharedField(field, value) {
  if (field === 'api_key') {
    editedSharedKey.value = value
  } else {
    sharedEndpoint.value[field] = value
  }
  // Editing the connection invalidates the prior tested state.
  if (field === 'url' || field === 'model' || field === 'api_key') {
    sharedEndpoint.value.last_tested_at = null
    sharedEndpoint.value.last_test_passed = null
  }
  debouncedSaveShared()
}

// Fetch the models the endpoint advertises (server-side, to dodge CORS) and
// populate the dropdown. If the saved model isn't offered, fall back to the
// first one — in the common single-model case this is a non-event.
async function fetchEndpointModels() {
  const url = (sharedEndpoint.value.url || '').trim()
  if (!url) {
    endpointModels.value = []
    return false
  }
  modelsLoading.value = true
  try {
    const body = { url }
    if (editedSharedKey.value !== undefined) body.api_key = editedSharedKey.value
    const { data } = await axios.post(`${getApiBase()}/settings/llms/endpoint/models`, body)
    const models = data?.models || []
    endpointModels.value = models
    // Fall back to the first model when the saved one isn't offered. Set directly
    // (runProbe persists afterward) so we don't kick off a competing save timer.
    if (models.length && !models.includes(sharedEndpoint.value.model)) {
      sharedEndpoint.value.model = models[0]
      return true
    }
  } catch (err) {
    endpointModels.value = []
  } finally {
    modelsLoading.value = false
  }
  return false
}

// Single sequenced pipeline for any URL / key / model change: persist → fetch
// models → test. A monotonic token ensures only the latest run touches the UI,
// so rapid edits / field blurs can't overlap and flicker.
let connTimer = null
let probeSeq = 0

function scheduleProbe() {
  clearTimeout(connTimer)
  connTimer = setTimeout(runProbe, 800)
}

async function runProbe() {
  clearTimeout(connTimer)
  clearTimeout(saveTimer)  // we save synchronously below
  const seq = ++probeSeq
  if (!sharedEndpoint.value.url) {
    testStatus.value = { testing: false, done: false, success: null, error: null, scenarios: null }
    return
  }
  testStatus.value = { testing: true, done: false, success: null, error: null, scenarios: null }
  // 1. Persist first — the backend test reads the saved endpoint config.
  await saveShared()
  if (seq !== probeSeq) return
  // 2. Populate the model dropdown; persist again if we picked a default.
  const changed = await fetchEndpointModels()
  if (seq !== probeSeq) return
  if (changed) { await saveShared(); if (seq !== probeSeq) return }
  if (!sharedEndpoint.value.model) {
    testStatus.value = { testing: false, done: true, success: false, error: 'No model available at this endpoint', scenarios: null }
    return
  }
  // 3. Test.
  await runTest(seq)
}

function onModelChange(value) {
  sharedEndpoint.value.model = value
  sharedEndpoint.value.last_tested_at = null
  sharedEndpoint.value.last_test_passed = null
  scheduleProbe()
}

// --- Reasoning control ---
// Reasoning method is owned by the backend profiler in 'auto' mode, so it's
// saved explicitly (not via the general debounced save) to avoid clobbering
// freshly-detected values. Manual selections stick and aren't re-detected.
function setReasoningSource(source) {
  sharedEndpoint.value.reasoning_method_source = source
  if (source === 'manual' && !sharedEndpoint.value.reasoning_method) {
    sharedEndpoint.value.reasoning_method = 'reasoning_effort'
  }
  saveReasoning()
  // Switching back to auto re-detects on the next test.
  if (source === 'auto' && sharedEndpoint.value.url) runProbe()
}

function onReasoningMethodChange(value) {
  sharedEndpoint.value.reasoning_method = value
  sharedEndpoint.value.reasoning_method_source = 'manual'
  saveReasoning()
}

async function saveReasoning() {
  const data = {
    endpoint_reasoning_method: sharedEndpoint.value.reasoning_method || '',
    endpoint_reasoning_method_source: sharedEndpoint.value.reasoning_method_source || 'auto',
  }
  try {
    await emit('update', { role: 'agent', data })
    await emit('update', { role: 'agent-fast', data })
  } catch (e) {
    console.error('Failed to save reasoning control:', e)
  }
}

// --- Extra request body (validated JSON) ---
function onExtraBodyInput(text) {
  extraBodyText.value = text
  const trimmed = text.trim()
  if (!trimmed) {
    extraBodyError.value = ''
    sharedEndpoint.value.extra_body = null
    debouncedSaveShared()
    return
  }
  try {
    const parsed = JSON.parse(trimmed)
    if (typeof parsed !== 'object' || Array.isArray(parsed)) {
      extraBodyError.value = 'Must be a JSON object'
      return
    }
    extraBodyError.value = ''
    sharedEndpoint.value.extra_body = parsed
    debouncedSaveShared()
  } catch (e) {
    extraBodyError.value = 'Invalid JSON'
  }
}

async function saveShared() {
  saving.value = true
  try {
    const payload = {
      endpoint_url: sharedEndpoint.value.url || '',
      endpoint_model: sharedEndpoint.value.model || '',
      endpoint_max_context_tokens: sharedEndpoint.value.max_context_tokens || 131072,
      endpoint_content_policy_enabled: sharedEndpoint.value.content_policy_enabled,
      endpoint_extra_system_prompt: sharedEndpoint.value.extra_system_prompt || '',
      endpoint_extra_body: sharedEndpoint.value.extra_body || {},
    }
    if (editedSharedKey.value !== undefined) {
      payload.endpoint_api_key = editedSharedKey.value
    }

    // Save to both roles — endpoint fields only, don't touch source
    await emit('update', { role: 'agent', data: payload })
    await emit('update', { role: 'agent-fast', data: payload })
    invalidateCache()
    await fetchModels(null, true)

    // If we cleared the URL, reset utility model to auto to avoid dead state
    if (!sharedEndpoint.value.url && utilityModelSource.value === 'endpoint') {
      await updateUtilityModel('auto')
    }
  } finally {
    saving.value = false
  }
}

function debouncedSaveShared() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(saveShared, 500)
}

// --- Test (called only from runProbe, which has already saved + chosen a model) ---
async function runTest(seq) {
  try {
    const { data } = await axios.post(`${getApiBase()}/settings/llms/agent/test`)
    if (seq !== probeSeq) return  // superseded by a newer probe
    testStatus.value = {
      testing: false,
      done: true,
      success: data.success,
      error: data.error,
      scenarios: data.scenarios,
    }
    // Backend persisted the tested timestamp; mirror it locally so the status
    // line shows "tested just now" without a reload.
    sharedEndpoint.value.last_tested_at = new Date().toISOString()
    sharedEndpoint.value.last_test_passed = data.success
    // Reflect what the profiler learned (backend already persisted it). Don't
    // override a manual reasoning method.
    if (data.detected) {
      const d = data.detected
      sharedEndpoint.value.detected_runtime = d.runtime
      sharedEndpoint.value.reasoning_mode = d.reasoning_mode
      sharedEndpoint.value.reasoning_output = d.reasoning_output
      if (sharedEndpoint.value.reasoning_method_source !== 'manual') {
        sharedEndpoint.value.reasoning_method = d.reasoning_method
      }
    }
  } catch (err) {
    if (seq !== probeSeq) return
    testStatus.value = {
      testing: false,
      done: true,
      success: false,
      error: err.response?.data?.detail || err.message || 'Connection test failed',
      scenarios: null,
    }
    sharedEndpoint.value.last_tested_at = new Date().toISOString()
    sharedEndpoint.value.last_test_passed = false
  }
}

</script>
