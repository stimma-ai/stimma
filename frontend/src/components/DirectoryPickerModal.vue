<script setup lang="ts">
/**
 * In-app folder picker, browsing the backend's filesystem over the API.
 *
 * Mounted once in App.vue; opened through pickDirectory() in
 * useDirectoryPicker. Layout: history + breadcrumbs (or a typed path) on
 * top, places/volumes/recents down the left, subfolders on the right, the
 * chosen path and the actions along the bottom.
 */
import { computed, nextTick, ref, watch } from 'vue'
import {
  ArrowDownTrayIcon,
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CircleStackIcon,
  ClockIcon,
  ComputerDesktopIcon,
  DocumentIcon,
  FilmIcon,
  FolderIcon,
  FolderOpenIcon,
  HomeIcon,
  MusicalNoteIcon,
  PencilIcon,
  PhotoIcon,
  ServerIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import Modal from './ui/Modal.vue'
import Button from './ui/Button.vue'
import IconButton from './ui/IconButton.vue'
import Spinner from './ui/Spinner.vue'
import Tooltip from './ui/Tooltip.vue'
import { useDirectoryPickerHost } from '../composables/useDirectoryPicker'
import { browseErrorMessage, useFilesystemApi } from '../composables/useFilesystemApi'
import { useMultiDevice } from '../composables/useMultiDevice'
import {
  activeRootFor,
  basename,
  crumbsFor,
  groupRoots,
  parseRecents,
  pushRecent,
  recentsStorageKey,
  type DirectoryEntry,
  type DirectoryListing,
  type RecentEntry,
} from '../utils/directoryPicker'

const { request, resolve } = useDirectoryPickerHost()
const { browseDirectory } = useFilesystemApi()
const { isRemote, activeDeviceName, activeDeviceId } = useMultiDevice()

const open = computed(() => request.value !== null)
const title = computed(() => request.value?.title || 'Choose a folder')

const roots = ref<DirectoryEntry[]>([])
const listing = ref<DirectoryListing | null>(null)
const selectedPath = ref<string | null>(null)
const recents = ref<RecentEntry[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const backStack = ref<string[]>([])
const forwardStack = ref<string[]>([])
// Bumped on every navigation so a slow response cannot overwrite a newer one.
let navToken = 0

const pathEditing = ref(false)
const pathInput = ref('')
const pathInputEl = ref<HTMLInputElement | null>(null)
const listEl = ref<HTMLElement | null>(null)

const sidebarGroups = computed(() => groupRoots(roots.value))
const activeRootPath = computed(() => activeRootFor(listing.value?.path, roots.value))
const crumbs = computed(() => crumbsFor(listing.value))
const entries = computed(() => listing.value?.entries ?? [])
const selectedName = computed(() => (selectedPath.value ? basename(selectedPath.value) : null))

const rootIcons: Record<string, any> = {
  Desktop: ComputerDesktopIcon,
  Pictures: PhotoIcon,
  Movies: FilmIcon,
  Videos: FilmIcon,
  Music: MusicalNoteIcon,
  Documents: DocumentIcon,
  Downloads: ArrowDownTrayIcon,
}

function rootIcon(root: DirectoryEntry) {
  if (root.kind === 'home') return HomeIcon
  if (root.kind === 'volume') return CircleStackIcon
  return rootIcons[root.name] ?? FolderIcon
}

function storageKey() {
  return recentsStorageKey(activeDeviceId.value)
}

function loadRecents() {
  try {
    recents.value = parseRecents(localStorage.getItem(storageKey()))
  } catch {
    recents.value = []
  }
}

function saveRecent(path: string) {
  recents.value = pushRecent(recents.value, path)
  try {
    localStorage.setItem(storageKey(), JSON.stringify(recents.value))
  } catch {
    // Storage full or unavailable: recents are a convenience, not state.
  }
}

async function fetchListing(path?: string): Promise<DirectoryListing | null> {
  const token = ++navToken
  loading.value = true
  error.value = null
  try {
    const result = await browseDirectory(path)
    return token === navToken ? result : null
  } catch (err) {
    if (token === navToken) error.value = browseErrorMessage(err)
    return null
  } finally {
    if (token === navToken) loading.value = false
  }
}

async function navigateTo(path: string, opts: { recordHistory?: boolean } = {}): Promise<boolean> {
  const next = await fetchListing(path || undefined)
  if (!next) return false
  if (opts.recordHistory !== false && listing.value) {
    backStack.value.push(listing.value.path)
    forwardStack.value = []
  }
  listing.value = next
  // The folder you are looking at is always choosable.
  selectedPath.value = next.path || null
  return true
}

async function init() {
  backStack.value = []
  forwardStack.value = []
  pathEditing.value = false
  listing.value = null
  selectedPath.value = null
  error.value = null
  loadRecents()

  const rootListing = await fetchListing()
  if (!rootListing) return
  roots.value = rootListing.entries

  const wanted = request.value?.defaultPath
  if (wanted && (await navigateTo(wanted, { recordHistory: false }))) return

  const home = roots.value.find((r) => r.kind === 'home') ?? roots.value[0]
  if (home) {
    await navigateTo(home.path, { recordHistory: false })
  } else {
    listing.value = rootListing
  }
}

async function goBack() {
  const prev = backStack.value.pop()
  if (prev === undefined) return
  const current = listing.value?.path ?? ''
  if (await navigateTo(prev, { recordHistory: false })) forwardStack.value.push(current)
  else backStack.value.push(prev)
}

async function goForward() {
  const next = forwardStack.value.pop()
  if (next === undefined) return
  const current = listing.value?.path ?? ''
  if (await navigateTo(next, { recordHistory: false })) backStack.value.push(current)
  else forwardStack.value.push(next)
}

function goUp() {
  const parent = listing.value?.parent
  if (parent) navigateTo(parent)
}

function handleEntryClick(entry: DirectoryEntry) {
  // First click selects; a second click on the selected row enters it.
  if (selectedPath.value === entry.path) navigateTo(entry.path)
  else selectedPath.value = entry.path
}

function handleEntryOpen(entry: DirectoryEntry) {
  if (entry.is_dir) navigateTo(entry.path)
}

function moveSelection(delta: number) {
  const list = entries.value
  if (!list.length) return
  const idx = list.findIndex((e) => e.path === selectedPath.value)
  const next = idx < 0 ? (delta > 0 ? 0 : list.length - 1) : Math.min(list.length - 1, Math.max(0, idx + delta))
  selectedPath.value = list[next].path
  nextTick(() => {
    listEl.value?.querySelector<HTMLElement>('[data-selected="true"]')?.scrollIntoView({ block: 'nearest' })
  })
}

function handleListKeydown(e: KeyboardEvent) {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    moveSelection(1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    moveSelection(-1)
  } else if (e.key === 'Enter') {
    const entry = entries.value.find((en) => en.path === selectedPath.value)
    if (entry) {
      e.preventDefault()
      handleEntryOpen(entry)
    }
  } else if (e.key === 'Backspace') {
    e.preventDefault()
    goUp()
  }
}

async function startPathEdit() {
  pathInput.value = listing.value?.path ?? ''
  pathEditing.value = true
  await nextTick()
  pathInputEl.value?.focus()
  pathInputEl.value?.select()
}

async function submitPathEdit() {
  const target = pathInput.value.trim()
  if (!target) return
  if (await navigateTo(target)) pathEditing.value = false
  // On failure the error shows in the list area; the field stays open to fix it.
}

function cancelPathEdit() {
  pathEditing.value = false
  error.value = null
}

function choose() {
  if (!selectedPath.value) return
  saveRecent(selectedPath.value)
  resolve(selectedPath.value)
}

function cancel() {
  resolve(null)
}

watch(open, (isOpen) => {
  if (isOpen) init()
})
</script>

<template>
  <Modal :show="open" size="custom" custom-class="max-w-3xl w-full" nested @close="cancel">
    <template #header>
      <div class="flex items-center justify-between gap-3">
        <div class="flex min-w-0 items-center gap-3">
          <h2 class="truncate text-lg font-semibold text-content">{{ title }}</h2>
          <span
            v-if="isRemote"
            class="flex shrink-0 items-center gap-1.5 rounded-full bg-overlay-subtle px-2.5 py-0.5 text-xs text-content-secondary"
          >
            <ServerIcon class="h-3.5 w-3.5" />
            {{ activeDeviceName }}
          </span>
        </div>
        <IconButton aria-label="Close" @click="cancel">
          <XMarkIcon class="h-5 w-5" />
        </IconButton>
      </div>
    </template>

    <div class="flex h-[60vh] max-h-[560px] min-h-[320px] flex-col">
      <!-- History + breadcrumbs / typed path -->
      <div class="flex shrink-0 items-center gap-1 border-b border-edge-subtle px-3 py-2">
        <IconButton aria-label="Back" :disabled="!backStack.length" @click="goBack">
          <ChevronLeftIcon class="h-4 w-4" />
        </IconButton>
        <IconButton aria-label="Forward" :disabled="!forwardStack.length" @click="goForward">
          <ChevronRightIcon class="h-4 w-4" />
        </IconButton>

        <template v-if="pathEditing">
          <input
            ref="pathInputEl"
            v-model="pathInput"
            type="text"
            spellcheck="false"
            placeholder="Type a folder path"
            class="mx-1 min-w-0 flex-1 rounded-md border border-transparent bg-overlay-subtle px-3 py-1.5 font-mono text-sm text-content outline-none placeholder:text-content-muted focus:border-accent focus-visible:ring-2 ring-accent/40"
            @keydown.enter.prevent="submitPathEdit"
            @keydown.esc.stop.prevent="cancelPathEdit"
          />
          <IconButton aria-label="Go to path" @click="submitPathEdit">
            <CheckIcon class="h-4 w-4" />
          </IconButton>
        </template>
        <template v-else>
          <div class="mx-1 flex min-w-0 flex-1 items-center gap-0.5 overflow-hidden">
            <template v-for="(crumb, i) in crumbs" :key="crumb.path">
              <ChevronRightIcon v-if="i > 0" class="h-3 w-3 shrink-0 text-content-muted" />
              <button
                type="button"
                class="max-w-[12rem] truncate rounded-md px-2 py-1 text-sm transition-colors duration-150 hover:bg-overlay-subtle focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
                :class="i === crumbs.length - 1 ? 'font-medium text-content' : 'text-content-secondary hover:text-content'"
                @click="navigateTo(crumb.path)"
              >
                {{ crumb.name }}
              </button>
            </template>
          </div>
          <IconButton aria-label="Type a folder path" @click="startPathEdit">
            <PencilIcon class="h-4 w-4" />
          </IconButton>
        </template>
      </div>

      <!-- Sidebar + listing -->
      <div class="flex min-h-0 flex-1">
        <div class="w-48 shrink-0 space-y-4 overflow-y-auto border-r border-edge-subtle px-2 py-3 custom-scrollbar">
          <div v-for="group in sidebarGroups" :key="group.label">
            <div class="px-2.5 pb-1 text-xs font-semibold text-content-secondary">{{ group.label }}</div>
            <button
              v-for="root in group.roots"
              :key="root.path"
              type="button"
              class="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
              :class="activeRootPath === root.path ? 'bg-accent/15 text-accent' : 'text-content hover:bg-overlay-subtle'"
              @click="navigateTo(root.path)"
            >
              <component :is="rootIcon(root)" class="h-4 w-4 shrink-0" :class="activeRootPath === root.path ? '' : 'text-content-tertiary'" />
              <span class="truncate">{{ root.name }}</span>
            </button>
          </div>

          <div v-if="recents.length">
            <div class="px-2.5 pb-1 text-xs font-semibold text-content-secondary">Recent</div>
            <Tooltip v-for="recent in recents" :key="recent.path" :text="recent.path" class="w-full">
              <button
                type="button"
                class="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-sm text-content transition-colors duration-150 hover:bg-overlay-subtle focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
                @click="navigateTo(recent.path)"
              >
                <ClockIcon class="h-4 w-4 shrink-0 text-content-tertiary" />
                <span class="truncate">{{ recent.name }}</span>
              </button>
            </Tooltip>
          </div>
        </div>

        <div
          ref="listEl"
          tabindex="0"
          class="min-h-0 flex-1 overflow-y-auto outline-none custom-scrollbar focus-visible:ring-2 ring-inset ring-accent/40"
          @keydown="handleListKeydown"
        >
          <div v-if="loading" class="flex h-full items-center justify-center p-8">
            <Spinner size="lg" />
          </div>

          <div v-else-if="error" class="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
            <span class="text-sm text-red-400">{{ error }}</span>
            <button
              v-if="listing"
              type="button"
              class="text-xs text-content-secondary hover:text-content"
              @click="navigateTo(listing.path, { recordHistory: false })"
            >
              Back to {{ basename(listing.path) || 'folders' }}
            </button>
          </div>

          <div v-else-if="!entries.length" class="flex h-full flex-col items-center justify-center gap-2 p-8 text-content-tertiary">
            <FolderOpenIcon class="h-8 w-8 opacity-50" />
            <span class="text-sm">No subfolders</span>
          </div>

          <div v-else class="py-1">
            <div
              v-for="entry in entries"
              :key="entry.path"
              role="button"
              :data-selected="selectedPath === entry.path ? 'true' : undefined"
              class="group flex w-full cursor-pointer select-none items-center gap-2.5 px-4 py-2 text-left transition-colors duration-150"
              :class="selectedPath === entry.path ? 'bg-selection/15' : 'hover:bg-overlay-subtle'"
              @click="handleEntryClick(entry)"
              @dblclick="handleEntryOpen(entry)"
            >
              <FolderIcon class="h-4 w-4 shrink-0" :class="selectedPath === entry.path ? 'text-content' : 'text-content-tertiary'" />
              <span class="truncate text-sm" :class="selectedPath === entry.path ? 'font-medium text-content' : 'text-content'">
                {{ entry.name }}
              </span>
              <span
                v-if="entry.item_count != null"
                class="ml-auto shrink-0 font-mono text-xs tabular-nums text-content-tertiary"
              >
                {{ entry.item_count }}
              </span>
              <button
                type="button"
                aria-label="Open folder"
                class="shrink-0 rounded-md p-1 text-content-tertiary transition-colors duration-150 hover:bg-overlay-subtle hover:text-content focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
                :class="[
                  entry.item_count == null ? 'ml-auto' : '',
                  selectedPath === entry.path ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus-visible:opacity-100',
                ]"
                @click.stop="handleEntryOpen(entry)"
              >
                <ChevronRightIcon class="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="flex min-w-0 flex-1 items-center gap-2 truncate text-xs text-content-secondary">
        <template v-if="selectedPath">
          <span class="shrink-0">Selected</span>
          <span class="truncate rounded-md bg-overlay-subtle px-1.5 py-0.5 font-mono text-content select-text">{{ selectedPath }}</span>
        </template>
        <template v-else>Select a folder</template>
      </div>
      <Button variant="secondary" @click="cancel">Cancel</Button>
      <Button variant="primary" :disabled="!selectedPath" class="max-w-[16rem]" @click="choose">
        <span class="truncate">{{ selectedName ? `Choose “${selectedName}”` : 'Choose folder' }}</span>
      </Button>
    </template>
  </Modal>
</template>
