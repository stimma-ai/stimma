<template>
  <div>
    <h3 class="text-base font-medium text-content mb-4">Agent</h3>
    <p class="text-sm text-content-tertiary mb-6">
      Configure default agent behavior for all chats in this profile. Per-chat settings can override these defaults.
    </p>

    <!-- Loading state -->
    <div v-if="loading" class="flex items-center justify-center py-12">
      <div class="w-6 h-6 border-2 border-edge border-t-content-secondary rounded-full animate-spin"></div>
    </div>

    <template v-else>
      <!-- Default Instructions -->
      <div class="mb-6">
        <h4 class="text-sm font-medium text-content-secondary mb-3">Default Instructions</h4>
        <textarea
          v-model="localInstructions"
          placeholder="Give the agent default instructions..."
          rows="6"
          class="w-full bg-base text-content text-sm border border-edge rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 resize-none"
          @blur="saveInstructions"
        />
      </div>

      <!-- Memory -->
      <div class="mb-6">
        <h4 class="text-sm font-medium text-content-secondary mb-1">Memory</h4>
        <p class="text-xs text-content-tertiary mb-3">
          Persistent context the agent remembers across all chats. The agent can also update this.
        </p>
        <textarea
          v-model="localMemory"
          placeholder="No memories yet..."
          rows="6"
          class="w-full bg-base text-content text-sm border border-edge rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 resize-none"
          @blur="saveMemory"
        />
      </div>

      <!-- Loading tools state -->
      <div v-if="loadingTools" class="flex items-center justify-center py-8 text-content-muted text-sm">
        Loading tools...
      </div>

      <template v-else>
        <!-- Generation Tools -->
        <div class="mb-6">
          <div class="flex items-center justify-between mb-3">
            <h4 class="text-sm font-medium text-content-secondary">Generation Tools</h4>
            <button
              ref="addToolButtonRef"
              @click="toggleAddToolDropdown"
              class="flex items-center gap-1.5 px-3 py-1.5 text-xs text-content-secondary hover:text-content bg-surface hover:bg-surface-raised border border-edge rounded-lg transition-colors"
            >
              <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
              </svg>
              Add Tool
            </button>
          </div>
          <div v-if="configuredTools.length > 0" class="bg-surface-raised border border-edge rounded-lg overflow-hidden">
            <ToolConfigRow
              v-for="(tool, idx) in configuredTools"
              :key="tool.full_tool_id"
              :tool="tool"
              :config="localToolConfig"
              :show-neutral="false"
              :show-border="idx < configuredTools.length - 1"
              @update:config="handleToolConfigUpdate"
              @remove="handleRemoveTool(tool.full_tool_id)"
            />
          </div>
          <p v-else class="text-xs text-content-muted mt-2">No generation tools configured. Click Add Tool to configure one.</p>
        </div>
      </template>
    </template>

    <!-- Add Tool Dropdown -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="showAddToolDropdown"
          ref="addToolDropdownRef"
          class="fixed w-56 max-h-[28rem] bg-surface border border-edge-subtle rounded-lg shadow-xl z-[10020] flex flex-col overflow-y-auto"
          :style="addToolDropdownStyle"
        >
          <TaskTypeToolList
            ref="addToolListRef"
            :tools="unconfiguredTools"
            :loading="loadingTools"
            gradient-id="stimma-gradient-permissions"
            @select="handleAddToolFromList"
          />
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../../apiConfig'
import ToolConfigRow from '../../chat/ToolConfigRow.vue'
import TaskTypeToolList from '../../TaskTypeToolList.vue'
import type { ToolConfig } from '../../../composables/useAgentPresetsApi'
import { useProvidersApi, type ProviderTool } from '../../../composables/useProvidersApi'
import { useProfile } from '../../../composables/useProfile'

interface ProfileAgentSettings {
  additional_instructions: string
  memory: string
  tool_config: ToolConfig
}

const { listAllTools } = useProvidersApi()
const { currentProfileId } = useProfile()

// State
const loading = ref(false)
const loadingTools = ref(false)
const settings = ref<ProfileAgentSettings | null>(null)
const allTools = ref<ProviderTool[]>([])



// Add tool dropdown state
const showAddToolDropdown = ref(false)
const addToolButtonRef = ref<HTMLElement | null>(null)
const addToolDropdownRef = ref<HTMLElement | null>(null)
const addToolListRef = ref<InstanceType<typeof TaskTypeToolList> | null>(null)
const addToolDropdownPosition = ref({ top: 0, left: 0 })


// Local editing state
const localInstructions = ref('')
const localMemory = ref('')
const localToolConfig = ref<ToolConfig>({
  allowed_tools: [],
  denied_tools: [],
})

// Computed: tools that are explicitly configured (in allowed or denied lists)
const configuredToolIds = computed(() => {
  const allowed = localToolConfig.value?.allowed_tools || []
  const denied = localToolConfig.value?.denied_tools || []
  return new Set([...allowed, ...denied])
})

const configuredTools = computed(() => {
  return allTools.value.filter(tool => configuredToolIds.value.has(tool.full_tool_id))
})

// Computed: tools NOT in the configured list (for the add dropdown)
const unconfiguredTools = computed(() => {
  return allTools.value.filter(tool => !configuredToolIds.value.has(tool.full_tool_id))
})

const addToolDropdownStyle = computed(() => ({
  top: `${addToolDropdownPosition.value.top}px`,
  left: `${addToolDropdownPosition.value.left}px`,
}))

// Add tool dropdown methods
function updateAddToolDropdownPosition() {
  if (addToolButtonRef.value) {
    const rect = addToolButtonRef.value.getBoundingClientRect()
    // Position below the button, aligned to the right
    addToolDropdownPosition.value = {
      top: rect.bottom + 4,
      left: Math.max(16, Math.min(rect.right - 224, window.innerWidth - 240)),
    }
  }
}

function toggleAddToolDropdown() {
  showAddToolDropdown.value = !showAddToolDropdown.value
  if (showAddToolDropdown.value) {
    updateAddToolDropdownPosition()
    // Reset task type tool list when opening
    setTimeout(() => addToolListRef.value?.reset(), 0)
  }
}

async function handleAddToolFromList(tool: ProviderTool, _taskType: string) {
  await handleAddTool(tool.full_tool_id)
}

async function handleAddTool(toolId: string) {
  // Add tool to allowed_tools by default
  const current = localToolConfig.value
  const currentAllowed = current?.allowed_tools || []

  const newConfig = {
    allowed_tools: currentAllowed.includes(toolId)
      ? [...currentAllowed]
      : [...currentAllowed, toolId],
    denied_tools: [...(current?.denied_tools || [])],
    v2_permissions: { ...(current?.v2_permissions || {}) },
  }

  await handleToolConfigUpdate(newConfig)
  showAddToolDropdown.value = false
}

async function handleRemoveTool(toolId: string) {
  // Remove from both allowed and denied lists
  const current = localToolConfig.value

  const newConfig = {
    allowed_tools: (current?.allowed_tools || []).filter(id => id !== toolId),
    denied_tools: (current?.denied_tools || []).filter(id => id !== toolId),
    v2_permissions: { ...(current?.v2_permissions || {}) },
  }

  await handleToolConfigUpdate(newConfig)
}

function handleClickOutside(e: MouseEvent) {
  const target = e.target as Node

  // Close add tool dropdown if clicking outside
  if (showAddToolDropdown.value) {
    const isInsideButton = addToolButtonRef.value?.contains(target)
    const isInsideDropdown = addToolDropdownRef.value?.contains(target)
    if (!isInsideButton && !isInsideDropdown) {
      showAddToolDropdown.value = false
    }
  }

}

// Methods
async function loadSettings() {
  loading.value = true
  try {
    const response = await axios.get(`${getApiBase()}/settings/agent`)
    settings.value = response.data
    localInstructions.value = settings.value?.additional_instructions || ''
    localMemory.value = settings.value?.memory || ''
    localToolConfig.value = settings.value?.tool_config || {
      allowed_tools: [],
      denied_tools: [],
    }
  } catch (err) {
    console.error('Failed to load agent settings:', err)
  } finally {
    loading.value = false
  }
}

async function loadTools() {
  loadingTools.value = true
  try {
    allTools.value = await listAllTools()
  } catch (err) {
    console.error('Failed to load tools:', err)
  } finally {
    loadingTools.value = false
  }
}

async function saveInstructions() {
  if (settings.value?.additional_instructions === localInstructions.value) return

  try {
    await axios.patch(`${getApiBase()}/settings/agent`, {
      additional_instructions: localInstructions.value,
    })
  } catch (err) {
    console.error('Failed to save instructions:', err)
  }
}

async function saveMemory() {
  if (settings.value?.memory === localMemory.value) return

  try {
    await axios.patch(`${getApiBase()}/settings/agent`, {
      memory: localMemory.value,
    })
  } catch (err) {
    console.error('Failed to save memory:', err)
  }
}

async function handleToolConfigUpdate(config: ToolConfig) {
  localToolConfig.value = config
  try {
    await axios.patch(`${getApiBase()}/settings/agent`, {
      tool_config: config,
    })
  } catch (err) {
    console.error('Failed to save tool config:', err)
  }
}

// Load data on mount
onMounted(() => {
  loadSettings()
  loadTools()
  // Use mousedown instead of click: when clicking a category inside TaskTypeToolList,
  // the component re-renders and removes the clicked element from the DOM before the
  // click event bubbles. At that point contains() returns false, closing the menu prematurely.
  document.addEventListener('mousedown', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('mousedown', handleClickOutside)
})

// Reload when profile changes
watch(currentProfileId, () => {
  loadSettings()
})
</script>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

</style>
