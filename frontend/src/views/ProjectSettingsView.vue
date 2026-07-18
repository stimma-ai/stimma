<template>
  <div class="flex-1 overflow-y-auto px-6 py-6">
    <div class="mx-auto max-w-3xl">

      <!-- Name -->
      <div class="mb-6">
        <h4 class="text-xs font-semibold text-content-secondary mb-3">Name</h4>
        <input
          v-model="localName"
          type="text"
          class="w-full bg-overlay-subtle text-content text-sm rounded-md px-3 py-2 border border-transparent placeholder:text-content-muted focus:border-accent focus-visible:ring-2 ring-accent/40 outline-none"
          placeholder="Untitled Project"
          @blur="saveGeneral"
        />
      </div>

      <!-- Agent Instructions -->
      <div class="mb-6">
        <h4 class="text-xs font-semibold text-content-secondary mb-3">Agent Instructions</h4>
        <textarea
          v-model="localInstructions"
          placeholder="Give the agent project-specific instructions..."
          rows="6"
          class="w-full bg-overlay-subtle text-content text-sm rounded-md px-3 py-2 border border-transparent placeholder:text-content-muted focus:border-accent focus-visible:ring-2 ring-accent/40 outline-none resize-none"
          @blur="saveAgentConfig"
        />
      </div>

      <!-- Memory -->
      <div class="mb-6">
        <h4 class="text-xs font-semibold text-content-secondary mb-1">Memory</h4>
        <p class="text-xs text-content-tertiary mb-3">
          Persistent context the agent remembers for this project. The agent can also update this.
        </p>
        <textarea
          v-model="localMemory"
          placeholder="No memories yet..."
          rows="6"
          class="w-full bg-overlay-subtle text-content text-sm rounded-md px-3 py-2 border border-transparent placeholder:text-content-muted focus:border-accent focus-visible:ring-2 ring-accent/40 outline-none resize-none"
          @blur="saveMemory"
        />
      </div>

      <!-- Tool permissions scoped to THIS project. Hidden when none (same reasoning
           as the chat panel — the default approval is global, so project-scoped
           entries are the exception, not the norm). -->
      <div v-if="configuredTools.length > 0" class="mb-6">
        <h4 class="text-xs font-semibold text-content-secondary mb-2">Tool Permissions for this Project</h4>
        <div class="border border-edge-subtle rounded-lg overflow-hidden">
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

      <!-- Delete Project -->
      <div class="mt-10 flex items-start justify-between gap-4">
        <div>
          <h4 class="text-xs font-semibold text-red-400">Delete Project</h4>
          <p class="mt-1 text-xs text-content-tertiary">
            Delete this project, its boards, and chats. Assets will remain in All Assets.
          </p>
        </div>
        <Button variant="danger-ghost" class="flex-shrink-0" @click="openDeleteProjectModal">
          Delete
        </Button>
      </div>

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
import { computed, ref, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import ConfirmModal from '../components/ConfirmModal.vue'
import ToolConfigRow from '../components/chat/ToolConfigRow.vue'
import Button from '../components/ui/Button.vue'
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

async function handleRemoveTool(toolId) {
  const current = localToolConfig.value

  const newConfig = {
    allowed_tools: (current?.allowed_tools || []).filter(id => id !== toolId),
    denied_tools: (current?.denied_tools || []).filter(id => id !== toolId),
    v2_permissions: { ...(current?.v2_permissions || {}) },
  }

  await handleToolConfigUpdate(newConfig)
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
})
</script>
