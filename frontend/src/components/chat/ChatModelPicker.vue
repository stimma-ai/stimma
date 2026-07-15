<template>
  <div class="relative" ref="container">
    <button
      type="button"
      :disabled="disabled"
      @click="toggle"
      class="flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs transition-colors min-w-0"
      :class="disabled
        ? 'text-content-muted opacity-60 cursor-not-allowed'
        : currentUnavailable
        ? 'text-content-muted opacity-70 hover:text-content-secondary hover:bg-white/[0.05]'
        : isCloudModel
        ? 'text-teal-500 hover:text-teal-400 hover:bg-teal-500/10'
        : 'text-content-muted hover:text-content-secondary hover:bg-white/[0.05]'"
      :title="currentTitle"
    >
      <!-- Spinner until the model list is ready, to avoid the 'auto' -> resolved
           name flicker (label, icon and color all settle at once) -->
      <svg v-if="!modelReady" class="w-3.5 h-3.5 flex-shrink-0 animate-spin text-content-muted" viewBox="0 0 24 24" fill="none">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" />
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <!-- Cloud icon for cloud models, server icon for local -->
      <svg v-else-if="isCloudModel" class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15a4.5 4.5 0 0 0 4.5 4.5H18a3.75 3.75 0 0 0 1.332-7.257 3 3 0 0 0-3.758-3.848 5.25 5.25 0 0 0-10.233 2.33A4.502 4.502 0 0 0 2.25 15Z" />
      </svg>
      <svg v-else class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
      </svg>
      <span
        v-if="modelReady"
        class="truncate max-w-[150px]"
        :class="isCloudModel && !currentUnavailable ? 'stimma-cloud-text' : ''"
      >
        {{ currentDisplayName }}<span v-if="currentReasoningLabel" class="text-content-muted"> · {{ currentReasoningLabel }}</span>
      </span>
      <svg
        v-if="!disabled && modelReady"
        class="w-2.5 h-2.5 text-content-muted transition-transform flex-shrink-0"
        :class="{ 'rotate-180': isOpen }"
        viewBox="0 0 12 12"
        fill="currentColor"
      >
        <path d="M3 4.5L6 8l3-3.5H3z"/>
      </svg>
    </button>

    <Teleport to="body">
      <!-- Backdrop -->
      <div
        v-if="isOpen"
        class="fixed inset-0 z-50"
        @click="close"
      />
      <!-- Dropdown -->
      <div
        v-if="isOpen"
        ref="dropdown"
        class="fixed z-50 py-1 bg-surface border border-edge rounded-lg shadow-xl w-80 max-w-[calc(100vw-2rem)]"
        :style="dropdownStyle"
        tabindex="-1"
        @keydown="handleKeydown"
      >
        <!-- Loading state (only when nothing is cached yet; otherwise show the
             cached list and let any refresh happen silently in the background) -->
        <div v-if="loading && models.length === 0" class="px-3 py-2 text-xs text-content-muted">
          Loading models...
        </div>

        <template v-else>
          <template v-if="visibleAutoModels.length > 0">
            <button
              v-for="model in visibleAutoModels"
              :key="model.slug"
              :disabled="model.available === false"
              @click="selectModel(model)"
              class="w-full px-3 py-1.5 text-left flex items-center gap-2 transition-colors"
              :class="modelButtonClass(model, 'bg-blue-500/10')"
            >
              <div class="flex-1 min-w-0">
                <div class="text-sm text-content">{{ model.name }}<span v-if="model.available === false"> · unavailable</span></div>
                <div v-if="model.description" class="text-[11px] leading-snug text-content-muted whitespace-normal break-words">{{ model.description }}</div>
              </div>
              <svg v-if="isSelectedModel(model)" class="w-4 h-4 text-blue-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
              </svg>
            </button>
            <div v-if="cloudModels.length > 0 || localModels.length > 0" class="border-t border-edge my-1" />
          </template>

          <!-- Models (cloud + local, one flat list; provenance lives in the subtitle) -->
          <button
            v-for="model in pickerModels"
            :key="model.slug"
            :disabled="model.available === false"
            @click="selectModel(model)"
            class="w-full px-3 py-2 text-left flex items-center gap-2 transition-colors"
            :class="modelButtonClass(model, model.source === 'stimma_cloud' ? 'bg-cyan-500/10' : 'bg-blue-500/10')"
          >
            <ModelVendorIcon :model="model" size="sm" />
            <div class="flex-1 min-w-0">
              <div class="text-sm text-content">{{ model.name }}<span v-if="model.available === false"> · unavailable</span></div>
              <div v-if="model.source === 'stimma_cloud' && model.description" class="text-[11px] leading-snug whitespace-normal break-words">
                <span class="text-content-muted">{{ modelVendorLabel(model) }} · </span><span class="stimma-cloud-text font-medium">via Stimma</span><span class="text-content-muted"> · {{ model.description }}<template v-if="model.cost_tier"> · {{ model.cost_tier }}</template></span>
              </div>
              <div
                v-else-if="model.endpoint_model"
                class="text-[11px] leading-snug font-mono text-content-muted truncate"
                :title="model.endpoint_url ? `${model.endpoint_url} (${model.endpoint_model})` : model.endpoint_model"
              >{{ model.endpoint_model }}</div>
              <div v-else-if="model.description" class="text-[11px] leading-snug text-content-muted whitespace-normal break-words"><template v-if="modelVendorLabel(model)">{{ modelVendorLabel(model) }} · </template>{{ model.description }}</div>
            </div>
            <svg v-if="isSelectedModel(model)" class="w-4 h-4 flex-shrink-0" :class="model.source === 'stimma_cloud' ? 'text-cyan-400' : 'text-blue-400'" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
            </svg>
          </button>

          <template v-if="collapsedCloudModels.length">
            <button
              type="button"
              @click="showCollapsedCloud = !showCollapsedCloud"
              class="flex w-full items-center justify-between border-t border-edge px-3 py-2 text-left text-[11px] text-content-muted hover:text-content-secondary"
            >
              <span>Also via Stimma</span>
              <svg class="h-3 w-3 transition-transform" :class="showCollapsedCloud ? 'rotate-180' : ''" viewBox="0 0 12 12" fill="currentColor">
                <path d="M3 4.5L6 8l3-3.5H3z" />
              </svg>
            </button>
            <button
              v-if="showCollapsedCloud"
              v-for="model in collapsedCloudModels"
              :key="model.slug"
              :disabled="model.available === false"
              @click="selectModel(model)"
              class="w-full px-3 py-2 text-left flex items-center gap-2 transition-colors"
              :class="modelButtonClass(model, 'bg-cyan-500/10')"
            >
              <ModelVendorIcon :model="model" size="sm" />
              <div class="min-w-0 flex-1">
                <div class="text-sm text-content">{{ model.name }}</div>
                <div class="text-[11px] text-content-muted">{{ modelVendorLabel(model) }} · via Stimma<span v-if="model.cost_tier"> · {{ model.cost_tier }}</span><span v-if="model.shadowed_by_provider"> · also available via {{ model.shadowed_by_provider }}</span></div>
              </div>
              <svg v-if="isSelectedModel(model)" class="h-4 w-4 flex-shrink-0 text-cyan-400" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
              </svg>
            </button>
          </template>

          <div v-if="reasoningOptions.length" class="mt-1 border-t border-edge px-3 py-2">
            <div class="mb-1.5 text-[11px] font-medium text-content-muted">Reasoning</div>
            <div class="flex flex-wrap gap-1">
              <button
                v-for="level in reasoningOptions"
                :key="level"
                @click="selectReasoning(level)"
                class="rounded-md border px-2 py-1 text-[11px] capitalize"
                :class="level === currentReasoningLevel ? 'border-blue-500/50 bg-blue-500/15 text-blue-400' : 'border-white/10 bg-white/[0.05] text-content-secondary hover:text-content'"
              >{{ reasoningLabel(level) }}</button>
            </div>
          </div>

          <!-- Empty state -->
          <div v-if="visibleAutoModels.length === 0 && pickerModels.length === 0" class="px-3 py-2 text-xs text-content-muted">
            No models available
          </div>
        </template>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../apiConfig'
import { normalizeModelSlug, useAvailableModels } from '../../composables/useAvailableModels'
import ModelVendorIcon from '../models/ModelVendorIcon.vue'
import { getModelVendorInfo, sortModelsByBrand } from '../../utils/modelVendors'

const props = defineProps({
  modelSlug: { type: String, default: null },
  chatId: { type: Number, default: null },
  projectId: { type: Number, default: null },
  disabled: { type: Boolean, default: false },
  disabledLabel: { type: String, default: 'Model unavailable' },
})

const emit = defineEmits(['update:modelSlug'])

const { models, globalDefault, reasoningLevels, loading, fetchModels, getModelDisplayName, getResolvedModel } = useAvailableModels()

const container = ref(null)
const dropdown = ref(null)
const isOpen = ref(false)
const showCollapsedCloud = ref(false)
const dropdownStyle = ref({})

// The effective slug (what's actually being used)
const effectiveSlug = computed(() => normalizeModelSlug(props.modelSlug || globalDefault.value))

const currentDisplayName = computed(() => {
  if (props.disabled) return props.disabledLabel
  // Informational, not alarming: a bare "Agent unavailable" instead of
  // "<model name> · unavailable" — the CTA card (when present) carries the
  // remedy, this pill just states the fact.
  if (currentUnavailable.value) return 'Agent unavailable'
  return getModelDisplayName(effectiveSlug.value)
})

// The trigger shows a spinner until the model list resolves, so the label
// doesn't flicker from the raw 'auto' slug to its resolved name. Once the
// in-memory cache is warm (subsequent mounts) models are present immediately,
// so there's no spinner and no hop.
const modelReady = computed(() => props.disabled || models.value.length > 0)

const selectedModel = computed(() => models.value.find(m => m.slug === effectiveSlug.value))
const resolvedModel = computed(() => getResolvedModel(effectiveSlug.value))
const resolvedEffectiveSlug = computed(() => selectedModel.value?.resolved_slug || effectiveSlug.value)
const reasoningModel = computed(() => resolvedModel.value || selectedModel.value)
const reasoningOptions = computed(() => reasoningModel.value?.reasoning?.levels || [])
const currentReasoningLevel = computed(() => {
  const model = reasoningModel.value
  if (!model) return null
  return reasoningLevels.value[model.slug] || model.reasoning?.default || null
})
const currentReasoningLabel = computed(() => currentReasoningLevel.value ? reasoningLabel(currentReasoningLevel.value) : '')

const currentUnavailable = computed(() => {
  if (loading.value) return false
  if (models.value.length > 0 && effectiveSlug.value && !selectedModel.value) return true
  return selectedModel.value?.available === false
})

const currentTitle = computed(() => {
  const model = selectedModel.value
  const display = currentDisplayName.value
  if (!model) return display
  const description = model.description
  return description ? `${display}: ${description}` : display
})

const isCloudModel = computed(() => {
  const model = resolvedModel.value || selectedModel.value
  return model ? model.source === 'stimma_cloud' : !['local', 'auto'].includes(effectiveSlug.value)
})

const autoModels = computed(() => models.value.filter(m => m.source === 'auto'))
const visibleAutoModels = computed(() => autoModels.value.filter(m => !m.resolved_slug))
const cloudModels = computed(() => models.value.filter(m => m.source === 'stimma_cloud' && !m.collapsed))
const collapsedCloudModels = computed(() => models.value.filter(m => m.source === 'stimma_cloud' && m.collapsed))
const providerModels = computed(() => models.value.filter(m => m.source === 'provider'))
const localModels = computed(() => models.value.filter(m => m.source === 'endpoint'))
const pickerModels = computed(() => sortModelsByBrand([...providerModels.value, ...cloudModels.value, ...localModels.value]))

onMounted(() => {
  // Use the in-memory cache if it's fresh; only the first open of a run hits
  // the server. A stale cache refreshes silently without flipping the loading UI.
  fetchModels(props.projectId)
})

function toggle() {
  if (isOpen.value) {
    close()
  } else {
    open()
  }
}

function open() {
  if (props.disabled) return
  fetchModels(props.projectId)
  isOpen.value = true
  nextTick(() => {
    positionDropdown()
    dropdown.value?.focus()
  })
}

function close() {
  isOpen.value = false
}

async function selectModel(model) {
  if (model.available === false) return
  close()
  const slug = model.slug
  const newSlug = slug
  emit('update:modelSlug', newSlug)

  // Persist to backend
  try {
    if (props.chatId != null) {
      await axios.patch(`${getApiBase()}/chats/${props.chatId}`, {
        model_slug: newSlug,
      })
    }
    await axios.patch(`${getApiBase()}/settings/default-model`, {
      default_model: newSlug,
    })
    await fetchModels(props.projectId, true)
  } catch (err) {
    console.error('Failed to update chat model:', err)
  }
}

function reasoningLabel(level) {
  return level === 'off' ? 'Off' : level === 'xhigh' ? 'XHigh' : level
}

async function selectReasoning(level) {
  const model = reasoningModel.value
  if (!model) return
  await axios.patch(`${getApiBase()}/settings/model-reasoning`, {
    model: model.slug,
    level,
  })
  await fetchModels(props.projectId, true)
}

function isSelectedModel(model) {
  return model.slug === effectiveSlug.value || (
    effectiveSlug.value === 'auto' && model.slug === resolvedEffectiveSlug.value
  )
}

function modelButtonClass(model, selectedClass) {
  if (isSelectedModel(model)) return selectedClass
  return model.available === false ? 'opacity-60 cursor-not-allowed' : 'hover:bg-surface-raised'
}

function modelVendorLabel(model) {
  return getModelVendorInfo(model)?.label || ''
}

function handleKeydown(e) {
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
  }
}

function positionDropdown() {
  if (!container.value) return
  const rect = container.value.getBoundingClientRect()
  const dropdownWidth = Math.min(320, window.innerWidth - 32)
  const left = Math.max(16, Math.min(rect.left, window.innerWidth - dropdownWidth - 16))

  // Position above the button (since picker is at bottom of screen)
  dropdownStyle.value = {
    bottom: `${window.innerHeight - rect.top + 4}px`,
    left: `${left}px`,
  }
}
</script>
