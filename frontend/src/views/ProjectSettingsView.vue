<template>
  <div class="flex-1 overflow-y-auto px-6 py-6">
    <div class="mx-auto max-w-3xl">

      <!-- Name -->
      <div class="mb-6">
        <h4 class="text-sm font-medium text-content-secondary mb-3">Name</h4>
        <input
          v-model="localName"
          type="text"
          class="w-full bg-base text-content text-sm border border-edge rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500"
          placeholder="Untitled Project"
          @blur="saveGeneral"
        />
      </div>

      <!-- Agent Instructions -->
      <div class="mb-6">
        <h4 class="text-sm font-medium text-content-secondary mb-3">Agent Instructions</h4>
        <textarea
          v-model="localInstructions"
          placeholder="Give the agent project-specific instructions..."
          rows="6"
          class="w-full bg-base text-content text-sm border border-edge rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 resize-none"
          @blur="saveAgentConfig"
        />
      </div>

      <!-- Memory -->
      <div class="mb-6">
        <h4 class="text-sm font-medium text-content-secondary mb-1">Memory</h4>
        <p class="text-xs text-content-tertiary mb-3">
          Persistent context the agent remembers for this project. The agent can also update this.
        </p>
        <textarea
          v-model="localMemory"
          placeholder="No memories yet..."
          rows="6"
          class="w-full bg-base text-content text-sm border border-edge rounded-lg px-3 py-2 focus:outline-none focus:border-blue-500 resize-none"
          @blur="saveMemory"
        />
      </div>

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
        <div v-if="configuredTools.length > 0" class="bg-surface-overlay border border-edge rounded-lg overflow-hidden">
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

      <!-- Delete Project -->
      <div class="mt-10 flex items-start justify-between gap-4">
        <div>
          <h4 class="text-sm font-medium text-content-secondary">Delete Project</h4>
          <p class="mt-1 text-xs text-content-tertiary">
            Delete this project, its boards, and chats. Assets will remain in All Assets.
          </p>
        </div>
        <button
          class="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm font-medium text-red-400 transition-colors hover:bg-red-500/15 flex-shrink-0"
          @click="openDeleteProjectModal"
        >
          Delete
        </button>
      </div>

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
              gradient-id="stimma-gradient-project-permissions"
              @select="handleAddToolFromList"
            />
          </div>
        </Transition>
      </Teleport>

    </div>

    <ConfirmModal
      :show="showDeleteModal"
      title="Delete Project"
      :message="deleteConfirmMessage"
      confirm-text="Delete"
      cancel-text="Cancel"
      @confirm="confirmDeleteProject"
      @cancel="cancelDeleteProject"
    />
  </div>
</template>

<script setup>
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import ConfirmModal from '../components/ConfirmModal.vue'
import ToolConfigRow from '../components/chat/ToolConfigRow.vue'
import TaskTypeToolList from '../components/TaskTypeToolList.vue'
import { useMediaApi } from '../composables/useMediaApi'
import { useProvidersApi } from '../composables/useProvidersApi'

const props = defineProps({
  project: {
    type: Object,
    required: true
  }
})

const router = useRouter()
const { updateProject, deleteProject } = useMediaApi()
const { listAllTools } = useProvidersApi()

// General state
const localName = ref('')
const showDeleteModal = ref(false)

// Agent state
const localInstructions = ref('')
const localMemory = ref('')
const localToolConfig = ref({
  allowed_tools: [],
  denied_tools: [],
  v2_permissions: {},
})

// Tools state
const allTools = ref([])
const loadingTools = ref(false)

// Add tool dropdown state
const showAddToolDropdown = ref(false)
const addToolButtonRef = ref(null)
const addToolDropdownRef = ref(null)
const addToolListRef = ref(null)
const addToolDropdownPosition = ref({ top: 0, left: 0 })

const deleteConfirmMessage = computed(() => {
  const projectName = props.project?.name?.trim()
  if (projectName) {
    return `Are you sure you want to delete "${projectName}"?`
  }
  return 'Are you sure you want to delete this project?'
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

const unconfiguredTools = computed(() => {
  return allTools.value.filter(tool => !configuredToolIds.value.has(tool.full_tool_id))
})

const addToolDropdownStyle = computed(() => ({
  top: `${addToolDropdownPosition.value.top}px`,
  left: `${addToolDropdownPosition.value.left}px`,
}))

function normalizeToolConfig(config = {}) {
  return {
    allowed_tools: [...(config.allowed_tools || [])],
    denied_tools: [...(config.denied_tools || [])],
    // Preserve any existing v2_permissions verbatim — there is no longer a UI to set them
    // per project; shell permission is granted per-chat from the approval prompt.
    v2_permissions: { ...(config.v2_permissions || {}) },
  }
}

// Sync from project prop
watch(() => props.project, (project) => {
  if (!project) return
  localName.value = project.name || ''
  localInstructions.value = project.additional_instructions || ''
  localMemory.value = project.memory || ''
  localToolConfig.value = normalizeToolConfig(project.agent_tool_config || {})
}, { immediate: true, deep: true })

// Tool config helpers
async function handleToolConfigUpdate(config) {
  localToolConfig.value = config
  await saveAgentConfig()
}

async function handleAddToolFromList(tool) {
  await handleAddTool(tool.full_tool_id)
}

async function handleAddTool(toolId) {
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

async function handleRemoveTool(toolId) {
  const current = localToolConfig.value

  const newConfig = {
    allowed_tools: (current?.allowed_tools || []).filter(id => id !== toolId),
    denied_tools: (current?.denied_tools || []).filter(id => id !== toolId),
    v2_permissions: { ...(current?.v2_permissions || {}) },
  }

  await handleToolConfigUpdate(newConfig)
}

// Add tool dropdown methods
function updateAddToolDropdownPosition() {
  if (addToolButtonRef.value) {
    const rect = addToolButtonRef.value.getBoundingClientRect()
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
    setTimeout(() => addToolListRef.value?.reset(), 0)
  }
}

function handleClickOutside(e) {
  const target = e.target

  if (showAddToolDropdown.value) {
    const isInsideButton = addToolButtonRef.value?.contains(target)
    const isInsideDropdown = addToolDropdownRef.value?.contains(target)
    if (!isInsideButton && !isInsideDropdown) {
      showAddToolDropdown.value = false
    }
  }
}

// Save methods
async function saveGeneral() {
  const updated = await updateProject(props.project.id, {
    name: localName.value,
  })
  Object.assign(props.project, updated)
}

async function saveMemory() {
  if (props.project.memory === localMemory.value) return
  const updated = await updateProject(props.project.id, {
    memory: localMemory.value,
  })
  Object.assign(props.project, updated)
}

async function saveAgentConfig() {
  const v2Permissions = Object.fromEntries(
    Object.entries(localToolConfig.value.v2_permissions || {}).filter(([, value]) => value && value !== 'ask')
  )
  const updated = await updateProject(props.project.id, {
    additional_instructions: localInstructions.value,
    agent_tool_config: {
      allowed_tools: localToolConfig.value.allowed_tools || [],
      denied_tools: localToolConfig.value.denied_tools || [],
      v2_permissions: v2Permissions,
    },
  })
  Object.assign(props.project, updated)
}

// Load tools
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

// Delete project
function openDeleteProjectModal() {
  showDeleteModal.value = true
}

function cancelDeleteProject() {
  showDeleteModal.value = false
}

async function confirmDeleteProject() {
  await deleteProject(props.project.id)
  showDeleteModal.value = false
  router.push({ name: 'projects' })
}

onMounted(() => {
  loadTools()
  document.addEventListener('mousedown', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('mousedown', handleClickOutside)
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
