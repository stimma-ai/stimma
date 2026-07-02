<template>
  <div
    class="flex-shrink-0 bg-base border-l border-edge flex flex-col transition-all duration-300 overflow-hidden"
    :class="isVisible ? 'w-80 opacity-100' : 'w-0 opacity-0 pointer-events-none'"
  >
    <!-- Full panel content -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto px-3 pt-3 pb-3 space-y-4">
        <!-- Additional Instructions section -->
        <div>
          <div class="flex items-center justify-between mb-1.5">
            <h4 class="text-[11px] font-medium text-content-muted uppercase tracking-wider">Additional Instructions</h4>
            <button
              @click="showInstructionsModal = true"
              class="p-1 text-content-muted hover:text-content-secondary transition-colors"
              title="Expand editor"
            >
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
              </svg>
            </button>
          </div>
          <textarea
            v-model="localInstructions"
            placeholder="Give the agent special instructions for this chat..."
            rows="6"
            class="w-full bg-surface text-content text-sm border border-edge rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 resize-none"
            @blur="saveInstructions"
          />
          <p class="text-[11px] text-content-muted mt-1 leading-relaxed">
            Guide the agent's behavior. Try: style preferences, output formats, tool constraints, or specific parameters like LoRAs and CFG values.
          </p>
        </div>

        <div v-if="loadingTools" class="py-8 text-center text-content-muted text-sm">
          Loading tools...
        </div>
        <template v-else>
          <!-- V2 Agent Tools section -->
          <div>
            <h4 class="text-[11px] font-medium text-content-muted uppercase tracking-wider mb-1.5">Agent Tools</h4>
            <div class="bg-surface rounded-lg border border-edge overflow-hidden">
              <div
                v-for="(tool, idx) in V2_TOOLS"
                :key="tool.name"
                class="flex items-center justify-between px-3 py-2"
                :class="idx < V2_TOOLS.length - 1 ? 'border-b border-edge' : ''"
              >
                <span class="text-[13px] text-content">{{ tool.label }}</span>
                <select
                  :value="getV2Permission(tool.name)"
                  @change="setV2Permission(tool.name, ($event.target as HTMLSelectElement).value)"
                  class="text-xs bg-base text-content border border-edge rounded-md px-2 py-1 focus:outline-none focus:border-blue-500 cursor-pointer"
                >
                  <option value="ask">Ask</option>
                  <option value="allow">Allow</option>
                  <option value="deny">Deny</option>
                </select>
              </div>
            </div>
          </div>

          <!-- Generation Tools section -->
          <div>
            <div class="flex items-center justify-between mb-1.5">
              <h4 class="text-[11px] font-medium text-content-muted uppercase tracking-wider">Generation Tools</h4>
              <button
                ref="addToolButtonRef"
                @click="toggleAddToolDropdown"
                class="text-[11px] text-blue-400 hover:text-blue-300 transition-colors font-medium"
              >
                + Add
              </button>
            </div>
            <div v-if="configuredTools.length > 0" class="bg-surface rounded-lg border border-edge overflow-hidden">
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
            <p v-else class="text-[11px] text-content-muted mt-1">No generation tools configured.</p>
          </div>
        </template>
      </div>
    </div>

    <!-- Add Tool Dropdown -->
    <Teleport to="body">
      <Transition name="fade">
        <div
          v-if="showAddToolDropdown"
          ref="addToolDropdownRef"
          class="fixed w-72 max-h-80 bg-surface border border-edge-subtle rounded-xl shadow-xl z-[1000] overflow-hidden"
          :style="addToolDropdownStyle"
        >
          <TaskTypeToolList
            ref="addToolListRef"
            :tools="addableTools"
            @select="(tool) => handleAddTool(tool.full_tool_id)"
          />
        </div>
      </Transition>
    </Teleport>

    <!-- Stimpack Editor Modal -->
    <StimpackEditorModal
      v-if="showStimpackEditor"
      :stimpack="editingStimpack"
      @close="showStimpackEditor = false"
      @save="handleStimpackSave"
    />

    <!-- Instructions Editor Modal -->
    <TextEditorModal
      v-if="showInstructionsModal"
      v-model="localInstructions"
      title="Additional Instructions"
      placeholder="Give the agent special instructions for this chat..."
      hint="Guide the agent's behavior for this chat. You can specify style preferences (e.g., 'always use photorealistic styles'), output formats (e.g., 'create sets of 4 images'), tool constraints (e.g., 'prefer Flux models over SDXL'), or specific generation parameters like LoRAs, CFG values, and sampling settings."
      @close="showInstructionsModal = false"
      @save="saveInstructions"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import ToolConfigRow from './ToolConfigRow.vue'
import TextEditorModal from './TextEditorModal.vue'
import TaskTypeToolList from '../TaskTypeToolList.vue'
import { useAgentPresetsApi, type AgentSettings, type ToolConfig } from '../../composables/useAgentPresetsApi'
import { useProvidersApi, type ProviderTool } from '../../composables/useProvidersApi'
import { useWebSocket } from '../../composables/useWebSocket'
import StimpackEditorModal from '../settings/StimpackEditorModal.vue'
import { useStimpacksApi, type StimpackDetail } from '../../composables/useStimpacksApi'

const props = defineProps<{
  chatId: number
  visible?: boolean
}>()

// Default visible to true if not provided
const isVisible = computed(() => props.visible ?? true)

const { getChatAgentSettings, updateChatAgentSettings } = useAgentPresetsApi()
const { listAllTools } = useProvidersApi()
const { on: onWsEvent } = useWebSocket()
const { getStimpack: getStimpackApi, updateStimpack: updateStimpackApi } = useStimpacksApi()

// Tabs

// State
const settings = ref<AgentSettings | null>(null)
const allTools = ref<ProviderTool[]>([])
const loadingTools = ref(false)

// Local state for editing (to avoid constant API calls)
const localInstructions = ref('')
const localToolConfig = ref<ToolConfig | null>(null)
const showInstructionsModal = ref(false)

// Add tool dropdown state
const showAddToolDropdown = ref(false)
const addToolButtonRef = ref<HTMLButtonElement | null>(null)
const addToolDropdownRef = ref<HTMLDivElement | null>(null)
const addToolDropdownPosition = ref({ top: 0, left: 0 })
const addToolListRef = ref<InstanceType<typeof TaskTypeToolList> | null>(null)


// WebSocket unsubscribe functions
const wsUnsubscribes: (() => void)[] = []

// Computed: tools that are explicitly configured (in allowed or denied lists)
const configuredToolIds = computed(() => {
  const allowed = localToolConfig.value?.allowed_tools || []
  const denied = localToolConfig.value?.denied_tools || []
  return new Set([...allowed, ...denied])
})

const configuredTools = computed(() => {
  return allTools.value.filter(tool => configuredToolIds.value.has(tool.full_tool_id))
})

// V2 agent tools — always shown
const V2_TOOLS = [
  { name: 'bash', label: 'Shell' },
  { name: 'run_code', label: 'Run Code' },
  { name: 'browse_web', label: 'Browsing Web' },
]

function getV2Permission(toolName: string): string {
  return localToolConfig.value?.v2_permissions?.[toolName] || 'ask'
}

async function setV2Permission(toolName: string, value: string) {
  if (!localToolConfig.value) return
  const v2 = { ...(localToolConfig.value.v2_permissions || {}) }
  if (value === 'ask') {
    delete v2[toolName]
  } else {
    v2[toolName] = value
  }
  const newConfig = { ...localToolConfig.value, v2_permissions: v2 }
  localToolConfig.value = newConfig
  try {
    settings.value = await updateChatAgentSettings(props.chatId, {
      tool_config: newConfig,
    })
  } catch (err) {
    console.error('Failed to update v2 permission:', err)
  }
}

// Tools available to add (not currently configured)
const addableTools = computed(() => {
  return allTools.value.filter(tool => !configuredToolIds.value.has(tool.full_tool_id))
})

const addToolDropdownStyle = computed(() => ({
  top: `${addToolDropdownPosition.value.top}px`,
  left: `${addToolDropdownPosition.value.left}px`,
}))

// Methods
async function loadSettings() {
  try {
    settings.value = await getChatAgentSettings(props.chatId)
    localInstructions.value = settings.value.additional_instructions || ''
    localToolConfig.value = settings.value.tool_config || {
      allowed_tools: [],
      denied_tools: [],
    }
  } catch (err) {
    console.error('Failed to load agent settings:', err)
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

async function refreshSettings() {
  await loadSettings()
}

async function saveInstructions() {
  if (settings.value?.additional_instructions === localInstructions.value) return

  try {
    settings.value = await updateChatAgentSettings(props.chatId, {
      additional_instructions: localInstructions.value || null,
    })
  } catch (err) {
    console.error('Failed to save instructions:', err)
  }
}

async function handleToolConfigUpdate(config: ToolConfig) {
  localToolConfig.value = config
  try {
    settings.value = await updateChatAgentSettings(props.chatId, {
      tool_config: config,
    })
  } catch (err) {
    console.error('Failed to save tool config:', err)
  }
}


// Add tool dropdown methods
function updateAddToolDropdownPosition() {
  if (addToolButtonRef.value) {
    const rect = addToolButtonRef.value.getBoundingClientRect()
    addToolDropdownPosition.value = {
      top: rect.bottom + 4,
      left: Math.max(8, Math.min(rect.right - 288, window.innerWidth - 296)),
    }
  }
}

function toggleAddToolDropdown() {
  showAddToolDropdown.value = !showAddToolDropdown.value
  if (showAddToolDropdown.value) {
    updateAddToolDropdownPosition()
    requestAnimationFrame(() => {
      addToolListRef.value?.reset()
    })
  }
}

function handleClickOutsideAddTool(event: MouseEvent) {
  const target = event.target as Element
  const isInsideButton = addToolButtonRef.value?.contains(target)
  const isInsideDropdown = addToolDropdownRef.value?.contains(target)
  if (!isInsideButton && !isInsideDropdown) {
    showAddToolDropdown.value = false
  }


  // Close stimpack menu if clicking outside
  if (openStimpackMenu.value && !(target as Element).closest?.('[data-stimpack-menu]')) {
    openStimpackMenu.value = null
  }
}

async function handleAddTool(toolId: string) {
  // Add tool to allowed_tools by default - create new object for reactivity
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
  // Remove from both allowed and denied lists - create new object for reactivity
  const current = localToolConfig.value

  const newConfig = {
    allowed_tools: (current?.allowed_tools || []).filter(id => id !== toolId),
    denied_tools: (current?.denied_tools || []).filter(id => id !== toolId),
    v2_permissions: { ...(current?.v2_permissions || {}) },
  }

  await handleToolConfigUpdate(newConfig)
}

function formatTaskType(taskType: string): string {
  if (!taskType) return ''
  return taskType
    .replace(/[-_]/g, ' ')
    .replace(/\b\w/g, char => char.toUpperCase())
}

// Stimpack editor modal state
const editingStimpack = ref<StimpackDetail | null>(null)
const showStimpackEditor = ref(false)
const openStimpackMenu = ref<string | null>(null)

function toggleStimpackMenu(name: string) {
  openStimpackMenu.value = openStimpackMenu.value === name ? null : name
}

async function openStimpackEditor(name: string) {
  try {
    editingStimpack.value = await getStimpackApi(name)
    showStimpackEditor.value = true
  } catch (err) {
    console.error('Failed to load stimpack:', err)
  }
}

async function handleStimpackSave(data: { name: string; display_name: string; description: string; tags: string[]; content: string }) {
  try {
    await updateStimpackApi(data.name, {
      display_name: data.display_name,
      description: data.description,
      tags: data.tags,
      content: data.content,
    })
    showStimpackEditor.value = false
    editingStimpack.value = null
  } catch (err) {
    console.error('Failed to save stimpack:', err)
  }
}

// Setup WebSocket subscriptions
function setupWebSocketSubscriptions() {
  // Listen for agent settings updates (HITL tool approval, external changes)
  wsUnsubscribes.push(onWsEvent('chat_agent_settings_updated', (data: any) => {
    if (data.chat_id !== props.chatId) return

    if (data.settings) {
      localInstructions.value = data.settings.additional_instructions || ''
      localToolConfig.value = data.settings.tool_config || {
        allowed_tools: [],
        denied_tools: [],
      }
      settings.value = data.settings
    }
  }))
}

function cleanupWebSocketSubscriptions() {
  wsUnsubscribes.forEach(unsub => unsub())
  wsUnsubscribes.length = 0
}

// Watch for chat changes
watch(() => props.chatId, () => {
  loadSettings()
}, { immediate: true })

onMounted(() => {
  loadTools()
  setupWebSocketSubscriptions()
  // Use mousedown instead of click: when clicking a category inside TaskTypeToolList,
  // the component re-renders and removes the clicked element from the DOM before the
  // click event bubbles. At that point contains() returns false, closing the menu prematurely.
  document.addEventListener('mousedown', handleClickOutsideAddTool)
})

onUnmounted(() => {
  cleanupWebSocketSubscriptions()
  document.removeEventListener('mousedown', handleClickOutsideAddTool)
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
