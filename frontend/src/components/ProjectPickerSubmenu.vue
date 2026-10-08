<template>
  <div class="flex flex-col max-h-[420px]">
    <!-- Search -->
    <div class="px-2 py-1.5 border-b border-edge-subtle flex-shrink-0">
      <div class="relative">
        <svg class="w-3.5 h-3.5 absolute left-2 top-1/2 -translate-y-1/2 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <input
          ref="searchInput"
          v-model="searchQuery"
          type="text"
          placeholder="Find a project"
          class="w-full compact:min-h-11 bg-overlay-subtle border border-edge-subtle rounded px-2 py-1 pl-7 text-xs text-content placeholder:text-content-muted focus:outline-none focus:border-edge"
        />
      </div>
    </div>

    <div class="overflow-y-auto flex-1">
      <!-- New Project button (move mode only) -->
      <button
        v-if="mode === 'move'"
        :disabled="creating"
        class="w-full compact:min-h-11 px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        @click="handleCreateProject"
      >
        <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
        <span>{{ creating ? 'Creating...' : 'New project' }}</span>
      </button>

      <!-- "No Project" option (move mode only) -->
      <button
        v-if="mode === 'move'"
        class="w-full compact:min-h-11 px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
        @click="$emit('select', null)"
      >
        <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="1.75" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 12H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <span>No Project</span>
        <svg v-if="currentProjectId == null" class="w-3.5 h-3.5 ml-auto text-accent" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
        </svg>
      </button>

      <div v-if="mode === 'move'" class="border-t border-edge-subtle my-1"></div>

      <!-- Loading -->
      <div v-if="loading" class="px-3 py-2 text-xs text-content-tertiary">Loading projects...</div>
      <div v-else-if="filteredProjects.length === 0" class="px-3 py-2 text-xs text-content-tertiary">No matching projects</div>

      <!-- Project list. In assign mode each row shows whether the targets are
           in that project and toggles membership; the current project is pinned
           to the top. -->
      <template v-for="(project, index) in orderedProjects" :key="project.id">
        <button
          :disabled="addingToProjectId === project.id"
          :aria-checked="mode === 'assign' ? (rowState(project.id) === 'all' ? 'true' : rowState(project.id) === 'some' ? 'mixed' : 'false') : undefined"
          :role="mode === 'assign' ? 'menuitemcheckbox' : undefined"
          class="w-full compact:min-h-11 px-3 py-2 text-left text-xs text-content hover:bg-overlay-subtle flex items-center gap-2"
          @click="handleProjectClick(project)"
        >
          <!-- Archive box icon -->
          <svg class="w-4 h-4 flex-shrink-0 text-content-tertiary" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" d="m20.25 7.5-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z" />
          </svg>
          <span class="flex-1 min-w-0 truncate" :class="project.name ? '' : 'italic text-content-muted'">{{ project.name || 'Untitled' }}</span>
          <span v-if="mode === 'assign' && isPinned(project.id)" class="flex-shrink-0 text-[10px] text-content-muted">Current</span>
          <!-- Checkmark: current project (move mode) or full membership (assign mode) -->
          <svg
            v-if="(mode === 'move' && currentProjectId === project.id) || (mode === 'assign' && rowState(project.id) === 'all')"
            class="w-3.5 h-3.5 flex-shrink-0 text-accent" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
          </svg>
          <!-- Dash: some of the selected items are in this project -->
          <svg
            v-else-if="mode === 'assign' && rowState(project.id) === 'some'"
            class="w-3.5 h-3.5 flex-shrink-0 text-accent" fill="none" viewBox="0 0 24 24" stroke-width="2.5" stroke="currentColor"
          >
            <path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14" />
          </svg>
          <span v-else-if="mode === 'assign'" class="w-3.5 h-3.5 flex-shrink-0" aria-hidden="true"></span>
        </button>
        <div v-if="mode === 'assign' && index === 0 && isPinned(project.id) && orderedProjects.length > 1" class="border-t border-edge-subtle my-1"></div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { useViewport } from '../composables/useViewport'
import { addToast } from '../composables/useToasts'
import { ref, computed, onMounted, nextTick } from 'vue'
import { useMediaApi } from '../composables/useMediaApi'
import { useAssetApi } from '../composables/useAssetApi'
import { membershipState, membershipToggleAction, orderProjectsCurrentFirst } from '../utils/projectScope'

const { allowsAutofocus } = useViewport()

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
  },
  // Assign mode: how many targets are in each project (Map of project id to
  // count). Null while unknown; rows then show no membership marks.
  membership: {
    type: Map,
    default: null
  },
  // Assign mode: the working project, pinned to the top of the list.
  pinnedProjectId: {
    type: Number,
    default: null
  }
})

// 'added' is kept for callers that only care about additions; 'changed'
// reports every membership toggle as (projectId, 'add' | 'remove').
const emit = defineEmits(['select', 'added', 'changed', 'close'])

const { getProjects, createProject, addMediaToProject, removeMediaFromProject } = useMediaApi()
const { addToProject: addAssetsToProject, removeFromProject: removeAssetFromProject } = useAssetApi()

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

const targetCount = computed(() => (props.assetIds.length > 0 ? props.assetIds : props.mediaIds).length)

const orderedProjects = computed(() => (
  props.mode === 'assign'
    ? orderProjectsCurrentFirst(filteredProjects.value, props.pinnedProjectId)
    : filteredProjects.value
))

function isPinned(projectId) {
  return props.pinnedProjectId != null && props.pinnedProjectId === projectId
}

function rowState(projectId) {
  if (!props.membership) return 'none'
  return membershipState(props.membership, targetCount.value, projectId)
}

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

  // Assign mode - toggle membership. Removes when every target is already in
  // the project, otherwise adds the rest. The menu stays open so several
  // projects can be toggled in a row.
  if (addingToProjectId.value != null) return
  addingToProjectId.value = project.id
  const action = membershipToggleAction(rowState(project.id))
  try {
    if (action === 'add') {
      if (props.assetIds.length > 0) {
        await addAssetsToProject(project.id, props.assetIds)
      } else {
        await addMediaToProject(project.id, props.mediaIds)
      }
      emit('added', project.id)
    } else {
      // Per-item removal; an item that wasn't in the project is not an error.
      const results = props.assetIds.length > 0
        ? await Promise.allSettled(props.assetIds.map(id => removeAssetFromProject(id, project.id)))
        : await Promise.allSettled(props.mediaIds.map(id => removeMediaFromProject(project.id, id)))
      const failed = results.filter(r => r.status === 'rejected' && r.reason?.response?.status !== 404)
      if (failed.length === results.length && results.length > 0) throw failed[0].reason
    }
    emit('changed', project.id, action)
  } catch (err) {
    console.error(`Failed to ${action === 'add' ? 'add to' : 'remove from'} project:`, err)
    addToast(action === 'add' ? 'Could not add to project' : 'Could not remove from project', 'error')
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
  if (allowsAutofocus.value) searchInput.value?.focus()
})
</script>
