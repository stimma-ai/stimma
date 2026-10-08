<script setup lang="ts">
import { useViewport } from '../composables/useViewport'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CheckIcon, ChevronLeftIcon, EllipsisHorizontalIcon, MagnifyingGlassIcon, PlusIcon, TrashIcon } from '@heroicons/vue/24/outline'
import { useContextSwitch, useWorkingContext, type WorkingProject } from '../composables/useWorkingContext'
import { useMediaApi } from '../composables/useMediaApi'
import { useContextMenuPosition } from '../composables/useContextMenuPosition'
import { useDragStore } from '../stores/dragStore'
import { useProjectDrop } from '../composables/useProjectDrop'
import { useProjectDeletion } from '../composables/useProjectDeletion'
import { useProjectActivity } from '../composables/useProjectActivity'
import { addToast } from '../composables/useToasts'
import ConfirmModal from './ConfirmModal.vue'
import Button from './ui/Button.vue'
import Spinner from './ui/Spinner.vue'

const { allowsAutofocus } = useViewport()

// The project picker. The sidebar owns the triggers (project header, All
// projects row, project row menus); this owns the one dialog they open.
// Leaving a project is the sidebar's "‹ stimma", so there is no
// everything/none row here: every row is a project.
const props = defineProps<{ fallbackAnchor?: HTMLElement | null }>()
const emit = defineEmits<{ selected: [] }>()
const route = useRoute()
const router = useRouter()
const { activeProjectId, projects, orderedProjects, loading, error, selectProject, refreshProjects, rememberProject } = useWorkingContext()
const switchContext = useContextSwitch()
const { createProject, updateProject } = useMediaApi()
const deleteProjectAndCleanUp = useProjectDeletion()
const { draggedMediaItems, draggedMediaInfo } = useDragStore()
const { dropTarget, onDragOver, onDragLeave, onDrop } = useProjectDrop()
const { isBusy } = useProjectActivity()
// Opened by hovering a trigger mid-drag: rows take the drop, and the picker
// closes itself when the drag ends.
const forDrop = ref(false)
const trigger = ref<HTMLElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const search = ref<HTMLInputElement | null>(null)
const nameInput = ref<HTMLInputElement | null>(null)
const open = ref(false)
const query = ref('')
// Five touch-sized rows fit comfortably without a search-first menu.
const searchable = computed(() => projects.value.length > 5 || query.value.length > 0)
const editing = ref<WorkingProject | null>(null)
const name = ref('')
const busy = ref(false)
const deleting = ref<WorkingProject | null>(null)
const coords = ref({ x: 0, y: 0 })
const { menuStyle } = useContextMenuPosition(menu, coords, open)
const filtered = computed(() => orderedProjects.value
  .filter(p => (p.name || 'Untitled').toLowerCase().includes(query.value.toLowerCase())))

function close() {
  open.value = false
  editing.value = null
  if (forDrop.value) { forDrop.value = false; return }
  trigger.value?.focus()
}
function anchorAt(anchor: HTMLElement | null | undefined) {
  trigger.value = anchor ?? props.fallbackAnchor ?? null
  const rect = trigger.value?.getBoundingClientRect()
  coords.value = rect ? { x: rect.left, y: rect.bottom + 6 } : { x: 12, y: 48 }
}
async function toggle(anchor?: HTMLElement | null) {
  // A drag target's scope must stay stable until the drop finishes.
  if (draggedMediaItems.value.length) return
  if (open.value) { close(); return }
  anchorAt(anchor)
  query.value = ''
  editing.value = null
  open.value = true
  await refreshProjects()
  await nextTick()
  ;(allowsAutofocus.value ? search.value ?? menu.value : menu.value)?.focus()
}
/** Opens mid-drag so the rows can receive dropped media. */
async function openForDrop(anchor?: HTMLElement | null) {
  if (open.value) return
  anchorAt(anchor)
  query.value = ''
  editing.value = null
  forDrop.value = true
  open.value = true
  await refreshProjects()
}
function dropOnRow(id: number, event: DragEvent) {
  void onDrop(id, event)
  close()
}
/** Opens straight into one project's rename/settings/delete view. */
async function manage(project: WorkingProject, anchor?: HTMLElement | null) {
  if (draggedMediaItems.value.length) return
  anchorAt(anchor)
  open.value = true
  await edit(project)
}
async function choose(id: number | null) {
  close()
  if (await switchContext(id)) emit('selected')
}
async function edit(project: WorkingProject) {
  editing.value = { ...project }
  name.value = project.name || ''
  await nextTick()
  nameInput.value?.focus()
  nameInput.value?.select()
}
async function create() {
  if (busy.value) return
  busy.value = true
  try {
    const project = await createProject('')
    rememberProject(project)
    selectProject(project.id)
    await router.push({ name: 'project-overview', params: { id: project.id } })
    // Keep the picker open for optional inline naming; no blocking naming modal.
    open.value = true
    await edit(project)
  } catch { addToast('Could not create the project.', 'warning') }
  finally { busy.value = false }
}
async function saveName() {
  if (!editing.value || busy.value) return
  busy.value = true
  try {
    const project = await updateProject(editing.value.id, { name: name.value.trim() })
    rememberProject(project)
    editing.value = null
  } catch { addToast('Could not rename the project.', 'warning') }
  finally { busy.value = false }
}
async function settings() {
  if (!editing.value) return
  await openSettings(editing.value.id)
}
async function openSettings(id: number) {
  close()
  await router.push({ name: 'project-settings', params: { id } })
  emit('selected')
}
function requestDelete() {
  deleting.value = editing.value
  close()
}
const deleteMessage = computed(() => {
  const p = deleting.value
  if (!p) return ''
  return `Delete "${p.name || 'Untitled'}"? This cannot be undone.\n\nIts assets stay in your library. Its chats, boards, and saved views are deleted with it.`
})
async function confirmDelete() {
  if (!deleting.value || busy.value) return
  busy.value = true
  try {
    if (await deleteProjectAndCleanUp(deleting.value.id)) deleting.value = null
  } finally { busy.value = false }
}
function outside(event: MouseEvent) {
  // Inline management replaces the clicked row before this document listener
  // runs. The original event path still identifies a click inside the picker.
  const path = event.composedPath()
  if (open.value && !path.includes(menu.value!) && !(trigger.value && path.includes(trigger.value))) close()
}
function keyboard(event: KeyboardEvent) {
  if (!open.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopPropagation()
    if (editing.value) editing.value = null
    else close()
  } else if (['ArrowDown', 'ArrowUp', 'Tab'].includes(event.key)) {
    const controls = [...(menu.value?.querySelectorAll<HTMLElement>('button:not(:disabled), input') || [])]
      .filter(el => el.getClientRects().length)
    if (!controls.length) return
    const current = controls.indexOf(document.activeElement as HTMLElement)
    const step = event.key === 'ArrowUp' || event.shiftKey ? -1 : 1
    event.preventDefault()
    controls[(current + step + controls.length) % controls.length]?.focus()
  } else if (event.key === 'Enter' && document.activeElement === search.value && filtered.value[0]) {
    event.preventDefault()
    choose(filtered.value[0].id)
  }
}
function dragEnded() {
  // Let a row's own drop handler run first.
  setTimeout(() => { if (forDrop.value && open.value) close() })
}
watch(open, shown => {
  if (shown) {
    document.addEventListener('click', outside); document.addEventListener('keydown', keyboard)
    document.addEventListener('dragend', dragEnded); document.addEventListener('drop', dragEnded)
  } else {
    document.removeEventListener('click', outside); document.removeEventListener('keydown', keyboard)
    document.removeEventListener('dragend', dragEnded); document.removeEventListener('drop', dragEnded)
  }
})
watch(draggedMediaInfo, info => { if (!info) dragEnded() })
watch(() => route.query.projects, async value => {
  if (value !== '1') return
  await nextTick()
  if (!open.value) await toggle()
  query.value = String(route.query.q || '')
  const rest = { ...route.query }
  delete rest.projects
  delete rest.q
  await router.replace({ query: rest })
}, { immediate: true })
onBeforeUnmount(() => {
  document.removeEventListener('click', outside); document.removeEventListener('keydown', keyboard)
  document.removeEventListener('dragend', dragEnded); document.removeEventListener('drop', dragEnded)
})
defineExpose({ toggle, manage, openForDrop })
</script>

<template>
  <div class="contents">
    <slot :toggle="toggle" :open="open" :open-for-drop="openForDrop" />
    <Teleport to="body">
      <Transition name="menu">
        <div v-if="open" ref="menu" :style="menuStyle" tabindex="-1" role="dialog" aria-label="Choose a project" class="fixed z-menu focus-visible:outline-none w-[288px] max-w-[calc(100vw-16px)] rounded-lg border border-edge-subtle bg-surface p-1.5 shadow-lg">
          <template v-if="editing">
            <button class="flex items-center gap-1 rounded px-2 py-1.5 text-xs text-content-muted transition-colors hover:text-content coarse:min-h-11" @click="editing = null"><ChevronLeftIcon class="h-3 w-3" />Projects</button>
            <form class="px-2 pb-2 pt-1" @submit.prevent="saveName">
              <input ref="nameInput" v-model="name" aria-label="Project name" placeholder="Untitled" class="block w-full rounded-md bg-overlay-subtle px-2.5 py-1.5 text-sm text-content placeholder:text-content-muted focus-visible:outline-none focus-visible:ring-2 ring-accent/60 coarse:min-h-11" />
              <div class="mt-2 flex justify-end"><Button class="coarse:min-h-11 coarse:min-w-11" size="sm" :disabled="busy" type="submit">Save name</Button></div>
            </form>
            <div class="mt-1 border-t border-edge-subtle pt-1.5">
              <button class="w-full rounded px-2.5 py-1.5 text-left text-sm text-content-secondary transition-colors hover:bg-overlay-subtle hover:text-content coarse:min-h-11" @click="settings">Project settings</button>
              <button class="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left text-sm text-red-400 transition-colors hover:bg-overlay-subtle coarse:min-h-11" @click="requestDelete"><TrashIcon class="h-3.5 w-3.5" />Delete project</button>
            </div>
          </template>
          <template v-else>
            <!-- Past five projects the picker leads with a filter. -->
            <label v-if="searchable" class="mb-1 flex items-center gap-2 rounded-md bg-overlay-subtle px-2.5 focus-within:ring-2 ring-accent/60">
              <MagnifyingGlassIcon class="h-3.5 w-3.5 shrink-0 text-content-muted" />
              <input ref="search" v-model="query" aria-label="Find a project" placeholder="Find a project…" class="min-w-0 flex-1 bg-transparent py-1.5 text-sm text-content placeholder:text-content-muted focus-visible:outline-none coarse:min-h-11" />
            </label>
            <div class="max-h-72 overflow-y-auto">
              <div
                v-for="project in filtered"
                :key="project.id"
                class="group flex items-center rounded transition-colors"
                :class="dropTarget === project.id ? 'bg-accent/10 ring-1 ring-accent' : activeProjectId === project.id ? 'bg-selection/15' : 'hover:bg-overlay-subtle'"
                @dragover="onDragOver(project.id, $event)"
                @dragleave="onDragLeave(project.id)"
                @drop="dropOnRow(project.id, $event)"
              >
                <button class="flex min-w-0 flex-1 items-center gap-2 px-2.5 py-1.5 text-left text-sm coarse:min-h-11" :class="activeProjectId === project.id ? 'text-selection' : 'text-content-secondary hover:text-content'" @click="choose(project.id)">
                  <span class="truncate" :class="project.name ? '' : 'italic'">{{ project.name || 'Untitled project' }}</span>
                  <span v-if="isBusy(project.id) || activeProjectId === project.id" class="ml-auto flex shrink-0 items-center gap-1.5">
                    <Spinner v-if="isBusy(project.id)" size="sm" hue="border-t-blue-500" title="Running" />
                    <CheckIcon v-if="activeProjectId === project.id" class="h-3.5 w-3.5" />
                  </span>
                </button>
                <button :aria-label="`Manage ${project.name || 'Untitled'}`" class="mr-1 flex h-6 w-6 items-center justify-center rounded text-content-muted opacity-0 transition-opacity hover:bg-overlay-light hover:text-content focus-visible:opacity-100 group-hover:opacity-100 coarse:h-11 coarse:w-11 coarse:opacity-100" @click="edit(project)"><EllipsisHorizontalIcon class="h-3.5 w-3.5" /></button>
              </div>
              <p v-if="query && !filtered.length" class="px-2.5 py-3 text-xs text-content-muted">No matching projects</p>
              <p v-else-if="!projects.length && !loading && !error" class="px-2.5 py-3 text-xs text-content-muted">No projects yet</p>
            </div>
            <div v-if="loading && !projects.length" class="flex items-center gap-2 px-2.5 py-2 text-xs text-content-muted"><Spinner class="h-3 w-3" />Loading projects…</div>
            <button v-if="error" class="px-2.5 py-2 text-xs text-content-muted" @click="refreshProjects">{{ error }}</button>
            <div class="mt-1 border-t border-edge-subtle pt-1"><button :disabled="busy" class="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-sm text-accent transition-colors hover:bg-overlay-subtle disabled:opacity-50 coarse:min-h-11" @click="create"><PlusIcon class="h-3.5 w-3.5" />New project</button></div>
          </template>
        </div>
      </Transition>
    </Teleport>
    <ConfirmModal :show="deleting != null" title="Delete project" :message="deleteMessage" confirm-text="Delete" @confirm="confirmDelete" @cancel="deleting = null" />
  </div>
</template>
