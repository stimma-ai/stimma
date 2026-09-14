<template>
  <div ref="container" class="flex flex-wrap gap-2 w-full compact:flex-col">
    <div v-for="file in liveFiles" :key="file.root + file.path" class="group relative rounded-lg border border-edge-subtle min-w-0 w-64 max-w-full compact:w-full hover:bg-overlay-subtle" :class="[missing.has(file.root + file.path) ? 'opacity-50' : '', selected?.root === file.root && selected?.path === file.path ? 'ring-2 ring-inset ring-selection' : '']" :draggable="!missing.has(file.root + file.path)" @dragstart="cancelPress(); dragWorkspaceFile($event, chatId, file)" @contextmenu.prevent="menuFile = file" @pointerdown="startPress($event, file)" @pointerup="cancelPress" @pointercancel="cancelPress" @pointermove="cancelPress">
      <button class="block p-2 text-left w-full focus-visible:outline-none focus-visible:ring-2 ring-accent/60 rounded-md" :disabled="missing.has(file.root + file.path)" @click="preview(file)">
        <span class="flex items-center gap-2.5">
        <FileChipIcon :name="file.name" :mime="file.mime" />
        <span class="min-w-0 flex-1" :class="isCoarsePointer ? 'pr-8' : ''"><span class="block truncate text-sm font-medium text-content">{{ file.name }}</span><span class="block truncate text-xs text-content-muted">{{ missing.has(file.root + file.path) ? 'No longer in workspace' : fileStats(file) }}</span></span>
        </span>
      </button>
      <button v-if="isCoarsePointer && !missing.has(file.root + file.path)" class="absolute right-0 top-0 min-h-11 min-w-11 text-content-muted" aria-label="File actions" @click.stop="menuFile = file">⋯</button>
    </div>
    <Sheet :show="!!menuFile" :title="menuFile?.name || ''" @close="menuFile = null">
      <template v-if="menuFile">
        <button class="sheet-row w-full" @click="act('preview')">Preview</button>
        <a :href="fileUrl(chatId, menuFile, 'content', true)" class="sheet-row w-full" @click="menuFile = null">Download</a>
        <button v-if="canSaveFileToLibrary(menuFile)" class="sheet-row w-full" @click="act('save')">Save to library</button>
        <button class="sheet-row w-full" @click="act('attach')">Attach to reply</button>
      </template>
    </Sheet>
  </div>
</template>
<script setup lang="ts">
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import axios from 'axios'
import FileChipIcon from './FileChipIcon.vue'
import Sheet from '../ui/Sheet.vue'
import { useViewport } from '../../composables/useViewport'
import { fileUrl, fileStats, canSaveFileToLibrary, dragWorkspaceFile, type WorkspaceFile } from '../../utils/fileRefs'
const props = defineProps<{ files: WorkspaceFile[]; chatId: number | string; selected?: WorkspaceFile | null }>()
const emit = defineEmits<{ refreshed: [file: WorkspaceFile]; preview: [file: WorkspaceFile]; save: [file: WorkspaceFile]; attach: [file: WorkspaceFile] }>()
const liveFiles = ref<WorkspaceFile[]>([]), missing = ref(new Set<string>())
const { isCoarsePointer } = useViewport()
const menuFile = ref<WorkspaceFile | null>(null)
let pressTimer: ReturnType<typeof setTimeout> | null = null, longPressed = false
function cancelPress() { if (pressTimer) clearTimeout(pressTimer); pressTimer = null }
function startPress(event: PointerEvent, file: WorkspaceFile) {
  longPressed = false
  if (event.pointerType === 'mouse') return
  pressTimer = setTimeout(() => { longPressed = true; menuFile.value = file }, 500)
}
function preview(file: WorkspaceFile) { if (!longPressed) emit('preview', file) }
function act(action: 'preview' | 'save' | 'attach') { if (menuFile.value) emit(action, menuFile.value); menuFile.value = null }
let generation = 0
async function refresh() {
  const version = ++generation
  const result = await Promise.all(props.files.map(async file => {
    try { return { file: { ...file, ...(await axios.get(fileUrl(props.chatId, file, 'info'))).data }, missing: false } }
    catch (e: any) { return { file, missing: e.response?.status === 404 } }
  }))
  if (version !== generation) return
  liveFiles.value = result.map(row => row.file)
  for (const row of result) if (!row.missing) emit('refreshed', row.file)
  missing.value = new Set(result.filter(row => row.missing).map(row => row.file.root + row.file.path))
}
watch(() => JSON.stringify([props.chatId, props.files]), () => { liveFiles.value = props.files; refresh() }, { immediate: true })
const container = ref<HTMLElement | null>(null)
let visible = true
let observer: IntersectionObserver | null = null
function refreshVisible() { if (visible && document.visibilityState === 'visible') refresh() }
let timer: ReturnType<typeof setInterval>
onMounted(() => {
  observer = new IntersectionObserver(([entry]) => { visible = entry.isIntersecting })
  if (container.value) observer.observe(container.value)
  timer = setInterval(refreshVisible, 15000)
  window.addEventListener('focus', refreshVisible)
})
onBeforeUnmount(() => { generation++; cancelPress(); clearInterval(timer); observer?.disconnect(); window.removeEventListener('focus', refreshVisible) })
</script>
