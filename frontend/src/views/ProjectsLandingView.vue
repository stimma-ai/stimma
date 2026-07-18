<template>
  <div class="flex h-full flex-col bg-base">
    <div class="flex items-center justify-between border-b border-edge-subtle px-6 py-5">
      <span class="text-xl font-semibold leading-none text-content">Projects</span>

      <div class="flex items-center gap-3">
        <button
          class="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-content-tertiary transition-colors hover:bg-overlay-subtle hover:text-content-secondary"
          @click="createNewProject"
        >
          <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          <span>New</span>
        </button>
        <div class="relative">
        <svg class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <input v-no-autocorrect
          v-model="searchQuery"
          type="text"
          placeholder="Search projects..."
          class="w-48 rounded-lg border border-edge-subtle bg-overlay-subtle py-1.5 pl-9 pr-3 text-sm text-content-secondary placeholder-white/30 focus:border-accent focus:outline-none"
        />
      </div>
      </div>
    </div>

    <div class="flex-1 overflow-y-auto px-6 py-6">
      <div v-if="loading" class="py-20 text-center text-content-muted">Loading projects...</div>
      <div v-else-if="filteredProjects.length === 0 && projects.length === 0" class="flex h-64 flex-col items-center justify-center text-center">
        <p class="mb-2 text-content-muted">No projects yet</p>
        <p class="text-sm text-content-muted">Create a project to give chats, assets, boards, and the agent a shared working world.</p>
      </div>
      <div v-else-if="filteredProjects.length === 0" class="flex h-64 flex-col items-center justify-center text-center">
        <p class="mb-2 text-content-muted">No projects match your search</p>
      </div>

      <div v-else class="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <button
          v-for="project in filteredProjects"
          :key="project.id"
          class="group rounded-lg border border-edge-subtle bg-overlay-faint p-5 text-left transition-all hover:border-edge hover:bg-overlay-subtle"
          @click="handleCardClick($event, project)"
          @contextmenu="handleProjectContextMenu($event, project)"
        >
          <div class="flex items-start gap-4">
            <EntityIcon type="project" size="lg" />

            <!-- Title + timestamp -->
            <div class="min-w-0 flex-1">
              <input
                v-if="editingProjectId === project.id"
                ref="nameInputRef"
                v-model="editingName"
                type="text"
                placeholder="Name this project..."
                class="w-full truncate rounded bg-transparent text-sm font-semibold text-content placeholder-content-muted/50 placeholder:italic focus:outline-none"
                @click.stop
                @blur="saveProjectName(project)"
                @keydown.enter.prevent="saveProjectName(project)"
                @keydown.escape.prevent="cancelEditing"
              />
              <h2
                v-else
                class="truncate text-sm font-semibold"
                :class="project.name ? 'text-content' : 'italic text-content-muted'"
                @click.stop="!project.name && startEditing(project)"
              >
                {{ project.name || 'Name this project...' }}
              </h2>
              <p class="mt-0.5 text-xs text-content-muted">
                Updated {{ formatRelativeTime(project.updated_at) }}
              </p>
            </div>
          </div>

          <!-- Stats with icons -->
          <div class="mt-4 flex items-center gap-4 text-xs text-content-muted">
            <span class="flex items-center gap-1.5">
              <!-- Image stack icon -->
              <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M18 3.75H6A2.25 2.25 0 003.75 6v12A2.25 2.25 0 006 20.25h12A2.25 2.25 0 0020.25 18V6A2.25 2.25 0 0018 3.75z" />
              </svg>
              {{ project.asset_count || 0 }}
            </span>
            <span class="flex items-center gap-1.5">
              <!-- Chat bubble icon -->
              <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H8.25m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0H12m4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 01-2.555-.337A5.972 5.972 0 015.41 20.97a5.969 5.969 0 01-.474-.065 4.48 4.48 0 00.978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" />
              </svg>
              {{ project.chat_count || 0 }}
            </span>
            <span class="flex items-center gap-1.5">
              <!-- Grid/board icon -->
              <svg class="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
              </svg>
              {{ project.board_count || 0 }}
            </span>
          </div>
        </button>
      </div>
    </div>

    <EntityContextMenu
      @open="handleContextMenuOpen"
      @delete="handleContextMenuDelete"
      @rename="handleContextMenuRename"
    />
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
import { computed, nextTick, onActivated, onMounted, onUnmounted, ref , watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConfirmModal from '../components/ConfirmModal.vue'
import EntityContextMenu from '../components/EntityContextMenu.vue'
import EntityIcon from '../components/EntityIcon.vue'
import { useEntityContextMenu } from '../composables/useEntityContextMenu'
import { useMediaApi } from '../composables/useMediaApi'
import { useWebSocket } from '../composables/useWebSocket'

const router = useRouter()
const entityContextMenu = useEntityContextMenu()
const { createProject, deleteProject, getProjects, updateProject } = useMediaApi()
const { on: onWsEvent } = useWebSocket()

const projects = ref([])
const loading = ref(false)
const searchQuery = ref('')

// Global search "View all" handoff: seed the local filter from ?q= so the
// omnibox's per-type result caps never hide matches for good.
const route = useRoute()
watch(() => route.query.q, (q) => {
  if (typeof q === 'string' && q) searchQuery.value = q
}, { immediate: true })
const showDeleteModal = ref(false)
const pendingDeleteProject = ref(null)
const editingProjectId = ref(null)
const editingName = ref('')
const nameInputRef = ref(null)

const filteredProjects = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return projects.value
  return projects.value.filter((project) => {
    return (project.name || '').toLowerCase().includes(query)
  })
})

const deleteConfirmMessage = computed(() => {
  const project = pendingDeleteProject.value
  const projectName = project?.name?.trim()
  const assetCount = project?.asset_count || 0
  const chatCount = project?.chat_count || 0
  const boardCount = project?.board_count || 0
  const label = projectName ? `"${projectName}"` : 'this project'
  const boardLabel = boardCount === 1 ? 'board' : 'boards'
  const chatLabel = chatCount === 1 ? 'chat' : 'chats'
  const assetLabel = assetCount === 1 ? 'asset' : 'assets'

  return `This cannot be undone.

Deleting ${label} will delete the project, ${assetCount} ${assetLabel}, ${chatCount} ${chatLabel}, and ${boardCount} ${boardLabel}.

Attached assets will be moved to trash. Chats and boards will be deleted with the project.`
})

async function loadProjects() {
  // Only show the loading state on the initial fetch — background refreshes
  // (KeepAlive reactivation, websocket events) swap the list in place.
  if (projects.value.length === 0) loading.value = true
  try {
    projects.value = await getProjects()
  } finally {
    loading.value = false
  }
}

async function createNewProject() {
  const project = await createProject('', '')
  router.push({ name: 'project-overview', params: { id: project.id }, query: { rename: '1' } })
}

function handleProjectContextMenu(event, project) {
  entityContextMenu.show({
    event,
    entityType: 'project',
    entityId: project.id,
    entityName: project.name || '',
    isSelected: false,
    selectedCount: 1
  })
}

function handleContextMenuOpen(entityType, entityId) {
  if (entityType !== 'project') return
  openProject(entityId)
}

async function handleContextMenuDelete(entityType, entityId) {
  if (entityType !== 'project') return
  const project = projects.value.find((item) => item.id === entityId) || null
  pendingDeleteProject.value = project
  showDeleteModal.value = true
}

async function handleContextMenuRename(entityType, entityId, entityName) {
  router.push({ name: 'project-overview', params: { id: entityId }, query: { rename: '1' } })
}

function cancelDeleteProject() {
  showDeleteModal.value = false
  pendingDeleteProject.value = null
}

async function confirmDeleteProject() {
  const projectId = pendingDeleteProject.value?.id
  if (!projectId) {
    cancelDeleteProject()
    return
  }

  await deleteProject(projectId)
  projects.value = projects.value.filter((project) => project.id !== projectId)
  cancelDeleteProject()
}

function formatRelativeTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''

  const diffMs = Date.now() - date.getTime()
  const diffMinutes = Math.max(0, Math.floor(diffMs / 60000))

  if (diffMinutes < 1) return 'just now'
  if (diffMinutes < 60) return `${diffMinutes}m ago`

  const diffHours = Math.floor(diffMinutes / 60)
  if (diffHours < 24) return `${diffHours}h ago`

  const diffDays = Math.floor(diffHours / 24)
  if (diffDays < 7) return `${diffDays}d ago`

  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric'
  })
}

function handleCardClick(event, project) {
  if (editingProjectId.value === project.id) return
  openProject(project.id)
}

async function startEditing(project) {
  editingProjectId.value = project.id
  editingName.value = project.name || ''
  await nextTick()
  const input = nameInputRef.value
  const el = Array.isArray(input) ? input[0] : input
  el?.focus()
}

async function saveProjectName(project) {
  const name = editingName.value.trim()
  editingProjectId.value = null
  if (!name) return
  const updated = await updateProject(project.id, { name })
  project.name = updated.name
}

function cancelEditing() {
  editingProjectId.value = null
  editingName.value = ''
}

function openProject(id) {
  router.push({ name: 'project-overview', params: { id } })
}

onMounted(loadProjects)

// This view lives under KeepAlive, so onMounted only fires once — refetch on
// reactivation and on project websocket events so the list never goes stale.
let activatedOnce = false
onActivated(() => {
  if (activatedOnce) loadProjects()
  activatedOnce = true
})

const unsubscribeWs = [
  onWsEvent('project_created', loadProjects),
  onWsEvent('project_updated', loadProjects),
  onWsEvent('project_deleted', loadProjects),
]
onUnmounted(() => unsubscribeWs.forEach((unsubscribe) => unsubscribe()))
</script>
