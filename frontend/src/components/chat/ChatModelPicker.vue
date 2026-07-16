<template>
  <div class="relative" ref="container">
    <button
      type="button"
      :disabled="triggerDisabled"
      @click="toggle"
      aria-haspopup="dialog"
      :aria-expanded="isOpen"
      class="flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs transition-colors min-w-0"
      :class="triggerDisabled
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
      <svg v-else-if="!currentUnavailable && selectableModels.length > 0" class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
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
        v-if="!triggerDisabled && modelReady"
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
        class="fixed z-50 flex w-96 max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-lg border border-edge bg-surface shadow-xl"
        :style="dropdownStyle"
        tabindex="-1"
        role="dialog"
        aria-label="Choose a model"
        @keydown="handleKeydown"
      >
        <div class="flex-shrink-0 border-b border-edge p-2">
          <div class="relative">
            <svg class="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" d="m21 21-4.35-4.35m1.35-5.4a6.75 6.75 0 1 1-13.5 0 6.75 6.75 0 0 1 13.5 0Z" />
            </svg>
            <input
              ref="searchInput"
              v-model="searchQuery"
              type="search"
              autocomplete="off"
              aria-label="Search models"
              placeholder="Search models…"
              class="w-full rounded-md border border-white/10 bg-white/[0.05] py-2 pl-9 pr-8 text-sm text-content placeholder:text-content-muted focus:border-blue-500/50 focus:outline-none focus:ring-1 focus:ring-blue-500/30"
            />
            <button
              v-if="searchQuery"
              type="button"
              class="absolute right-1.5 top-1/2 -translate-y-1/2 rounded p-1 text-content-muted hover:bg-white/[0.05] hover:text-content"
              aria-label="Clear model search"
              @click="searchQuery = ''"
            >
              <svg class="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path d="M4.47 4.47a.75.75 0 0 1 1.06 0L10 8.94l4.47-4.47a.75.75 0 1 1 1.06 1.06L11.06 10l4.47 4.47a.75.75 0 1 1-1.06 1.06L10 11.06l-4.47 4.47a.75.75 0 0 1-1.06-1.06L8.94 10 4.47 5.53a.75.75 0 0 1 0-1.06Z" />
              </svg>
            </button>
          </div>
        </div>

        <!-- Loading state (only when nothing is cached yet; otherwise show the
             cached list and let any refresh happen silently in the background) -->
        <div v-if="loading && models.length === 0" class="px-3 py-3 text-xs text-content-muted">
          Loading models...
        </div>

        <template v-else>
          <div class="min-h-0 flex-1 overflow-y-auto overscroll-contain py-1">
            <template v-if="filteredAutoModels.length > 0">
              <button
                v-for="model in filteredAutoModels"
                :key="model.slug"
                @click="selectModel(model)"
                class="w-full px-3 py-1.5 text-left flex items-center gap-2 transition-colors"
                :class="modelButtonClass(model, 'bg-blue-500/10')"
              >
                <div class="flex-1 min-w-0">
                  <div class="text-sm text-content">{{ model.name }}</div>
                  <div v-if="model.description" class="text-[11px] leading-snug text-content-muted whitespace-normal break-words">{{ model.description }}</div>
                </div>
                <svg v-if="isSelectedModel(model)" class="w-4 h-4 text-blue-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
                </svg>
              </button>
              <div v-if="recentModels.length > 0 || displayPickerModels.length > 0 || displayCollapsedCloudModels.length > 0" class="my-1 border-t border-edge" />
            </template>

          <template v-if="recentModels.length">
            <div class="flex items-center gap-1.5 px-3 pb-1 pt-1.5 text-[10px] font-semibold uppercase tracking-wider text-content-muted">
              <svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-9-9 9 9 0 0 1 9 9Z" />
              </svg>
              Recent
            </div>
            <button
              v-for="model in recentModels"
              :key="`recent-${model.slug}`"
              @click="selectModel(model)"
              class="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors"
              :class="modelButtonClass(model, model.source === 'stimma_cloud' ? 'bg-cyan-500/10' : 'bg-blue-500/10')"
            >
              <ModelVendorIcon :model="model" size="sm" />
              <div class="min-w-0 flex-1">
                <div class="truncate text-sm text-content">{{ model.name }}</div>
                <div class="truncate text-[11px] text-content-muted">{{ modelSubtitle(model) }}</div>
              </div>
              <svg v-if="isSelectedModel(model)" class="h-4 w-4 flex-shrink-0" :class="model.source === 'stimma_cloud' ? 'text-cyan-400' : 'text-blue-400'" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
              </svg>
            </button>
            <div v-if="displayPickerModels.length > 0 || displayCollapsedCloudModels.length > 0" class="my-1 border-t border-edge" />
          </template>

          <!-- Models (cloud + local, one flat list; provenance lives in the subtitle) -->
          <div v-if="displayPickerModels.length > 0" class="px-3 pb-1 pt-1.5 text-[10px] font-semibold uppercase tracking-wider text-content-muted">
            {{ hasSearch ? 'Matching models' : 'Models' }}
          </div>
          <button
            v-for="model in displayPickerModels"
            :key="model.slug"
            @click="selectModel(model)"
            class="w-full px-3 py-2 text-left flex items-center gap-2 transition-colors"
            :class="modelButtonClass(model, model.source === 'stimma_cloud' ? 'bg-cyan-500/10' : 'bg-blue-500/10')"
          >
            <ModelVendorIcon :model="model" size="sm" />
            <div class="flex-1 min-w-0">
              <div class="text-sm text-content">{{ model.name }}</div>
              <div v-if="model.source === 'stimma_cloud'" class="truncate text-[11px] leading-snug">
                <span v-if="modelVendorLabel(model)" class="text-content-muted">{{ modelVendorLabel(model) }} · </span><span class="stimma-cloud-text font-medium">via Stimma</span><span v-if="model.cost_tier" class="text-content-muted"> · {{ model.cost_tier }}</span>
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

          <template v-if="displayCollapsedCloudModels.length">
            <button
              v-if="!hasSearch"
              type="button"
              @click="showCollapsedCloud = !showCollapsedCloud"
              class="flex w-full items-center justify-between border-t border-edge px-3 py-2 text-left text-[11px] text-content-muted hover:text-content-secondary"
            >
              <span>Also via Stimma ({{ displayCollapsedCloudModels.length }})</span>
              <svg class="h-3 w-3 transition-transform" :class="showCollapsedCloud ? 'rotate-180' : ''" viewBox="0 0 12 12" fill="currentColor">
                <path d="M3 4.5L6 8l3-3.5H3z" />
              </svg>
            </button>
            <div v-else class="border-t border-edge px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-content-muted">
              Also via Stimma
            </div>
            <button
              v-if="showCollapsedCloud || hasSearch"
              v-for="model in displayCollapsedCloudModels"
              :key="model.slug"
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

          <!-- Empty state -->
          <div v-if="!hasModelResults" class="px-3 py-8 text-center text-xs text-content-muted">
            {{ hasSearch ? `No models match “${searchQuery.trim()}”` : 'No models available' }}
          </div>
          </div>

          <div v-if="reasoningOptions.length" class="flex-shrink-0 border-t border-edge px-3 py-2">
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
        </template>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../apiConfig'
import { normalizeModelSlug, useAvailableModels } from '../../composables/useAvailableModels'
import { makeProfileKey } from '../../utils/storageKeys'
import ModelVendorIcon from '../models/ModelVendorIcon.vue'
import { getModelVendorInfo, sortModelsByBrand } from '../../utils/modelVendors'

const MAX_RECENT_MODELS = 4

const props = defineProps({
  modelSlug: { type: String, default: null },
  chatId: { type: Number, default: null },
  projectId: { type: Number, default: null },
  disabled: { type: Boolean, default: false },
  disabledLabel: { type: String, default: 'Model unavailable' },
})

const emit = defineEmits(['update:modelSlug'])

const { models, selectableModels, globalDefault, reasoningLevels, loading, hasFetched, fetchModels, getModelDisplayName, getSelectableModel } = useAvailableModels()

const container = ref(null)
const dropdown = ref(null)
const searchInput = ref(null)
const isOpen = ref(false)
const showCollapsedCloud = ref(false)
const searchQuery = ref('')
const recentModelSlugs = ref(loadRecentModelSlugs())
const dropdownStyle = ref({})

// The effective slug (what's actually being used)
const effectiveSlug = computed(() => normalizeModelSlug(props.modelSlug || globalDefault.value))

const currentDisplayName = computed(() => {
  if (catalogReady.value && selectableModels.value.length === 0) return 'No models available'
  if (props.disabled) return props.disabledLabel
  if (currentUnavailable.value) return 'Choose a model'
  return getModelDisplayName(effectiveSlug.value)
})

// The trigger shows a spinner until the model list resolves, so the label
// doesn't flicker from the raw 'auto' slug to its resolved name. Once the
// in-memory cache is warm (subsequent mounts) models are present immediately,
// so there's no spinner and no hop.
const catalogReady = computed(() => hasFetched.value || models.value.length > 0)
const modelReady = computed(() => props.disabled || catalogReady.value)
const triggerDisabled = computed(() => props.disabled || (
  catalogReady.value && selectableModels.value.length === 0
))

const selectedModel = computed(() => selectableModels.value.find(m => m.slug === effectiveSlug.value))
const resolvedModel = computed(() => getSelectableModel(effectiveSlug.value))
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
  if (!catalogReady.value || loading.value && !hasFetched.value) return false
  return Boolean(effectiveSlug.value && !selectedModel.value)
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
  return model?.source === 'stimma_cloud'
})

const autoModels = computed(() => selectableModels.value.filter(m => m.source === 'auto'))
const visibleAutoModels = computed(() => autoModels.value.filter(m => !m.resolved_slug))
const cloudModels = computed(() => selectableModels.value.filter(m => m.source === 'stimma_cloud' && !m.collapsed))
const collapsedCloudModels = computed(() => selectableModels.value.filter(m => m.source === 'stimma_cloud' && m.collapsed))
const providerModels = computed(() => selectableModels.value.filter(m => m.source === 'provider'))
const localModels = computed(() => selectableModels.value.filter(m => m.source === 'endpoint'))
const pickerModels = computed(() => sortModelsByBrand([...providerModels.value, ...cloudModels.value, ...localModels.value]))
const searchTokens = computed(() => searchQuery.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean))
const hasSearch = computed(() => searchTokens.value.length > 0)
const filteredAutoModels = computed(() => visibleAutoModels.value.filter(modelMatchesSearch))
const filteredPickerModels = computed(() => pickerModels.value.filter(modelMatchesSearch))
const filteredCollapsedCloudModels = computed(() => collapsedCloudModels.value.filter(modelMatchesSearch))
const recentModels = computed(() => {
  if (hasSearch.value) return []
  return recentModelSlugs.value
    .map(slug => selectableModels.value.find(model => model.slug === slug))
    .filter(model => model && model.source !== 'auto')
})
const recentSlugSet = computed(() => new Set(recentModels.value.map(model => model.slug)))
const displayPickerModels = computed(() => filteredPickerModels.value.filter(model => !recentSlugSet.value.has(model.slug)))
const displayCollapsedCloudModels = computed(() => filteredCollapsedCloudModels.value.filter(model => !recentSlugSet.value.has(model.slug)))
const hasModelResults = computed(() => (
  filteredAutoModels.value.length > 0
  || recentModels.value.length > 0
  || displayPickerModels.value.length > 0
  || displayCollapsedCloudModels.value.length > 0
))

onMounted(() => {
  // Use the in-memory cache if it's fresh; only the first open of a run hits
  // the server. A stale cache refreshes silently without flipping the loading UI.
  fetchModels(props.projectId)
  window.addEventListener('resize', positionDropdown)
})

onBeforeUnmount(() => window.removeEventListener('resize', positionDropdown))

function toggle() {
  if (isOpen.value) {
    close()
  } else {
    open()
  }
}

function open() {
  if (triggerDisabled.value) return
  fetchModels(props.projectId)
  recentModelSlugs.value = loadRecentModelSlugs()
  isOpen.value = true
  nextTick(() => {
    positionDropdown()
    searchInput.value?.focus()
  })
}

function close() {
  isOpen.value = false
  searchQuery.value = ''
  showCollapsedCloud.value = false
}

async function selectModel(model) {
  if (!getSelectableModel(model.slug)) return
  if (model.source !== 'auto') recordRecentModel(model.slug)
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
  return 'hover:bg-surface-raised'
}

function modelVendorLabel(model) {
  return getModelVendorInfo(model)?.label || ''
}

function modelSubtitle(model) {
  if (model.source === 'stimma_cloud') {
    return [modelVendorLabel(model), 'via Stimma', model.cost_tier].filter(Boolean).join(' · ')
  }
  if (model.endpoint_model) return model.endpoint_model
  return [modelVendorLabel(model), model.description].filter(Boolean).join(' · ')
}

function modelMatchesSearch(model) {
  if (!searchTokens.value.length) return true
  const text = [
    model.name,
    model.slug,
    model.description,
    model.endpoint_model,
    model.endpoint_url,
    model.provider,
    model.provider_name,
    model.provider_kind,
    model.model_vendor,
    model.model_id,
    model.canonical_model_id,
    model.cost_tier,
    model.shadowed_by_provider,
    modelVendorLabel(model),
    model.source === 'stimma_cloud' ? 'via Stimma' : '',
  ].filter(Boolean).join(' ').toLocaleLowerCase()
  return searchTokens.value.every(token => text.includes(token))
}

function recentModelsStorageKey() {
  return makeProfileKey('model_picker', 'recent')
}

function loadRecentModelSlugs() {
  try {
    const stored = JSON.parse(localStorage.getItem(recentModelsStorageKey()) || '[]')
    return Array.isArray(stored)
      ? stored.filter(slug => typeof slug === 'string' && slug !== 'auto').slice(0, MAX_RECENT_MODELS)
      : []
  } catch {
    return []
  }
}

function recordRecentModel(slug) {
  const next = [slug, ...recentModelSlugs.value.filter(recentSlug => recentSlug !== slug)].slice(0, MAX_RECENT_MODELS)
  recentModelSlugs.value = next
  try {
    localStorage.setItem(recentModelsStorageKey(), JSON.stringify(next))
  } catch {
    // Recents are a convenience; model selection should still work if storage is unavailable.
  }
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
  const dropdownWidth = Math.min(384, window.innerWidth - 32)
  const left = Math.max(16, Math.min(rect.left, window.innerWidth - dropdownWidth - 16))
  const spaceAbove = Math.max(0, rect.top - 16)
  const spaceBelow = Math.max(0, window.innerHeight - rect.bottom - 16)
  const positionAbove = spaceAbove >= spaceBelow
  const availableHeight = Math.min(640, positionAbove ? spaceAbove : spaceBelow)

  dropdownStyle.value = {
    left: `${left}px`,
    maxHeight: `${availableHeight}px`,
    ...(positionAbove
      ? { bottom: `${window.innerHeight - rect.top + 4}px` }
      : { top: `${rect.bottom + 4}px` }),
  }
}
</script>
