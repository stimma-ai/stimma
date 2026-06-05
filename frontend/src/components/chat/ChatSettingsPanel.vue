<template>
  <div
    class="flex-shrink-0 bg-base border-l border-edge flex flex-col transition-all duration-300 overflow-hidden"
    :class="isVisible ? 'w-80 opacity-100' : 'w-0 opacity-0 pointer-events-none'"
  >
    <!-- Full panel content -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <!-- Tab Bar -->
      <div class="px-3 pt-3 pb-2 flex justify-center">
        <div class="inline-flex rounded-lg bg-surface p-0.5">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            @click="activeTab = tab.id"
            class="px-3 py-1 text-xs font-medium rounded-md transition-colors"
            :class="activeTab === tab.id
              ? 'bg-surface-raised text-content'
              : 'text-content-tertiary hover:text-content'"
          >
            {{ tab.label }}
          </button>
        </div>
      </div>

      <!-- Agent Tab -->
      <div v-if="activeTab === 'agent'" class="flex-1 flex flex-col overflow-hidden">
        <div class="px-3 pb-3 flex-1 overflow-y-auto pt-2">
          <!-- Additional Instructions -->
          <div class="flex items-center justify-between mb-1">
            <label class="text-xs font-medium text-content-tertiary">Additional Instructions</label>
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
            rows="8"
            class="w-full bg-surface text-content text-sm border border-edge rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 resize-none"
            @blur="saveInstructions"
          />
          <p class="text-[11px] text-content-muted mt-2 leading-relaxed">
            Guide the agent's behavior. Try: style preferences, output formats, tool constraints, or specific parameters like LoRAs and CFG values.
          </p>

          <!-- Skills -->
          <div class="mt-4">
            <label class="text-xs font-medium text-content-tertiary mb-1.5 block">Skills</label>
            <p class="text-[11px] text-content-muted mb-2">
              Activate a skill to guide the agent's approach. Skills stay active for the rest of the conversation.
            </p>
            <div v-if="loadingSkills" class="text-[11px] text-content-muted py-2">Loading...</div>
            <div v-else-if="skills.length > 0" class="bg-surface rounded-lg border border-edge">
              <div
                v-for="(skill, idx) in skills"
                :key="skill.name"
                class="flex items-center justify-between px-3 py-2 transition-colors"
                :class="idx < skills.length - 1 ? 'border-b border-edge' : ''"
              >
                <div class="min-w-0 mr-2">
                  <div class="flex items-center gap-2">
                    <span
                      class="w-1.5 h-1.5 rounded-full flex-shrink-0"
                      :class="isSkillInvoked(skill.name) ? 'bg-blue-500' : 'bg-white/10'"
                    />
                    <span class="text-xs leading-4" :class="isSkillInvoked(skill.name) ? 'text-content font-medium' : 'text-content-secondary'">{{ skill.display_name || skill.name }}</span>
                  </div>
                  <p v-if="skill.description" class="text-[10px] text-content-muted truncate mt-0.5 pl-3.5">{{ skill.description }}</p>
                </div>
                <div class="flex items-center flex-shrink-0">
                  <button
                    v-if="!isSkillInvoked(skill.name)"
                    @click="invokeSkill(skill.name)"
                    :disabled="invokingSkill === skill.name"
                    class="text-[10px] px-2 py-0.5 rounded text-blue-400 hover:text-blue-300 hover:bg-blue-500/10 transition-colors disabled:opacity-50"
                  >
                    {{ invokingSkill === skill.name ? 'Activating...' : 'Activate' }}
                  </button>
                  <span v-else class="text-[10px] text-content-muted px-2">Active</span>
                </div>
              </div>
            </div>
            <p v-else class="text-[11px] text-content-muted">No skills available.</p>
          </div>
        </div>
      </div>

      <!-- Permissions Tab -->
      <div v-else-if="activeTab === 'permissions'" class="flex-1 flex flex-col min-h-0">
        <!-- Loading state -->
        <div v-if="loadingTools" class="flex-1 flex items-center justify-center text-content-muted text-sm">
          Loading tools...
        </div>

        <template v-else>
          <div class="flex-1 overflow-y-auto px-3 pt-3 pb-3 space-y-4">
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

    <!-- Skill Editor Modal -->
    <SkillEditorModal
      v-if="showSkillEditor"
      :skill="editingSkill"
      @close="showSkillEditor = false"
      @save="handleSkillSave"
    />

    <!-- Revert Skill Confirmation -->
    <ConfirmModal
      :show="showRevertConfirm"
      title="Revert Skill?"
      :message="`Revert &quot;${revertingSkill?.display_name || revertingSkill?.name}&quot; to the original version? Your changes will be lost.`"
      confirm-text="Revert"
      @confirm="executeRevertSkill"
      @cancel="showRevertConfirm = false"
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
import ConfirmModal from '../ConfirmModal.vue'
import TaskTypeToolList from '../TaskTypeToolList.vue'
import { useAgentPresetsApi, type AgentSettings, type ToolConfig } from '../../composables/useAgentPresetsApi'
import { useProvidersApi, type ProviderTool } from '../../composables/useProvidersApi'
import { useWebSocket } from '../../composables/useWebSocket'
import SkillEditorModal from '../settings/SkillEditorModal.vue'
import { useSkillsApi, type Skill, type SkillDetail } from '../../composables/useSkillsApi'

const props = defineProps<{
  chatId: number
  visible?: boolean
}>()

// Default visible to true if not provided
const isVisible = computed(() => props.visible ?? true)

const { getChatAgentSettings, updateChatAgentSettings } = useAgentPresetsApi()
const { listAllTools } = useProvidersApi()
const { on: onWsEvent } = useWebSocket()
const { listSkills: listSkillsApi, getSkill: getSkillApi, updateSkill: updateSkillApi } = useSkillsApi()

// Tabs
const tabs = [
  { id: 'agent', label: 'Agent' },
  { id: 'permissions', label: 'Tool Permissions' },
]
const activeTab = ref('agent')

// State
const settings = ref<AgentSettings | null>(null)
const allTools = ref<ProviderTool[]>([])
const loadingTools = ref(false)

// Local state for editing (to avoid constant API calls)
const localInstructions = ref('')
const localToolConfig = ref<ToolConfig | null>(null)
const showInstructionsModal = ref(false)

// Skills state
const skills = ref<Skill[]>([])
const loadingSkills = ref(false)

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


  // Close skill menu if clicking outside
  if (openSkillMenu.value && !(target as Element).closest?.('[data-skill-menu]')) {
    openSkillMenu.value = null
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

// Skills methods
async function loadSkills() {
  loadingSkills.value = true
  try {
    skills.value = await listSkillsApi()
  } catch (err) {
    console.error('Failed to load skills:', err)
  } finally {
    loadingSkills.value = false
  }
}

// Track which skills have been invoked in this chat (from skill_injection items)
const invokedSkills = ref<Set<string>>(new Set())
const invokingSkill = ref<string | null>(null)

function isSkillInvoked(name: string): boolean {
  return invokedSkills.value.has(name)
}

async function invokeSkill(name: string) {
  if (invokedSkills.value.has(name)) return
  invokingSkill.value = name
  try {
    const response = await fetch(`/api/chats/${props.chatId}/invoke-skill`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    if (response.ok) {
      invokedSkills.value = new Set([...invokedSkills.value, name])
    }
  } catch (err) {
    console.error('Failed to invoke skill:', err)
  } finally {
    invokingSkill.value = null
  }
}

async function loadInvokedSkills() {
  try {
    const response = await fetch(`/api/chats/${props.chatId}/invoked-skills`)
    if (response.ok) {
      const data = await response.json()
      invokedSkills.value = new Set(data.skills || [])
    }
  } catch {
    // Fallback: will be populated via WebSocket events
  }
}

// Skill editor modal state
const editingSkill = ref<SkillDetail | null>(null)
const showSkillEditor = ref(false)
const openSkillMenu = ref<string | null>(null)

function toggleSkillMenu(name: string) {
  openSkillMenu.value = openSkillMenu.value === name ? null : name
}

async function openSkillEditor(name: string) {
  try {
    editingSkill.value = await getSkillApi(name)
    showSkillEditor.value = true
  } catch (err) {
    console.error('Failed to load skill:', err)
  }
}

async function handleSkillSave(data: { name: string; display_name: string; description: string; tags: string[]; content: string }) {
  try {
    await updateSkillApi(data.name, {
      display_name: data.display_name,
      description: data.description,
      tags: data.tags,
      content: data.content,
    })
    showSkillEditor.value = false
    editingSkill.value = null
    await loadSkills()
  } catch (err) {
    console.error('Failed to save skill:', err)
  }
}

const showRevertConfirm = ref(false)
const revertingSkill = ref<Skill | null>(null)

function handleRevertSkill(skill: Skill) {
  revertingSkill.value = skill
  showRevertConfirm.value = true
}

async function executeRevertSkill() {
  if (!revertingSkill.value) return
  showRevertConfirm.value = false
  try {
    const { revertSkill } = useSkillsApi()
    await revertSkill(revertingSkill.value.name)
    await loadSkills()
  } catch (err) {
    console.error('Failed to revert skill:', err)
  } finally {
    revertingSkill.value = null
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

  // Listen for skill invocations (from agent or API)
  wsUnsubscribes.push(onWsEvent('chat_item_created', (data: any) => {
    if (data.chat_id !== props.chatId) return
    const item = data.item
    if (item?.item_type === 'skill_injection') {
      const meta = typeof item.item_metadata === 'string' ? JSON.parse(item.item_metadata) : item.item_metadata
      if (meta?.skill_name) {
        invokedSkills.value = new Set([...invokedSkills.value, meta.skill_name])
      }
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
  loadInvokedSkills()
}, { immediate: true })

// Load tools and setup WebSocket on mount
function handleSkillsChanged() {
  loadSkills()
}

onMounted(() => {
  loadTools()
  loadSkills()
  loadInvokedSkills()
  setupWebSocketSubscriptions()
  window.addEventListener('skills-changed', handleSkillsChanged)
  // Use mousedown instead of click: when clicking a category inside TaskTypeToolList,
  // the component re-renders and removes the clicked element from the DOM before the
  // click event bubbles. At that point contains() returns false, closing the menu prematurely.
  document.addEventListener('mousedown', handleClickOutsideAddTool)
})

onUnmounted(() => {
  cleanupWebSocketSubscriptions()
  window.removeEventListener('skills-changed', handleSkillsChanged)
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
