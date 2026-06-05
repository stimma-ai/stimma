<template>
  <div class="relative" ref="container">
    <button
      type="button"
      @click="toggle"
      class="flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs transition-colors"
      :class="isCloudModel
        ? 'text-teal-500 hover:text-teal-400 hover:bg-teal-500/10'
        : 'text-content-muted hover:text-content-secondary hover:bg-white/[0.05]'"
      :title="currentDisplayName"
    >
      <!-- Cloud icon for cloud models, server icon for local -->
      <svg v-if="isCloudModel" class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15a4.5 4.5 0 0 0 4.5 4.5H18a3.75 3.75 0 0 0 1.332-7.257 3 3 0 0 0-3.758-3.848 5.25 5.25 0 0 0-10.233 2.33A4.502 4.502 0 0 0 2.25 15Z" />
      </svg>
      <svg v-else class="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
      </svg>
      <span class="truncate max-w-[120px]">{{ currentDisplayName }}</span>
      <svg
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
        class="fixed z-50 py-1 bg-surface border border-edge rounded-lg shadow-xl min-w-[200px] max-w-[280px]"
        :style="dropdownStyle"
        tabindex="-1"
        @keydown="handleKeydown"
      >
        <!-- Loading state -->
        <div v-if="loading" class="px-3 py-2 text-xs text-content-muted">
          Loading models...
        </div>

        <template v-else>
          <template v-if="autoModels.length > 0">
            <button
              v-for="model in autoModels"
              :key="model.slug"
              :disabled="model.available === false"
              @click="selectModel(model)"
              class="w-full px-3 py-1.5 text-left flex items-center gap-2 transition-colors"
              :class="model.slug === effectiveSlug
                ? 'bg-blue-500/10'
                : model.available === false ? 'opacity-60 cursor-not-allowed' : 'hover:bg-surface-raised'"
            >
              <div class="flex-1 min-w-0">
                <div class="text-sm text-content truncate">{{ model.name }}<span v-if="model.available === false"> · unavailable</span></div>
                <div v-if="model.description" class="text-[11px] text-content-muted truncate">{{ model.description }}</div>
              </div>
              <svg v-if="model.slug === effectiveSlug" class="w-4 h-4 text-blue-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
              </svg>
            </button>
            <div class="border-t border-edge my-1" />
          </template>

          <!-- Cloud models section -->
          <template v-if="cloudModels.length > 0">
            <div class="px-3 py-1.5 text-[10px] font-medium uppercase tracking-wider stimma-cloud-text">
              Stimma Cloud
            </div>
            <button
              v-for="model in cloudModels"
              :key="model.slug"
              :disabled="model.available === false"
              @click="selectModel(model)"
              class="w-full px-3 py-1.5 text-left flex items-center gap-2 transition-colors"
              :class="model.slug === effectiveSlug
                ? 'bg-cyan-500/10'
                : model.available === false ? 'opacity-60 cursor-not-allowed' : 'hover:bg-surface-raised'"
            >
              <div class="flex-1 min-w-0">
                <div class="text-sm text-content truncate">{{ model.name }}<span v-if="model.available === false"> · unavailable</span></div>
                <div v-if="model.description" class="text-[11px] text-content-muted truncate">{{ model.description }}</div>
              </div>
              <svg v-if="model.slug === effectiveSlug" class="w-4 h-4 text-cyan-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
              </svg>
            </button>
          </template>

          <!-- Local endpoint section -->
          <template v-if="localModels.length > 0">
            <div v-if="cloudModels.length > 0" class="border-t border-edge my-1" />
            <div class="px-3 py-1.5 text-[10px] font-medium uppercase tracking-wider text-content-muted">
              Local
            </div>
            <button
              v-for="model in localModels"
              :key="model.slug"
              :disabled="model.available === false"
              @click="selectModel(model)"
              class="w-full px-3 py-1.5 text-left flex items-center gap-2 transition-colors"
              :class="model.slug === effectiveSlug
                ? 'bg-blue-500/10'
                : model.available === false ? 'opacity-60 cursor-not-allowed' : 'hover:bg-surface-raised'"
            >
              <div class="flex-1 min-w-0">
                <div class="text-sm text-content truncate">{{ model.name }}<span v-if="model.available === false"> · unavailable</span></div>
                <div v-if="model.description" class="text-[11px] text-content-muted truncate">{{ model.description }}</div>
              </div>
              <svg v-if="model.slug === effectiveSlug" class="w-4 h-4 text-blue-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
              </svg>
            </button>
          </template>

          <!-- Empty state -->
          <div v-if="cloudModels.length === 0 && localModels.length === 0" class="px-3 py-2 text-xs text-content-muted">
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
import { useAvailableModels } from '../../composables/useAvailableModels'

const props = defineProps({
  modelSlug: { type: String, default: null },
  chatId: { type: Number, required: true },
  projectId: { type: Number, default: null },
})

const emit = defineEmits(['update:modelSlug'])

const { models, globalDefault, loading, fetchModels, getModelDisplayName } = useAvailableModels()

const container = ref(null)
const dropdown = ref(null)
const isOpen = ref(false)
const dropdownStyle = ref({})

// The effective slug (what's actually being used)
const effectiveSlug = computed(() => props.modelSlug || globalDefault.value)

const currentDisplayName = computed(() => getModelDisplayName(effectiveSlug.value))

const isCloudModel = computed(() => {
  const model = models.value.find(m => m.slug === effectiveSlug.value)
  return model ? model.source === 'stimma_cloud' : !['local', 'auto'].includes(effectiveSlug.value)
})

const autoModels = computed(() => models.value.filter(m => m.source === 'auto'))
const cloudModels = computed(() => models.value.filter(m => m.source === 'stimma_cloud'))
const localModels = computed(() => models.value.filter(m => m.source === 'endpoint'))

onMounted(() => {
  fetchModels(props.projectId, true)
})

function toggle() {
  if (isOpen.value) {
    close()
  } else {
    open()
  }
}

function open() {
  fetchModels(props.projectId, true)
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
  // If selecting the global default, store null (inherit)
  const newSlug = slug === globalDefault.value ? null : slug
  emit('update:modelSlug', newSlug)

  // Persist to backend
  try {
    await axios.patch(`${getApiBase()}/chats/${props.chatId}`, {
      model_slug: newSlug,
    })
  } catch (err) {
    console.error('Failed to update chat model:', err)
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

  // Position above the button (since picker is at bottom of screen)
  dropdownStyle.value = {
    bottom: `${window.innerHeight - rect.top + 4}px`,
    left: `${rect.left}px`,
  }
}
</script>
