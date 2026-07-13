<template>
  <div class="flex flex-col max-h-[420px]">
    <!-- Search -->
    <div class="px-2 py-1.5 border-b border-edge-subtle flex-shrink-0">
      <div class="relative">
        <svg class="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <input
          ref="searchInput"
          v-model="searchQuery"
          type="text"
          placeholder="Find a project"
          class="w-full bg-overlay-subtle border border-edge-subtle rounded px-2 py-1 pl-7 text-xs text-content placeholder:text-content-muted focus:outline-none focus:border-edge"
        />
      </div>
    </div>

    <div class="overflow-y-auto flex-1">
      <!-- New Project button (move mode only) -->
      <button
        v-if="mode === 'move'"
        :disabled="creating"
        class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        @click="handleCreateProject"
      >
        <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
        <span>{{ creating ? 'Creating...' : 'New project' }}</span>
      </button>

      <!-- "No Project" option (move mode only) -->
      <button
        v-if="mode === 'move'"
        class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        @click="$emit('select', null)"
      >
        <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 12H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span>No Project</span>
        <svg v-if="currentProjectId == null" class="w-3.5 h-3.5 ml-auto text-blue-500" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
        </svg>
      </button>

      <div v-if="mode === 'move'" class="border-t border-edge-subtle my-1"></div>

      <!-- Loading -->
      <div v-if="loading" class="px-3 py-2 text-xs text-content-tertiary">Loading projects...</div>
      <div v-else-if="filteredProjects.length === 0" class="px-3 py-2 text-xs text-content-tertiary">No matching projects</div>

      <!-- Project list -->
      <button
        v-for="project in filteredProjects"
        :key="project.id"
        :disabled="addingToProjectId === project.id"
        class="w-full px-3 py-2 text-left text-xs text-content hover:bg-overlay-light flex items-center gap-2"
        @click="handleProjectClick(project)"
      >
        <!-- Archive box icon -->
        <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="m20.25 7.5-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z" />
        </svg>
        <span class="flex-1 min-w-0 truncate" :class="project.name ? '' : 'italic text-content-muted'">{{ project.name || 'Untitled' }}</span>
        <!-- Checkmark for current project (move mode only) -->
        <svg v-if="mode === 'move' && currentProjectId === project.id" class="w-3.5 h-3.5 flex-shrink-0 text-blue-500" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import { useMediaApi } from '../composables/useMediaApi'
import { useAssetApi } from '../composables/useAssetApi'

const props = defineProps({
  mediaIds: {
    type: Array,
    default: () => []
  },
  assetIds: {
    type: Array,
    default: () => []
  },
  mode: {
    type: String,
    default: 'assign'
  },
  currentProjectId: {
    type: Number,
    default: null
  }
})

const emit = defineEmits(['select', 'added', 'close'])

const { getProjects, createProject, addMediaToProject } = useMediaApi()
const { addToProject: addAssetsToProject } = useAssetApi()

const searchInput = ref(null)
const searchQuery = ref('')
const loading = ref(false)
const creating = ref(false)
const projects = ref([])
const addingToProjectId = ref(null)

const filteredProjects = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return projects.value
  return projects.value.filter((p) => (p.name || '').toLowerCase().includes(query))
})

async function loadProjects() {
  loading.value = true
  try {
    projects.value = await getProjects()
  } catch (err) {
    console.error('Failed to load projects:', err)
  } finally {
    loading.value = false
  }
}

async function handleProjectClick(project) {
  if (props.mode === 'move') {
    emit('select', project.id)
    return
  }

  // Assign mode - add and dismiss
  if (addingToProjectId.value != null) return
  addingToProjectId.value = project.id
  try {
    if (props.assetIds.length > 0) {
      await addAssetsToProject(project.id, props.assetIds)
    } else {
      await addMediaToProject(project.id, props.mediaIds)
    }
    emit('added', project.id)
    emit('close')
  } catch (err) {
    console.error('Failed to add to project:', err)
  } finally {
    addingToProjectId.value = null
  }
}

async function handleCreateProject() {
  if (creating.value) return
  creating.value = true
  try {
    const project = await createProject('')
    projects.value.unshift(project)
    emit('select', project.id)
  } catch (err) {
    console.error('Failed to create project:', err)
  } finally {
    creating.value = false
  }
}

onMounted(async () => {
  await loadProjects()
  await nextTick()
  searchInput.value?.focus()
})
</script>
