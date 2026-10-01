<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { EllipsisHorizontalIcon, PlusIcon } from '@heroicons/vue/24/outline'
import { useContextSwitch, useWorkingContext, type WorkingProject } from '../../composables/useWorkingContext'
import { useSidebarSections } from '../../composables/useSidebarSections'
import { useMediaApi } from '../../composables/useMediaApi'
import { useDragStore } from '../../stores/dragStore'
import { getDroppedMediaIds } from '../../composables/useDragPreview'
import { addToast } from '../../composables/useToasts'
import SidebarSectionHeader from './SidebarSectionHeader.vue'
import WorkingContextPicker from '../WorkingContextPicker.vue'

// Everything's Projects section: recent projects as plain names (no covers,
// so nothing inside a project shows at the top level), inline creation, and
// drop targets for assets. Entering a project swaps the sidebar to that
// project's header; switching from there goes through WorkingContextPicker.
const RECENT_LIMIT = 5
const emit = defineEmits<{ selected: [] }>()
const router = useRouter()
const { orderedProjects, projects, refreshProjects, rememberProject, selectProject } = useWorkingContext()
const switchContext = useContextSwitch()
const { isCollapsed } = useSidebarSections()
const { createProject, updateProject, addMediaToProject } = useMediaApi()
const { draggedMediaItems } = useDragStore()

const header = ref<HTMLElement | null>(null)
const picker = ref<InstanceType<typeof WorkingContextPicker> | null>(null)
let nameInput: HTMLInputElement | null = null
// Only one naming input renders at a time; a function ref avoids v-for arrays.
function setNameInput(el: unknown) { if (el) nameInput = el as HTMLInputElement }
// 'new' is the inline create row; a number is an inline rename.
const naming = ref<'new' | number | null>(null)
const draft = ref('')
const busy = ref(false)
const dropTarget = ref<'new' | number | null>(null)

const collapsed = computed(() => isCollapsed('projects'))
const recent = computed(() => orderedProjects.value.slice(0, RECENT_LIMIT))
const dragging = computed(() => draggedMediaItems.value.length > 0)
const dragCount = computed(() => draggedMediaItems.value.length)

onMounted(() => { refreshProjects() })

async function enter(project: WorkingProject) {
  if (await switchContext(project.id)) emit('selected')
}

async function startNaming(target: 'new' | number) {
  draft.value = target === 'new' ? '' : (projects.value.find(p => p.id === target)?.name || '')
  naming.value = target
  await nextTick()
  nameInput?.focus()
  nameInput?.select()
}

async function commitNaming() {
  const target = naming.value
  const name = draft.value.trim()
  if (target == null || busy.value) return
  naming.value = null
  if (target === 'new' && !name) return
  busy.value = true
  try {
    if (target === 'new') {
      const project = await createProject(name)
      rememberProject(project)
      selectProject(project.id)
      await router.push({ name: 'project-overview', params: { id: project.id } })
      emit('selected')
    } else {
      rememberProject(await updateProject(target, { name }))
    }
  } catch {
    addToast(target === 'new' ? 'Could not create the project.' : 'Could not rename the project.', 'warning')
  } finally {
    busy.value = false
  }
}

function onNameKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter') { event.preventDefault(); commitNaming() }
  else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); naming.value = null }
}

function manage(project: WorkingProject, event: MouseEvent) {
  picker.value?.manage(project, event.currentTarget as HTMLElement)
}

function onDragOver(target: 'new' | number, event: DragEvent) {
  if (!event.dataTransfer?.types.includes('application/x-media-id')) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'copy'
  dropTarget.value = target
}

function onDragLeave(target: 'new' | number) {
  if (dropTarget.value === target) dropTarget.value = null
}

async function onDrop(target: 'new' | number, event: DragEvent) {
  event.preventDefault()
  dropTarget.value = null
  const mediaIds = getDroppedMediaIds(event.dataTransfer)
  if (!mediaIds.length) return
  const noun = mediaIds.length === 1 ? 'asset' : 'assets'
  try {
    if (target === 'new') {
      const project = await createProject('')
      rememberProject(project)
      await addMediaToProject(project.id, mediaIds)
      addToast(`Added ${mediaIds.length} ${noun} to a new project`, 'success')
      await startNaming(project.id)
    } else {
      await addMediaToProject(target, mediaIds)
      const name = projects.value.find(p => p.id === target)?.name || 'Untitled project'
      addToast(`Added ${mediaIds.length} ${noun} to ${name}`, 'success')
    }
  } catch {
    addToast('Could not add to the project.', 'warning')
  }
}

const rowClass = 'flex w-full items-center rounded px-3 py-1.5 text-left text-sm transition-colors coarse:min-h-11'
</script>

<template>
  <section aria-label="Projects">
    <div ref="header">
      <SidebarSectionHeader id="projects" label="Projects">
        <template #action>
          <button
            v-if="projects.length > 0"
            type="button"
            aria-label="New project"
            title="New project"
            class="flex h-5 w-5 items-center justify-center rounded text-content-muted opacity-0 transition-opacity hover:bg-overlay-light hover:text-content focus-visible:opacity-100 group-hover/section:opacity-100 coarse:h-11 coarse:w-11 coarse:opacity-100"
            @click="startNaming('new')"
          >
            <PlusIcon class="h-3 w-3" />
          </button>
        </template>
      </SidebarSectionHeader>
    </div>

    <div v-if="!collapsed" class="flex flex-col gap-1">
      <!-- While media is dragged, the section offers a fresh project as a target. -->
      <button
        v-if="dragging && projects.length > 0"
        type="button"
        :class="[rowClass, 'gap-2 text-accent', dropTarget === 'new' ? 'bg-accent/10 ring-1 ring-accent' : 'hover:bg-overlay-subtle']"
        @dragover="onDragOver('new', $event)"
        @dragleave="onDragLeave('new')"
        @drop="onDrop('new', $event)"
      >
        <PlusIcon class="h-3.5 w-3.5 shrink-0" />
        <span class="truncate">New project with {{ dragCount }} {{ dragCount === 1 ? 'asset' : 'assets' }}</span>
      </button>

      <template v-if="projects.length === 0 && naming !== 'new'">
        <button
          type="button"
          :class="[rowClass, 'gap-2 text-accent', dropTarget === 'new' ? 'bg-accent/10 ring-1 ring-accent' : 'hover:bg-overlay-subtle']"
          @click="startNaming('new')"
          @dragover="onDragOver('new', $event)"
          @dragleave="onDragLeave('new')"
          @drop="onDrop('new', $event)"
        >
          <PlusIcon class="h-3.5 w-3.5 shrink-0" />
          <span>New project</span>
        </button>
        <p class="px-3 pb-1 text-[11.5px] leading-snug text-content-muted">
          Keep the assets, chats and boards for one client or piece of work together.
        </p>
      </template>

      <div v-if="naming === 'new'" :class="[rowClass, 'py-1']">
        <input
          :ref="setNameInput"
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
        <div v-if="naming === project.id" :class="[rowClass, 'py-1']">
          <input
            :ref="setNameInput"
            v-model="draft"
            v-no-autocorrect
            aria-label="Project name"
            placeholder="Untitled"
            class="-mx-1.5 min-w-0 flex-1 rounded bg-overlay-subtle px-1.5 py-0.5 text-sm text-content outline-none ring-1 ring-selection/60 coarse:min-h-11"
            @keydown="onNameKeydown"
            @blur="commitNaming"
          />
        </div>
        <template v-else>
          <button
            type="button"
            :class="[rowClass, 'pr-8 text-content-secondary', dropTarget === project.id ? 'bg-accent/10 text-content ring-1 ring-accent' : 'hover:bg-overlay-subtle hover:text-content']"
            :title="project.name || 'Untitled project'"
            @click="enter(project)"
            @contextmenu.prevent="manage(project, $event)"
            @dragover="onDragOver(project.id, $event)"
            @dragleave="onDragLeave(project.id)"
            @drop="onDrop(project.id, $event)"
          >
            <span class="truncate" :class="project.name ? '' : 'italic text-content-muted'">{{ project.name || 'Untitled project' }}</span>
          </button>
          <button
            type="button"
            :aria-label="`Manage ${project.name || 'Untitled'}`"
            class="absolute inset-y-0 right-1.5 my-auto flex h-6 w-6 items-center justify-center rounded text-content-muted opacity-0 transition-opacity hover:bg-overlay-light hover:text-content focus-visible:opacity-100 group-hover/project:opacity-100 coarse:h-11 coarse:w-11 coarse:opacity-100"
            @click.stop="manage(project, $event)"
          >
            <EllipsisHorizontalIcon class="h-3.5 w-3.5" />
          </button>
        </template>
      </div>

      <button
        v-if="projects.length > RECENT_LIMIT"
        type="button"
        :class="[rowClass, 'justify-between text-content-muted hover:bg-overlay-subtle hover:text-content-secondary']"
        @click="picker?.toggle($event.currentTarget as HTMLElement)"
      >
        <span>All projects</span>
        <span class="text-[11px] tabular-nums">{{ projects.length }}</span>
      </button>
    </div>

    <WorkingContextPicker ref="picker" :fallback-anchor="header" @selected="emit('selected')" />
  </section>
</template>
