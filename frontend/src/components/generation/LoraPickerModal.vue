<template>
  <!-- Wide: a submenu-tier Modal. Compact / coarse: the kit bottom Sheet
       (DESIGN.md §1.11) — full width, safe-area padded, search pinned in the
       header, rows at touch height. One body, two shells. -->
  <component
    :is="asSheet ? Sheet : Modal"
    :show="true"
    v-bind="asSheet ? { title: 'Add LoRA' } : { submenu: true, size: 'custom', customClass: 'w-[760px] max-w-[95vw] max-h-[70vh] flex flex-col' }"
    @close="$emit('close')"
  >
    <template #header>
      <div class="flex items-center justify-between gap-2">
        <div class="flex items-center gap-2 min-w-0">
          <h3 class="font-semibold text-content truncate" :class="asSheet ? 'text-[14px]' : 'text-lg'">Add LoRA</h3>
          <Spinner v-if="isRefreshing || isUploading" size="md" />
        </div>
        <div class="flex items-center gap-1">
          <input
            ref="fileInputRef"
            type="file"
            multiple
            class="hidden"
            :accept="fileAcceptString"
            @change="onFileInputChange"
          />
          <button
            v-if="uploadConfig"
            @click="fileInputRef?.click()"
            type="button"
            class="text-xs font-semibold text-content-secondary hover:text-accent transition-colors px-2 min-h-8 coarse:min-h-11 coarse:px-3 rounded-md"
          >Upload</button>
          <button
            @click="$emit('toggle-raw')"
            type="button"
            :class="[
              'text-xs font-semibold transition-colors px-2 min-h-8 coarse:min-h-11 coarse:px-3 rounded-md',
              showRaw ? 'text-accent' : 'text-content-secondary hover:text-content'
            ]"
          >Raw</button>
          <IconButton v-if="!asSheet" @click="$emit('close')">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
              <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
            </svg>
          </IconButton>
        </div>
      </div>
      <!-- Sheet: the search field is pinned under the title; the list scrolls beneath it. -->
      <div v-if="asSheet" class="pt-2 pb-1">
        <div class="relative">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-content-muted pointer-events-none">
            <path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
          </svg>
          <input v-no-autocorrect
            ref="searchInput"
            v-model="searchQuery"
            type="search"
            placeholder="Search LoRAs..."
            class="w-full min-h-11 pl-10 pr-4 py-2 bg-overlay-subtle rounded-md border border-transparent text-content text-sm placeholder:text-content-muted focus:border-accent focus-visible:ring-2 ring-accent/40 outline-none transition-colors [&::-webkit-search-cancel-button]:appearance-none"
            @keydown.enter="addSelected"
            @keydown.escape="$emit('close')"
          />
        </div>
      </div>
    </template>

    <!-- Search Input (wide) -->
    <div v-if="!asSheet" class="p-4 border-b border-edge-subtle">
      <div class="relative">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-content-muted"
        >
          <path fill-rule="evenodd" d="M9 3.5a5.5 5.5 0 100 11 5.5 5.5 0 000-11zM2 9a7 7 0 1112.452 4.391l3.328 3.329a.75.75 0 11-1.06 1.06l-3.329-3.328A7 7 0 012 9z" clip-rule="evenodd" />
        </svg>
        <input v-no-autocorrect
          ref="searchInput"
          v-model="searchQuery"
          type="text"
          placeholder="Search LoRAs..."
          class="w-full pl-10 pr-4 py-2.5 bg-overlay-subtle rounded-md border border-transparent text-content text-sm placeholder:text-content-muted focus:border-accent focus-visible:ring-2 ring-accent/40 outline-none transition-colors"
          @keydown.enter="addSelected"
          @keydown.escape="$emit('close')"
          @keydown.down.prevent="navigateDown"
          @keydown.up.prevent="navigateUp"
        />
      </div>
    </div>

    <!-- Results List. In the Sheet the shell scrolls; in the Modal this box does. -->
    <div
      :class="[
        'relative py-1',
        asSheet ? 'min-h-[40dvh]' : 'flex-1 custom-scrollbar overflow-y-auto min-h-[200px]',
        isDraggingFile ? 'bg-accent/5' : ''
      ]"
      @dragover.prevent="onFileDragOver"
      @dragleave="onFileDragLeave"
      @drop.prevent="onFileDrop"
    >
      <div
        v-if="isDraggingFile"
        class="absolute inset-2 z-10 rounded-lg ring-1 ring-accent/50 flex items-center justify-center pointer-events-none bg-accent/10"
      >
        <span class="text-accent text-xs font-medium">Drop LoRA file</span>
      </div>

      <div
        v-if="isUploading"
        class="mx-4 my-2 rounded-lg border border-accent/30 bg-accent/5 px-3 py-2 flex items-center gap-2.5"
      >
        <Spinner size="sm" />
        <div class="flex-1 min-w-0">
          <div class="text-xs text-content-muted mb-1 truncate">{{ uploadFileName || 'Uploading LoRA...' }}</div>
          <ProgressBar :value="uploadProgress ?? 0" />
        </div>
      </div>

      <div v-if="filteredLoras.length === 0" class="text-center text-content-muted py-12">
        {{ searchQuery ? 'No LoRAs match your search' : 'No LoRAs available' }}
      </div>

      <button
        v-for="(lora, index) in filteredLoras"
        :key="lora.path"
        :ref="el => setItemRef(index, el)"
        @click="addLora(lora)"
        type="button"
        :class="[
          'w-full px-4 py-2 coarse:min-h-11 text-left transition-colors flex items-center justify-between gap-3',
          isInPool(lora.path)
            ? 'bg-accent-selection/15 text-accent-selection'
            : index === selectedIndex && !asSheet
              ? 'bg-overlay-subtle text-content'
              : 'hover:bg-overlay-subtle text-content-secondary'
        ]"
        @mouseenter="selectedIndex = index"
      >
        <span v-if="showRaw" class="text-sm min-w-0 flex-1">
          <span class="truncate block">{{ getRawFileName(lora.path) }}</span>
          <span v-if="getDirectoryPath(lora.path)" class="text-[10px] text-content-muted truncate block">{{ getDirectoryPath(lora.path) }}</span>
        </span>
        <!-- Name first, tag chips after; on a narrow row the chips wrap under
             the name instead of pushing past the edge. -->
        <span v-else class="text-sm flex flex-wrap items-center gap-x-1.5 gap-y-1 min-w-0 flex-1">
          <span class="font-medium truncate max-w-full">{{ smartNames[lora.path]?.primary || getRawDisplayName(lora.path) }}</span>
          <span
            v-for="chip in (smartNames[lora.path]?.secondary || '').split(' ').filter(Boolean)"
            :key="chip"
            class="shrink-0 text-[10px] leading-none px-1.5 py-0.5 rounded bg-overlay-subtle text-content-tertiary font-mono lowercase"
          >{{ chip }}</span>
        </span>
        <!-- Checkmark for selected items -->
        <svg
          v-if="isInPool(lora.path)"
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          class="w-4 h-4 text-accent-selection flex-shrink-0"
        >
          <path fill-rule="evenodd" d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z" clip-rule="evenodd" />
        </svg>
        <!-- Plus icon for unselected items -->
        <svg
          v-else
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
          class="w-4 h-4 text-content-tertiary flex-shrink-0"
        >
          <path d="M10.75 4.75a.75.75 0 0 0-1.5 0v4.5h-4.5a.75.75 0 0 0 0 1.5h4.5v4.5a.75.75 0 0 0 1.5 0v-4.5h4.5a.75.75 0 0 0 0-1.5h-4.5v-4.5Z" />
        </svg>
      </button>
    </div>
  </component>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
import type { LoraPoolItem, LoraOption } from '../../composables/useLoraPool'
import { computeDisplayNames, getRawDisplayName, getRawFileName, getDirectoryPath } from '../../composables/useLoraDisplayNames'
import { addToast } from '../../composables/useToasts'
import { useViewport } from '../../composables/useViewport'
import Modal from '../ui/Modal.vue'
import Sheet from '../ui/Sheet.vue'
import IconButton from '../ui/IconButton.vue'
import Spinner from '../ui/Spinner.vue'
import ProgressBar from '../ui/ProgressBar.vue'

interface Props {
  availableLoras: LoraOption[]
  poolLoras: LoraPoolItem[]
  isRefreshing?: boolean
  showRaw?: boolean
  modelName?: string | null
  isUploading?: boolean
  uploadProgress?: number | null
  uploadFileName?: string | null
  uploadConfig?: UploadConfig | null
}

interface UploadConfig {
  extensions: string[]
  max_size: number
}

const props = withDefaults(defineProps<Props>(), {
  showRaw: false,
  modelName: null,
  isUploading: false,
  uploadProgress: null,
  uploadFileName: null,
  uploadConfig: null,
})

const emit = defineEmits<{
  (e: 'add', lora: LoraOption): void
  (e: 'remove', lora: LoraOption): void
  (e: 'close'): void
  (e: 'refresh-loras'): void
  (e: 'toggle-raw'): void
  (e: 'upload', files: File[]): void
}>()

const { isCompact, isCoarsePointer } = useViewport()
const asSheet = computed(() => isCompact.value || isCoarsePointer.value)

const searchQuery = ref('')
const selectedIndex = ref(0)
const searchInput = ref<HTMLInputElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const itemRefs = ref<Record<number, HTMLElement | null>>({})
const isDraggingFile = ref(false)
let fileDragLeaveTimer: ReturnType<typeof setTimeout> | null = null

const fileAcceptString = computed(() => props.uploadConfig?.extensions?.join(',') || undefined)

function setItemRef(index: number, el: any) {
  if (el) {
    itemRefs.value[index] = el as HTMLElement
  }
}

// Unicode normalization for search (removes accents, spaces)
function normalizeString(str: string): string {
  return str
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[\/_.\-\s]+/g, '')
    .toLowerCase()
}

const allSmartNames = computed(() => {
  const paths = props.availableLoras.map(l => l.path)
  return computeDisplayNames(paths, props.modelName || undefined)
})

function buildSearchText(lora: LoraOption): string {
  const filename = getRawFileName(lora.path)
  const directory = getDirectoryPath(lora.path)
  const smart = allSmartNames.value[lora.path]
  return [
    lora.path,
    filename,
    directory,
    lora.name,
    smart?.primary || '',
    smart?.secondary || ''
  ].join(' ')
}

// Filter results against full path + filename + display labels.
const filteredLoras = computed(() => {
  const query = normalizeString(searchQuery.value)

  if (!query) {
    return props.availableLoras
  }

  return props.availableLoras.filter(lora => normalizeString(buildSearchText(lora)).includes(query))
})

// Smart names for all available loras in the current filtered view
const smartNames = computed(() => {
  const paths = filteredLoras.value.map(l => l.path)
  return computeDisplayNames(paths, props.modelName || undefined)
})

// Check if a LoRA is already in the pool
function isInPool(path: string): boolean {
  return props.poolLoras.some(item => item.lora === path)
}

// Toggle a LoRA in the pool
function addLora(lora: LoraOption) {
  if (isInPool(lora.path)) {
    emit('remove', lora)
  } else {
    emit('add', lora)
  }
}

// Toggle the currently selected LoRA
function addSelected() {
  const lora = filteredLoras.value[selectedIndex.value]
  if (lora) {
    addLora(lora)
  }
}

function onFileDragOver(event: DragEvent) {
  if (!props.uploadConfig) return
  if (!event.dataTransfer?.types.includes('Files')) return
  if (fileDragLeaveTimer) { clearTimeout(fileDragLeaveTimer); fileDragLeaveTimer = null }
  isDraggingFile.value = true
}

function onFileDragLeave() {
  fileDragLeaveTimer = setTimeout(() => { isDraggingFile.value = false }, 50)
}

function onFileDrop(event: DragEvent) {
  isDraggingFile.value = false
  if (!props.uploadConfig) return
  const fileList = event.dataTransfer?.files
  if (!fileList || fileList.length === 0) return

  emitValidUploadFiles(Array.from(fileList))
}

function onFileInputChange(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  emitValidUploadFiles(files)
}

function emitValidUploadFiles(files: File[]) {
  if (!props.uploadConfig || files.length === 0) return

  const validFiles: File[] = []
  const errors: string[] = []

  for (const file of files) {
    if (props.uploadConfig.extensions?.length) {
      const ext = '.' + file.name.split('.').pop()?.toLowerCase()
      if (!props.uploadConfig.extensions.some(e => e.toLowerCase() === ext)) {
        errors.push(`${file.name}: invalid type`)
        continue
      }
    }
    if (props.uploadConfig.max_size && file.size > props.uploadConfig.max_size) {
      const maxMb = Math.round(props.uploadConfig.max_size / (1024 * 1024))
      errors.push(`${file.name}: exceeds ${maxMb} MB`)
      continue
    }
    validFiles.push(file)
  }

  if (errors.length > 0) {
    addToast(`Skipped ${errors.length} file(s): ${errors.join('; ')}`, 'warning', 8000)
  }

  if (validFiles.length > 0) {
    emit('upload', validFiles)
  }
}

function navigateDown() {
  selectedIndex.value = Math.min(selectedIndex.value + 1, filteredLoras.value.length - 1)
  scrollToSelected()
}

function navigateUp() {
  selectedIndex.value = Math.max(selectedIndex.value - 1, 0)
  scrollToSelected()
}

function scrollToSelected() {
  nextTick(() => {
    const el = itemRefs.value[selectedIndex.value]
    if (el) {
      el.scrollIntoView({ block: 'nearest' })
    }
  })
}

// Reset selection when results change
watch(filteredLoras, () => {
  selectedIndex.value = 0
})

// Auto-focus (wide only: on a phone the keyboard would cover the list before
// the user has seen it) and trigger refresh on mount
onMounted(() => {
  if (!asSheet.value) {
    nextTick(() => {
      searchInput.value?.focus()
    })
  }
  emit('refresh-loras')
})
</script>
