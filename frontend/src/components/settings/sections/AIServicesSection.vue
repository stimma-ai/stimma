<template>
  <div class="space-y-6">
    <div>
      <h3 class="text-base font-medium text-content">AI Services</h3>
      <p class="mt-1 text-xs text-content-tertiary">Use Stimma Cloud, your own API key, or a local LLM server.</p>
    </div>

    <section class="rounded-lg border border-edge p-4">
      <div class="flex items-center justify-between gap-4">
        <div class="min-w-0">
          <h4 class="text-sm font-medium text-content">Quick tasks</h4>
          <p class="mt-0.5 text-xs text-content-tertiary">Prompt cleanup, chat names, and other background work.</p>
        </div>
        <div>
          <select
            :value="quickTaskModel"
            @change="saveQuickTaskModel($event.target.value)"
            class="w-64 rounded border border-edge bg-surface-raised px-3 py-1.5 text-sm text-content focus:border-blue-500 focus:outline-none"
          >
            <option v-for="model in selectableModels" :key="model.slug" :value="model.slug" :disabled="model.available === false">
              {{ model.name }} · {{ providerLabel(model) }}{{ model.cost_tier ? ` · ${model.cost_tier}` : '' }}
            </option>
          </select>
          <p v-if="selectedQuickModel?.available === false" class="mt-1 text-xs text-red-400">Unavailable. Choose another model.</p>
        </div>
      </div>
    </section>

    <section v-if="voiceSupported" class="rounded-lg border border-edge p-4">
      <div class="flex items-center justify-between gap-4">
        <div class="min-w-0">
          <h4 class="text-sm font-medium text-content">Voice input</h4>
          <p class="mt-0.5 text-xs text-content-tertiary">Processed on this device.</p>
        </div>
        <div class="flex items-center gap-2">
          <svg v-if="voiceModelReady" class="h-4 w-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75 11.25 15 15 9.75M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
          </svg>
          <select v-model="voiceModel" class="w-52 rounded border border-edge bg-surface-raised px-3 py-1.5 text-sm text-content focus:border-blue-500 focus:outline-none">
            <option v-for="model in VOICE_MODELS" :key="model.id" :value="model.id">{{ model.label }} · {{ model.size }}</option>
          </select>
        </div>
      </div>
      <p v-if="!voiceModelReady && privacyLockdownActive" class="mt-3 text-xs text-content-secondary">Downloads are off during Privacy Lockdown.</p>
      <p v-else-if="!voiceModelReady" class="mt-3 text-xs text-content-tertiary">Downloads on first use.</p>
    </section>

    <section>
      <div class="mb-3 flex items-center justify-between gap-3">
        <h4 class="text-sm font-medium text-content">Your services</h4>
        <button @click="refreshAll" class="text-xs text-blue-400 hover:text-blue-300">Refresh</button>
      </div>

      <div class="grid gap-3 lg:grid-cols-2">
        <div class="rounded-lg bg-gradient-to-r from-teal-600/40 via-cyan-500/40 to-indigo-500/40 p-[1px]">
          <div class="h-full rounded-[7px] bg-surface p-4">
            <div class="flex items-start justify-between gap-3">
              <div>
                <div class="stimma-cloud-text text-sm font-medium">Stimma Cloud</div>
                <p class="mt-1 text-xs text-content-tertiary">{{ cloudModels.length }} models · billed through Stimma</p>
              </div>
              <span class="rounded-full px-2 py-0.5 text-[11px]" :class="cloudStatus === 'available' ? 'bg-green-500/10 text-green-500' : 'bg-white/[0.05] text-content-muted'">
                {{ cloudStatus === 'available' ? 'Ready' : 'Unavailable' }}
              </span>
            </div>
            <button type="button" @click="cloudOpen = !cloudOpen" class="mt-4 text-xs text-blue-400 hover:text-blue-300">
              {{ cloudOpen ? 'Hide models' : 'View models' }}
            </button>
            <div v-if="cloudOpen" class="mt-3 divide-y divide-edge border-t border-edge">
              <div v-for="model in cloudModels" :key="model.slug" class="flex items-center justify-between gap-3 py-2 text-xs">
                <div class="min-w-0">
                  <div class="truncate text-content-secondary">{{ model.name }}</div>
                  <div v-if="model.input_modalities?.length" class="mt-0.5 text-[11px] text-content-muted">{{ model.input_modalities.includes('image') ? 'Text and images' : 'Text' }}</div>
                </div>
                <span class="shrink-0 text-content-tertiary">{{ model.cost_tier || '—' }}</span>
              </div>
            </div>
          </div>
        </div>

        <div v-for="provider in providers" :key="provider.id" class="rounded-lg border border-edge p-4">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="truncate text-sm font-medium text-content">{{ provider.name }}</div>
              <p class="mt-1 text-xs text-content-tertiary">{{ provider.models.length }} model{{ provider.models.length === 1 ? '' : 's' }} · {{ kindLabel(provider.kind) }}</p>
            </div>
            <span class="rounded-full px-2 py-0.5 text-[11px]" :class="provider.last_test_passed === false ? 'bg-red-500/10 text-red-500' : 'bg-green-500/10 text-green-500'">
              {{ provider.last_test_passed === false ? 'Check failed' : 'Ready' }}
            </span>
          </div>
          <p v-if="provider.last_error" class="mt-2 text-xs text-red-400">{{ provider.last_error }}</p>
          <div class="mt-4 flex items-center gap-3">
            <button @click="manage(provider)" class="text-xs text-blue-400 hover:text-blue-300">Manage</button>
            <button @click="testProvider(provider)" :disabled="testingId === provider.id" class="text-xs text-content-secondary hover:text-content disabled:opacity-50">
              {{ testingId === provider.id ? 'Checking…' : 'Test' }}
            </button>
            <button @click="removeProvider(provider)" class="ml-auto text-content-muted hover:text-red-500" :aria-label="`Delete ${provider.name}`">
              <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673A2.25 2.25 0 0 1 15.916 21H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0V4.477c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </section>

    <section>
      <h4 class="mb-3 text-sm font-medium text-content">Add a service</h4>
      <div class="flex flex-wrap gap-2">
        <button v-for="kind in providerKinds" :key="kind.id" @click="beginAdd(kind.id)" class="rounded-lg border border-edge bg-white/[0.05] px-3 py-2 text-sm text-content-secondary hover:border-blue-500/50 hover:text-content">
          {{ kind.name }}
        </button>
      </div>

      <div v-if="draft" class="mt-3 rounded-lg border border-blue-500/50 bg-blue-500/10 p-4">
        <div class="flex items-center justify-between">
          <h5 class="text-sm font-medium text-content">Add {{ kindLabel(draft.kind) }}</h5>
          <button @click="draft = null" class="text-xs text-content-muted hover:text-content">Cancel</button>
        </div>
        <div class="mt-4 space-y-3">
          <label v-if="draft.kind === 'local'" class="block">
            <span class="mb-1 block text-xs text-content-tertiary">Server URL</span>
            <input v-model="draft.base_url" class="w-full rounded border border-edge bg-surface px-3 py-2 text-sm text-content focus:border-blue-500 focus:outline-none" placeholder="http://localhost:1234/v1" />
          </label>
          <label v-if="draft.kind !== 'local'" class="block">
            <span class="mb-1 block text-xs text-content-tertiary">API key</span>
            <input v-model="draft.api_key" type="password" autocomplete="off" class="w-full rounded border border-edge bg-surface px-3 py-2 text-sm text-content focus:border-blue-500 focus:outline-none" placeholder="Paste API key" />
          </label>
          <p v-if="draftError" class="text-xs text-red-400">{{ draftError }}</p>
          <button @click="addProvider" :disabled="saving" class="rounded bg-blue-500 px-3 py-2 text-sm font-medium text-white hover:bg-blue-400 disabled:opacity-50">
            {{ saving ? 'Checking…' : 'Check and add' }}
          </button>
        </div>
      </div>
    </section>

    <section v-if="activeProvider" class="rounded-lg border border-edge p-4">
      <div class="flex items-center justify-between">
        <div>
          <h4 class="text-sm font-medium text-content">{{ activeProvider.name }}</h4>
          <p class="mt-0.5 text-xs text-content-tertiary">{{ activeProvider.base_url }}</p>
        </div>
        <button @click="activeProvider = null" class="text-xs text-content-muted hover:text-content">Done</button>
      </div>

      <div class="mt-4 grid gap-3 border-t border-edge pt-4 sm:grid-cols-2">
        <label class="block">
          <span class="mb-1 block text-[11px] text-content-tertiary">Name</span>
          <input v-model="activeProvider.name" class="w-full rounded border border-edge bg-surface-raised px-2 py-1.5 text-xs text-content focus:border-blue-500 focus:outline-none" />
        </label>
        <label class="block">
          <span class="mb-1 block text-[11px] text-content-tertiary">Server URL</span>
          <input v-model="activeProvider.base_url" class="w-full rounded border border-edge bg-surface-raised px-2 py-1.5 text-xs text-content focus:border-blue-500 focus:outline-none" />
        </label>
        <label v-if="activeProvider.kind !== 'local'" class="block sm:col-span-2">
          <span class="mb-1 block text-[11px] text-content-tertiary">Replace API key</span>
          <input v-model="providerKeyDraft" type="password" autocomplete="off" class="w-full rounded border border-edge bg-surface-raised px-2 py-1.5 text-xs text-content focus:border-blue-500 focus:outline-none" placeholder="Leave blank to keep the current key" />
        </label>
        <div class="sm:col-span-2">
          <p v-if="providerSaveError" class="mb-2 text-xs text-red-400">{{ providerSaveError }}</p>
          <button @click="saveProviderConnection" :disabled="savingProvider" class="rounded bg-blue-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-400 disabled:opacity-50">{{ savingProvider ? 'Checking…' : 'Save and check' }}</button>
        </div>
      </div>

      <div class="mt-4 border-t border-edge pt-4">
        <div class="mb-2 flex items-center justify-between">
          <h5 class="text-xs font-medium text-content-secondary">Models</h5>
          <button v-if="isDiscoverable(activeProvider)" @click="loadProviderModels(activeProvider)" class="text-xs text-blue-400">Refresh list</button>
        </div>
        <div class="space-y-2">
          <label v-for="model in managerModels" :key="model.id" class="flex items-center gap-3 rounded border border-edge px-3 py-2">
            <input v-if="isDiscoverable(activeProvider)" type="checkbox" :checked="selectedManagerIds.has(managerModelId(model))" @change="toggleManagerModel(managerModelId(model))" class="rounded border-edge bg-surface" />
            <div class="min-w-0 flex-1">
              <div class="truncate text-sm text-content">{{ model.name || model.id }}</div>
              <div v-if="model.reasoning?.levels?.length" class="mt-0.5 text-[11px] text-content-muted">Reasoning: {{ model.reasoning.levels.join(', ') }}</div>
            </div>
          </label>
        </div>
        <button v-if="isDiscoverable(activeProvider) && discoveredModels.length" @click="saveProviderModels" class="mt-3 rounded bg-blue-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-400">Save models</button>
      </div>

      <div v-if="isDiscoverable(activeProvider) && activeProvider.models.length" class="mt-4 border-t border-edge pt-4">
        <h5 class="mb-2 text-xs font-medium text-content-secondary">Model settings</h5>
        <div class="space-y-2">
          <div v-for="model in activeProvider.models" :key="model.id" class="rounded border border-edge">
            <button type="button" @click="customizingModelId = customizingModelId === model.id ? null : model.id" class="flex w-full items-center justify-between px-3 py-2 text-left">
              <span class="truncate text-sm text-content">{{ model.name }}</span>
              <span class="text-[11px] text-content-muted">{{ customizingModelId === model.id ? 'Hide' : 'Customize' }}</span>
            </button>
            <div v-if="customizingModelId === model.id" class="space-y-3 border-t border-edge p-3">
              <div class="grid gap-3 sm:grid-cols-2">
                <label class="block">
                  <span class="mb-1 block text-[11px] text-content-tertiary">Display name</span>
                  <input v-model="model.name" class="w-full rounded border border-edge bg-surface-raised px-2 py-1.5 text-xs text-content focus:border-blue-500 focus:outline-none" />
                </label>
                <label class="block">
                  <span class="mb-1 block text-[11px] text-content-tertiary">Context window</span>
                  <input v-model.number="model.max_context_tokens" type="number" min="1024" step="1024" class="w-full rounded border border-edge bg-surface-raised px-2 py-1.5 text-xs text-content focus:border-blue-500 focus:outline-none" />
                </label>
              </div>
              <label class="flex items-center gap-2 text-xs text-content-secondary">
                <input v-model="model.supports_tools" type="checkbox" class="rounded border-edge bg-surface" />
                Tool calls
              </label>
              <div class="grid gap-3 sm:grid-cols-2">
                <label class="block">
                  <span class="mb-1 block text-[11px] text-content-tertiary">Reasoning</span>
                  <select v-model="model.reasoning.mode" class="w-full rounded border border-edge bg-surface-raised px-2 py-1.5 text-xs text-content" @change="normalizeReasoning(model)">
                    <option value="none">None</option>
                    <option value="optional">Optional</option>
                    <option value="required">Always on</option>
                  </select>
                </label>
                <label class="block">
                  <span class="mb-1 block text-[11px] text-content-tertiary">Request control</span>
                  <select v-model="model.reasoning.control" class="w-full rounded border border-edge bg-surface-raised px-2 py-1.5 text-xs text-content" @change="normalizeReasoning(model)">
                    <option value="none">None</option>
                    <option value="openai_effort">reasoning_effort</option>
                    <option value="openrouter_effort">OpenRouter reasoning</option>
                    <option value="fireworks_effort">Fireworks reasoning_effort</option>
                    <option value="enable_thinking">enable_thinking</option>
                    <option value="think">think</option>
                    <option value="reasoning_budget">reasoning_budget</option>
                  </select>
                </label>
              </div>
              <label v-if="model.reasoning.mode !== 'none'" class="block">
                <span class="mb-1 block text-[11px] text-content-tertiary">Levels</span>
                <input :value="model.reasoning.levels.join(', ')" @change="setReasoningLevels(model, $event.target.value)" class="w-full rounded border border-edge bg-surface-raised px-2 py-1.5 text-xs text-content focus:border-blue-500 focus:outline-none" placeholder="off, low, medium, high" />
              </label>
              <div v-if="model.reasoning.mode !== 'none'" class="grid gap-3 sm:grid-cols-2">
                <label class="block">
                  <span class="mb-1 block text-[11px] text-content-tertiary">Chat default</span>
                  <select v-model="model.reasoning.default" class="w-full rounded border border-edge bg-surface-raised px-2 py-1.5 text-xs text-content">
                    <option v-for="level in model.reasoning.levels" :key="level" :value="level">{{ level }}</option>
                  </select>
                </label>
                <div>
                  <span class="mb-1 block text-[11px] text-content-tertiary">Quick tasks</span>
                  <div class="rounded border border-edge bg-white/[0.05] px-2 py-1.5 text-xs text-content-muted">{{ model.reasoning.levels[0] }}</div>
                </div>
              </div>
              <label class="block">
                <span class="mb-1 block text-[11px] text-content-tertiary">Extra request body · JSON</span>
                <textarea :value="extraBodyText(model)" @input="setExtraBody(model, $event.target.value)" rows="3" class="w-full rounded border border-edge bg-surface-raised px-2 py-1.5 font-mono text-xs text-content focus:border-blue-500 focus:outline-none" placeholder="{}" />
                <span v-if="extraBodyErrors[model.id]" class="mt-1 block text-[11px] text-red-400">Invalid JSON</span>
              </label>
              <button @click="saveProviderDetails" :disabled="Boolean(extraBodyErrors[model.id])" class="rounded bg-blue-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-400 disabled:opacity-50">Save</button>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="rounded-lg border border-edge p-4">
      <button @click="promptOpen = !promptOpen" class="flex w-full items-center justify-between text-left">
        <span class="text-sm font-medium text-content">Prompt policy</span>
        <span class="text-xs text-content-muted">{{ promptOpen ? 'Hide' : 'Customize' }}</span>
      </button>
      <div v-if="promptOpen" class="mt-4 space-y-3">
        <label class="flex items-start gap-2 text-sm text-content-secondary">
          <input v-model="contentPolicy" value="stimma" type="radio" class="mt-0.5" />
          <span><span class="text-content">Stimma policy</span><span class="block text-xs text-content-tertiary">Use the same policy prompt across your providers.</span></span>
        </label>
        <label class="flex items-start gap-2 text-sm text-content-secondary">
          <input v-model="contentPolicy" value="provider" type="radio" class="mt-0.5" />
          <span><span class="text-content">Provider default</span><span class="block text-xs text-content-tertiary">Do not add Stimma's policy prompt.</span></span>
        </label>
        <label class="block">
          <span class="mb-1 block text-xs text-content-tertiary">Additional system prompt</span>
          <textarea v-model="extraSystemPrompt" rows="3" class="w-full rounded border border-edge bg-surface-raised px-3 py-2 text-sm text-content focus:border-blue-500 focus:outline-none" />
        </label>
        <button @click="savePromptPolicy" class="rounded bg-blue-500 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-400">Save</button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../../apiConfig'
import { useAvailableModels } from '../../../composables/useAvailableModels'
import { VOICE_MODELS, voiceModel, isModelReady, supported as voiceSupported } from '../../../composables/useVoiceInput'
import { usePrivacyLockdown } from '../../../composables/usePrivacyLockdown'

const props = defineProps({ llmSettings: { type: Array, default: () => [] } })
const emit = defineEmits(['update'])

const providerKinds = [
  { id: 'openai', name: 'OpenAI' },
  { id: 'anthropic', name: 'Anthropic' },
  { id: 'xai', name: 'xAI' },
  { id: 'openrouter', name: 'OpenRouter' },
  { id: 'local', name: 'Local LLM' },
]
const { models, quickTaskModel, cloudStatus, fetchModels, invalidateCache } = useAvailableModels()
const { privacyLockdownActive } = usePrivacyLockdown()
const voiceModelReady = ref(false)
const providers = ref([])
const draft = ref(null)
const draftError = ref('')
const saving = ref(false)
const testingId = ref(null)
const activeProvider = ref(null)
const discoveredModels = ref([])
const selectedManagerIds = ref(new Set())
const cloudOpen = ref(false)
const promptOpen = ref(false)
const contentPolicy = ref('stimma')
const extraSystemPrompt = ref('')
const customizingModelId = ref(null)
const extraBodyDrafts = ref({})
const extraBodyErrors = ref({})
const providerKeyDraft = ref('')
const providerSaveError = ref('')
const savingProvider = ref(false)

const cloudModels = computed(() => models.value.filter(model => model.source === 'stimma_cloud'))
const selectedQuickModel = computed(() => models.value.find(model => model.slug === quickTaskModel.value))
const selectableModels = computed(() => models.value.filter(model => (
  model.source !== 'auto'
  && !model.collapsed
  && (model.available !== false || model.slug === quickTaskModel.value)
)))
const managerModels = computed(() => discoveredModels.value.length ? discoveredModels.value : (activeProvider.value?.models || []))

function kindLabel(kind) { return providerKinds.find(item => item.id === kind)?.name || kind }
function providerLabel(model) { return model.provider_name || (model.source === 'stimma_cloud' ? 'Stimma Cloud' : 'Local LLM') }
function isDiscoverable(provider) { return ['openrouter', 'local'].includes(provider.kind) }
function managerModelId(model) { return model.model_id || model.id }

async function loadProviders() {
  const response = await axios.get(`${getApiBase()}/models/providers`)
  providers.value = response.data.providers || []
}

async function refreshAll() {
  invalidateCache()
  await Promise.all([fetchModels(null, true), loadProviders()])
}

function beginAdd(kind) {
  draftError.value = ''
  draft.value = { kind, api_key: '', base_url: kind === 'local' ? 'http://localhost:1234/v1' : undefined }
}

async function addProvider() {
  saving.value = true
  draftError.value = ''
  try {
    const response = await axios.post(`${getApiBase()}/models/providers`, draft.value)
    draft.value = null
    await refreshAll()
    manage(response.data)
  } catch (error) {
    draftError.value = error.response?.data?.detail || 'Could not add this service.'
  } finally {
    saving.value = false
  }
}

function manage(provider) {
  activeProvider.value = provider
  discoveredModels.value = []
  selectedManagerIds.value = new Set(provider.models.filter(model => model.enabled).map(model => model.model_id))
  customizingModelId.value = null
  extraBodyDrafts.value = Object.fromEntries(provider.models.map(model => [model.id, JSON.stringify(model.extra_body || {}, null, 2)]))
  extraBodyErrors.value = {}
  providerKeyDraft.value = ''
  providerSaveError.value = ''
  if (isDiscoverable(provider)) loadProviderModels(provider).catch(() => {})
}

async function loadProviderModels(provider) {
  const response = await axios.get(`${getApiBase()}/models/providers/${provider.id}/models`)
  discoveredModels.value = response.data.models || []
  selectedManagerIds.value = new Set(discoveredModels.value.filter(model => model.selected).map(model => model.id))
}

function toggleManagerModel(id) {
  const next = new Set(selectedManagerIds.value)
  next.has(id) ? next.delete(id) : next.add(id)
  selectedManagerIds.value = next
}

async function saveProviderModels() {
  const response = await axios.patch(`${getApiBase()}/models/providers/${activeProvider.value.id}`, { model_ids: [...selectedManagerIds.value] })
  activeProvider.value = response.data
  await refreshAll()
}

function wireLevelsFor(model) {
  const levels = model.reasoning.levels
  const control = model.reasoning.control
  return Object.fromEntries(levels.map((level, index) => {
    if (control === 'enable_thinking' || control === 'think') return [level, level !== 'off']
    if (control === 'reasoning_budget') return [level, level === 'off' ? 0 : [1024, 4096, 16384, 32768][Math.min(index, 3)]]
    if (control === 'openai_effort' || control === 'fireworks_effort') return [level, level === 'off' ? 'none' : level]
    return [level, level]
  }))
}

function normalizeReasoning(model) {
  if (model.reasoning.mode === 'none') {
    model.reasoning.levels = ['off']
    model.reasoning.default = 'off'
    model.reasoning.quick_task = 'off'
    model.reasoning.control = 'none'
  } else if (model.reasoning.levels.length === 0 || (model.reasoning.levels.length === 1 && model.reasoning.levels[0] === 'off')) {
    model.reasoning.levels = model.reasoning.mode === 'required' ? ['low', 'medium', 'high'] : ['off', 'low', 'medium', 'high']
    model.reasoning.default = 'medium'
    model.reasoning.quick_task = model.reasoning.levels[0]
  }
  model.reasoning.wire_levels = wireLevelsFor(model)
}

function setReasoningLevels(model, value) {
  const levels = [...new Set(value.split(',').map(level => level.trim().toLowerCase()).filter(Boolean))]
  model.reasoning.levels = levels.length ? levels : ['off']
  if (!model.reasoning.levels.includes(model.reasoning.default)) model.reasoning.default = model.reasoning.levels[0]
  if (!model.reasoning.levels.includes(model.reasoning.quick_task)) model.reasoning.quick_task = model.reasoning.levels[0]
  model.reasoning.wire_levels = wireLevelsFor(model)
}

function extraBodyText(model) {
  return extraBodyDrafts.value[model.id] ?? JSON.stringify(model.extra_body || {}, null, 2)
}

function setExtraBody(model, value) {
  extraBodyDrafts.value = { ...extraBodyDrafts.value, [model.id]: value }
  try {
    const parsed = value.trim() ? JSON.parse(value) : null
    if (parsed != null && (typeof parsed !== 'object' || Array.isArray(parsed))) throw new Error()
    model.extra_body = parsed
    const next = { ...extraBodyErrors.value }
    delete next[model.id]
    extraBodyErrors.value = next
  } catch {
    extraBodyErrors.value = { ...extraBodyErrors.value, [model.id]: true }
  }
}

async function saveProviderDetails() {
  const response = await axios.patch(`${getApiBase()}/models/providers/${activeProvider.value.id}`, { models: activeProvider.value.models })
  activeProvider.value = response.data
  await refreshAll()
}

async function saveProviderConnection() {
  savingProvider.value = true
  providerSaveError.value = ''
  try {
    const payload = {
      name: activeProvider.value.name,
      base_url: activeProvider.value.base_url,
    }
    if (providerKeyDraft.value) payload.api_key = providerKeyDraft.value
    const response = await axios.patch(`${getApiBase()}/models/providers/${activeProvider.value.id}`, payload)
    activeProvider.value = response.data
    providerKeyDraft.value = ''
    await testProvider(activeProvider.value)
  } catch (error) {
    providerSaveError.value = error.response?.data?.detail || 'Could not check this service.'
  } finally {
    savingProvider.value = false
  }
}

async function testProvider(provider) {
  testingId.value = provider.id
  try { await axios.post(`${getApiBase()}/models/providers/${provider.id}/test`) }
  finally { testingId.value = null; await refreshAll() }
}

async function removeProvider(provider) {
  await axios.delete(`${getApiBase()}/models/providers/${provider.id}`)
  if (activeProvider.value?.id === provider.id) activeProvider.value = null
  await refreshAll()
}

async function saveQuickTaskModel(model) {
  await axios.patch(`${getApiBase()}/settings/quick-task-model`, { model })
  await fetchModels(null, true)
}

async function savePromptPolicy() {
  await axios.patch(`${getApiBase()}/settings/llm-prompt-policy`, {
    content_policy: contentPolicy.value,
    extra_system_prompt: extraSystemPrompt.value,
  })
  emit('update')
}

async function refreshVoiceModelReady() {
  voiceModelReady.value = await isModelReady(voiceModel.value)
}

watch(voiceModel, refreshVoiceModelReady)

onMounted(async () => {
  await refreshVoiceModelReady()
  await Promise.all([fetchModels(), loadProviders()])
  try {
    const response = await axios.get(`${getApiBase()}/settings`)
    contentPolicy.value = response.data.llm_content_policy || 'stimma'
    extraSystemPrompt.value = response.data.llm_extra_system_prompt || ''
  } catch {}
})
</script>
