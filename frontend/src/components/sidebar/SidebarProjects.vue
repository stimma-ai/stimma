<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { EllipsisHorizontalIcon, PlusIcon } from '@heroicons/vue/24/outline'
import { useContextSwitch, useWorkingContext, type WorkingProject } from '../../composables/useWorkingContext'
import { useSidebarSections } from '../../composables/useSidebarSections'
import { useMediaApi } from '../../composables/useMediaApi'
import { useDragHoverOpen, useProjectDrop } from '../../composables/useProjectDrop'
import { useProjectActivity } from '../../composables/useProjectActivity'
import { addToast } from '../../composables/useToasts'
import SidebarSectionHeader from './SidebarSectionHeader.vue'
import WorkingContextPicker from '../WorkingContextPicker.vue'
import Spinner from '../ui/Spinner.vue'

// Everything's Projects section: recent projects as plain names (no covers,
// so nothing inside a project shows at the top level), inline creation, and
// drop targets for assets. Entering a project swaps the sidebar to that
// project's header; switching from there goes through WorkingContextPicker.
const RECENT_LIMIT = 5
const NEW_PROJECT_HINT = 'New project — keep the assets, chats and boards for one piece of work together'
const emit = defineEmits<{ selected: [] }>()
const router = useRouter()
const { orderedProjects, projects, refreshProjects, rememberProject, selectProject } = useWorkingContext()
const switchContext = useContextSwitch()
const { isCollapsed, toggleSection } = useSidebarSections()
const { createProject } = useMediaApi()
const { dropTarget, onDragOver, onDragLeave, onDrop } = useProjectDrop()
const { isBusy } = useProjectActivity()

const header = ref<HTMLElement | null>(null)
const allRow = ref<HTMLElement | null>(null)
const picker = ref<InstanceType<typeof WorkingContextPicker> | null>(null)
const nameInput = ref<HTMLInputElement | null>(null)
const naming = ref(false)
const draft = ref('')
const busy = ref(false)
// Past the recent rows, hovering "All projects" mid-drag opens the picker.
const allRowDrag = useDragHoverOpen(() => picker.value?.openForDrop(allRow.value))

const collapsed = computed(() => isCollapsed('projects'))
const recent = computed(() => orderedProjects.value.slice(0, RECENT_LIMIT))
const busyBeyondRecent = computed(() => orderedProjects.value.slice(RECENT_LIMIT).some(p => isBusy(p.id)))

onMounted(() => { refreshProjects() })

async function enter(project: WorkingProject) {
  if (await switchContext(project.id)) emit('selected')
}

async function startNaming() {
  if (collapsed.value) toggleSection('projects')
  draft.value = ''
  naming.value = true
  await nextTick()
  nameInput.value?.focus()
}

async function commitNaming() {
  const name = draft.value.trim()
  if (!naming.value || busy.value) return
  naming.value = false
  if (!name) return
  busy.value = true
  try {
    const project = await createProject(name)
    rememberProject(project)
    selectProject(project.id)
    await router.push({ name: 'project-overview', params: { id: project.id } })
    emit('selected')
  } catch {
    addToast('Could not create the project.', 'warning')
  } finally {
    busy.value = false
  }
}

function onNameKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter') { event.preventDefault(); commitNaming() }
  else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); naming.value = false }
}

function manage(project: WorkingProject, event: MouseEvent) {
  picker.value?.manage(project, event.currentTarget as HTMLElement)
}

const rowClass = 'flex w-full items-center rounded px-3 py-1.5 text-left text-sm transition-colors coarse:min-h-11'
</script>

<template>
  <section aria-label="Projects">
    <div ref="header">
      <SidebarSectionHeader id="projects" label="Projects">
        <template #action>
          <!-- Always visible while there are no projects; hover-only after. -->
          <button
            type="button"
            aria-label="New project"
            :title="NEW_PROJECT_HINT"
            class="flex h-5 w-5 items-center justify-center rounded text-content-muted transition-opacity hover:bg-overlay-light hover:text-content focus-visible:opacity-100 coarse:h-11 coarse:w-11 coarse:opacity-100"
            :class="projects.length > 0 ? 'opacity-0 group-hover/section:opacity-100' : ''"
            @click="startNaming"
          >
            <PlusIcon class="h-3 w-3" />
          </button>
        </template>
      </SidebarSectionHeader>
    </div>

    <div v-if="!collapsed" class="flex flex-col gap-1">
      <div v-if="naming" :class="[rowClass, 'py-1']">
        <input
          ref="nameInput"
          v-model="draft"
          v-no-autocorrect
          aria-label="Project name"
          placeholder="Project name"
          class="-mx-1.5 min-w-0 flex-1 rounded bg-overlay-subtle px-1.5 py-0.5 text-sm text-content outline-none ring-1 ring-selection/60 coarse:min-h-11"
          @keydown="onNameKeydown"
          @blur="commitNaming"
        />
      </div>

      <div v-for="project in recent" :key="project.id" class="group/project relative">
        <button
          type="button"
          :class="[rowClass, 'gap-2 pr-8 text-content-secondary', dropTarget === project.id ? 'bg-accent/10 text-content ring-1 ring-accent' : 'hover:bg-overlay-subtle hover:text-content']"
          :title="project.name || 'Untitled project'"
          @click="enter(project)"
          @contextmenu.prevent="manage(project, $event)"
          @dragover="onDragOver(project.id, $event)"
          @dragleave="onDragLeave(project.id)"
          @drop="onDrop(project.id, $event)"
        >
          <span class="truncate" :class="project.name ? '' : 'italic text-content-muted'">{{ project.name || 'Untitled project' }}</span>
          <Spinner v-if="isBusy(project.id)" size="sm" hue="border-t-blue-500" class="ml-auto shrink-0" title="Running" />
        </button>
        <button
          type="button"
          :aria-label="`Manage ${project.name || 'Untitled'}`"
          class="absolute inset-y-0 right-1.5 my-auto flex h-6 w-6 items-center justify-center rounded text-content-muted opacity-0 transition-opacity hover:bg-overlay-light hover:text-content focus-visible:opacity-100 group-hover/project:opacity-100 coarse:h-11 coarse:w-11 coarse:opacity-100"
          @click.stop="manage(project, $event)"
        >
          <EllipsisHorizontalIcon class="h-3.5 w-3.5" />
        </button>
      </div>

      <button
        v-if="projects.length > RECENT_LIMIT"
        ref="allRow"
        type="button"
        :class="[rowClass, 'justify-between text-content-muted hover:bg-overlay-subtle hover:text-content-secondary']"
        title="All projects (hold media here to drop it into any project)"
        @click="picker?.toggle($event.currentTarget as HTMLElement)"
        @dragenter="allRowDrag.onDragEnter"
        @dragover="allRowDrag.onDragOver"
        @dragleave="allRowDrag.onDragLeave"
        @drop="allRowDrag.onDrop"
      >
        <span>All projects</span>
        <span class="flex items-center gap-1.5">
          <Spinner v-if="busyBeyondRecent" size="sm" hue="border-t-blue-500" title="Running" />
          <span class="text-[11px] tabular-nums">{{ projects.length }}</span>
        </span>
      </button>
    </div>

    <WorkingContextPicker ref="picker" :fallback-anchor="header" @selected="emit('selected')" />
  </section>
</template>
