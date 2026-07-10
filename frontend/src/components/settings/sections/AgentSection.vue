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
        <!-- Tool Permissions -->
        <div class="mb-6">
          <h4 class="text-sm font-medium text-content-secondary mb-1">Tool Permissions</h4>
          <p class="text-xs text-content-tertiary mb-3">The agent asks the first time it uses a tool. Tools you allow or block appear here.</p>
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
        </div>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import axios from 'axios'
import { getApiBase } from '../../../apiConfig'
import ToolConfigRow from '../../chat/ToolConfigRow.vue'
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
})

// Reload when profile changes
watch(currentProfileId, () => {
  loadSettings()
})
</script>
