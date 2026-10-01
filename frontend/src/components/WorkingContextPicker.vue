<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArchiveBoxIcon, BookOpenIcon, CheckIcon, ChevronUpDownIcon, EllipsisHorizontalIcon, MagnifyingGlassIcon, PlusIcon, TrashIcon } from '@heroicons/vue/24/outline'
import { useWorkingContext, type WorkingProject } from '../composables/useWorkingContext'
import { useMediaApi } from '../composables/useMediaApi'
import { useContextMenuPosition } from '../composables/useContextMenuPosition'
import { contextSwitchRoute } from '../utils/workingContext'
import { useDragStore } from '../stores/dragStore'
import { addToast } from '../composables/useToasts'
import ConfirmModal from './ConfirmModal.vue'
import Button from './ui/Button.vue'
import Spinner from './ui/Spinner.vue'

const emit = defineEmits<{ selected: [] }>()
const route = useRoute()
const router = useRouter()
const { activeProjectId, activeProject, projects, orderedProjects, loading, error, selectProject, refreshProjects, rememberProject } = useWorkingContext()
const { createProject, updateProject, deleteProject } = useMediaApi()
const { draggedMediaItems } = useDragStore()
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
  trigger.value?.focus()
}
async function toggle() {
  // A drag target's scope must stay stable until the drop finishes.
  if (draggedMediaItems.value.length) return
  if (open.value) { close(); return }
  const rect = trigger.value!.getBoundingClientRect()
  coords.value = { x: rect.left, y: rect.bottom + 6 }
  query.value = ''
  open.value = true
  await refreshProjects()
  await nextTick()
  ;(search.value ?? menu.value)?.focus()
}
async function choose(id: number | null) {
  const same = activeProjectId.value === id
  close()
  if (same) { emit('selected'); return }
  const target = contextSwitchRoute(route, id)
  const previous = activeProjectId.value
  selectProject(id)
  try {
    const failure = await router.push(target)
    if (failure) selectProject(previous)
    else emit('selected')
  } catch {
    selectProject(previous)
    addToast('Could not switch projects.', 'warning')
  }
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
  const id = editing.value.id
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
  return `Delete "${p.name || 'Untitled'}"? This cannot be undone.\n\nAssets will remain in Everything. Chats, boards, and saved views will be deleted with the project.`
})
async function confirmDelete() {
  if (!deleting.value || busy.value) return
  busy.value = true
  const id = deleting.value.id
  try {
    await deleteProject(id)
    if (activeProjectId.value === id) {
      selectProject(null)
      await router.push({ name: 'browse' })
    }
    deleting.value = null
    await refreshProjects()
  } catch { addToast('Could not delete the project.', 'warning') }
  finally { busy.value = false }
}
function outside(event: MouseEvent) {
  // Inline management replaces the clicked row before this document listener
  // runs. The original event path still identifies a click inside the picker.
  const path = event.composedPath()
  if (open.value && !path.includes(menu.value!) && !path.includes(trigger.value!)) close()
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
watch(open, shown => {
  if (shown) { document.addEventListener('click', outside); document.addEventListener('keydown', keyboard) }
  else { document.removeEventListener('click', outside); document.removeEventListener('keydown', keyboard) }
})
watch(() => route.query.projects, async value => {
  if (value !== '1') return
  await nextTick()
  if (!open.value) await toggle()
  query.value = String(route.query.q || '')
  const query = { ...route.query }
  delete query.projects
  await router.replace({ query })
}, { immediate: true })
onBeforeUnmount(() => { document.removeEventListener('click', outside); document.removeEventListener('keydown', keyboard) })
</script>

<template>
  <div class="mb-3">
    <button ref="trigger" type="button" aria-label="Working context" aria-haspopup="dialog" :aria-expanded="open" class="flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-content-secondary transition-colors hover:bg-overlay-subtle hover:text-content focus-visible:outline-none focus-visible:ring-2 ring-accent/60 coarse:min-h-11" @click="toggle">
      <ArchiveBoxIcon v-if="activeProjectId != null" class="h-4 w-4 shrink-0 text-content-muted" />
      <BookOpenIcon v-else class="h-4 w-4 shrink-0 text-content-muted" />
      <span class="min-w-0 flex-1 truncate text-left">{{ activeProjectId != null ? activeProject?.name || 'Untitled project' : 'Everything' }}</span>
      <ChevronUpDownIcon class="h-3 w-3 shrink-0 text-content-muted" />
    </button>
    <Teleport to="body">
      <Transition name="menu">
        <div v-if="open" ref="menu" :style="menuStyle" tabindex="-1" role="dialog" aria-label="Choose working context" class="fixed z-menu focus-visible:outline-none w-[288px] max-w-[calc(100vw-16px)] rounded-lg border border-edge-subtle bg-surface p-1.5 shadow-lg">
          <template v-if="editing">
            <button class="px-3 py-2 text-xs text-content-muted hover:text-content coarse:min-h-11" @click="editing = null">← Projects</button>
            <form class="px-3 py-2" @submit.prevent="saveName">
              <label class="text-xs text-content-secondary">Project name<input ref="nameInput" v-model="name" aria-label="Project name" placeholder="Untitled" class="mt-2 block w-full rounded-md bg-overlay-subtle px-3 py-2 text-sm text-content focus-visible:outline-none focus-visible:ring-2 ring-accent/60 coarse:min-h-11" /></label>
              <div class="mt-3 flex justify-end"><Button class="coarse:min-h-11 coarse:min-w-11" size="sm" :disabled="busy" type="submit">Save name</Button></div>
            </form>
            <div class="mt-2 border-t border-edge-subtle pt-1.5">
              <button class="w-full rounded-md px-3 py-2 text-left text-sm text-content-secondary hover:bg-overlay-subtle coarse:min-h-11" @click="settings">Project settings</button>
              <button class="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm text-red-400 hover:bg-overlay-subtle coarse:min-h-11" @click="requestDelete"><TrashIcon class="h-4 w-4" />Delete project</button>
            </div>
          </template>
          <template v-else>
            <div v-if="searchable" class="flex items-center gap-2 px-3 py-2">
              <MagnifyingGlassIcon class="h-3.5 w-3.5 shrink-0 text-content-muted" />
              <input ref="search" v-model="query" aria-label="Find a project" placeholder="Find a project…" class="min-w-0 w-full rounded-md bg-overlay-subtle px-2 py-1 text-sm text-content placeholder:text-content-muted focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-inset coarse:min-h-11" />
            </div>
            <button class="flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-left text-sm transition-colors coarse:min-h-11" :class="activeProjectId == null ? 'bg-selection/15 text-selection' : 'text-content-secondary hover:bg-overlay-subtle'" @click="choose(null)">
              <BookOpenIcon class="h-4 w-4 shrink-0" />
              <span class="min-w-0 flex-1 truncate">Everything</span>
              <CheckIcon v-if="activeProjectId == null" class="h-3.5 w-3.5 shrink-0" />
            </button>
            <div v-if="searchable && projects.length" class="px-3 pb-1 pt-3 text-xs text-content-muted">Projects</div>
            <div class="max-h-64 overflow-y-auto">
              <div v-for="project in filtered" :key="project.id" class="group flex items-center rounded-md" :class="activeProjectId === project.id ? 'bg-selection/15' : 'hover:bg-overlay-subtle'">
                <button class="flex min-w-0 flex-1 items-center gap-2.5 px-3 py-2 text-left text-sm coarse:min-h-11" :class="activeProjectId === project.id ? 'text-selection' : 'text-content-secondary'" @click="choose(project.id)"><ArchiveBoxIcon class="h-4 w-4 shrink-0 text-content-muted" /><span class="truncate">{{ project.name || 'Untitled' }}</span><CheckIcon v-if="activeProjectId === project.id" class="ml-auto h-3.5 w-3.5 shrink-0" /></button>
                <button :aria-label="`Manage ${project.name || 'Untitled'}`" class="mr-1 rounded-md p-2 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 coarse:opacity-100 text-content-muted hover:text-content focus-visible:outline-none focus-visible:ring-2 ring-accent/60 coarse:min-h-11 coarse:min-w-11" @click="edit(project)"><EllipsisHorizontalIcon class="h-4 w-4" /></button>
              </div>
              <p v-if="query && !filtered.length" class="px-3 py-4 text-xs text-content-muted">No matching projects</p>
            </div>
            <div v-if="loading" class="flex items-center gap-2 px-3 py-2 text-xs text-content-muted"><Spinner class="h-3 w-3" />Loading projects…</div>
            <button v-if="error" class="px-3 py-2 text-xs text-content-muted" @click="refreshProjects">{{ error }}</button>
            <div class="mt-1.5 border-t border-edge-subtle pt-1.5"><button :disabled="busy" class="flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm text-accent hover:bg-overlay-subtle disabled:opacity-50 coarse:min-h-11" @click="create"><PlusIcon class="h-4 w-4" />New project</button></div>
          </template>
        </div>
      </Transition>
    </Teleport>
    <ConfirmModal :show="deleting != null" title="Delete project" :message="deleteMessage" confirm-text="Delete" @confirm="confirmDelete" @cancel="deleting = null" />
  </div>
</template>
