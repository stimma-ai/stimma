<template>
  <div
    class="flex-1 flex flex-col items-center p-6 overflow-hidden"
    @dragenter="handleDragEnter"
    @dragleave="handleDragLeave"
    @dragover.prevent
    @drop="handleDrop"
  >
    <!-- Slideshow overlay -->
    <SlideshowMode
      v-if="slideshowState.active"
      :total-count="slideshowState.totalCount"
      :start-index="slideshowState.startIndex"
      :page-provider="slideshowState.pageProvider"
      :inline="true"
      @close="exitSlideshow"
    />

    <!-- Drop target area — flex-1 so it fills available space and shrinks when grid is present -->
    <div
      class="w-full max-w-2xl flex-1 min-h-0 flex flex-col items-center justify-center gap-4 border-2 border-dashed rounded-lg transition-all duration-200 relative"
      :class="isDragging
        ? 'border-blue-500 bg-blue-500/10 scale-[1.02]'
        : 'border-edge bg-overlay-faint hover:border-edge-strong hover:bg-overlay-subtle'"
    >
      <!-- Auto-mark options (top right) -->
      <div v-if="availableMarkers.length > 0" class="absolute top-4 right-4">
        <AutoMarkPicker
          :markers="availableMarkers"
          v-model="selectedMarkerIds"
        />
      </div>

      <!-- Upload icon -->
      <div
        class="w-16 h-16 rounded-full flex items-center justify-center transition-all duration-200"
        :class="isDragging ? 'bg-blue-500/20' : 'bg-overlay-subtle'"
      >
        <svg
          class="w-8 h-8 transition-colors duration-200"
          :class="isDragging ? 'text-blue-500' : 'text-content-muted'"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          stroke-width="1.5"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
        </svg>
      </div>

      <div class="text-center">
        <h2 class="text-lg font-medium text-content mb-1">
          {{ isDragging ? 'Drop to upload' : 'Drag files here to upload' }}
        </h2>
        <p class="text-sm text-content-tertiary">
          Images and videos will be imported
        </p>
      </div>

      <!-- Browse button -->
      <button
        class="px-6 py-2.5 bg-accent hover:bg-accent/90 text-white font-medium rounded-md transition-colors"
        @click="openFilePicker"
      >
        Browse Files
      </button>
      <input v-no-autocorrect
        ref="fileInput"
        type="file"
        multiple
        accept="image/*,video/*"
        class="hidden"
        @change="handleFileSelect"
      />
    </div>

    <!-- Bottom section: progress + thumbnail grid (fixed height, never overlaps drop area) -->
    <div v-if="showProgress || uploadedMedia.length > 0" class="w-full max-w-2xl flex-shrink-0 mt-4">
      <!-- Progress header + bar -->
      <div v-if="showProgress">
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center gap-3">
            <div v-if="progress.isUploading" class="w-5 h-5 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin"></div>
            <div v-else-if="progress.failed === 0" class="w-5 h-5 rounded-full bg-green-500 flex items-center justify-center">
              <svg class="w-3 h-3 text-content" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="m4.5 12.75 6 6 9-13.5" />
              </svg>
            </div>
            <div v-else class="w-5 h-5 rounded-full bg-red-500 flex items-center justify-center">
              <svg class="w-3 h-3 text-content" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 1 1-18 0 9 9 0 0 1 18 0Zm-9 3.75h.008v.008H12v-.008Z" />
              </svg>
            </div>
            <span class="text-content font-medium">{{ statusText }}</span>
          </div>
          <button
            v-if="!progress.isUploading"
            class="text-sm text-content-tertiary hover:text-content-secondary transition-colors"
            @click="clearAll"
          >
            Clear
          </button>
        </div>
        <div class="h-1.5 bg-overlay-light rounded-full overflow-hidden mb-3">
          <div
            class="h-full transition-all duration-300 rounded-full"
            :class="progress.failed > 0 && !progress.isUploading ? 'bg-red-500' : 'bg-blue-500'"
            :style="{ width: percentComplete + '%' }"
          ></div>
        </div>
      </div>

      <!-- Thumbnail grid: exactly 2 rows of 6 -->
      <div v-if="uploadedMedia.length > 0" class="grid gap-1.5" style="grid-template-columns: repeat(6, 1fr)">
        <div
          v-for="(item, index) in visibleMedia"
          :key="item.media_id"
          class="aspect-square rounded-media overflow-hidden cursor-pointer"
          @click="openSlideshow(index)"
        >
          <AppImage
            :src="getThumbnailUrl(item.file_hash)"
            :alt="item.filename"
            container-class="w-full h-full"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useLibraryUpload, type UploadResult } from '../composables/useLibraryUpload'
import { useMediaApi } from '../composables/useMediaApi'
import { useSlideshow } from '../composables/useSlideshow'
import { AutoMarkPicker } from '../components/generation'
import { AppImage } from '../components/media'
import SlideshowMode from '../components/SlideshowMode.vue'

const router = useRouter()
const route = useRoute()

interface Marker {
  id: number
  name: string
  icon_svg: string
  color: string
}

const { progress, showProgress, percentComplete, statusText, uploadFiles, clearProgress, filterMediaFiles } = useLibraryUpload()
const { getMarkers, getThumbnailUrl } = useMediaApi()
const { slideshowState, enterSlideshow, exitSlideshow } = useSlideshow()

const isDragging = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const uploadedMedia = ref<UploadResult[]>([])
const MAX_GRID_ROWS = 2
const GRID_COLS = 6 // matches md:grid-cols-6 (largest breakpoint)
const visibleMedia = computed(() => uploadedMedia.value.slice(0, MAX_GRID_ROWS * GRID_COLS))
const availableMarkers = ref<Marker[]>([])
const selectedMarkerIds = ref<number[]>([])
const projectId = computed(() => {
  const raw = route.query.project_id
  if (typeof raw !== 'string' || !raw.trim()) return null
  const parsed = Number.parseInt(raw, 10)
  return Number.isFinite(parsed) ? parsed : null
})

// Handle markers config change
async function handleMarkersChanged() {
  try {
    availableMarkers.value = await getMarkers()
  } catch (error) {
    console.error('Failed to reload markers:', error)
  }
}

function clearAll() {
  clearProgress()
  uploadedMedia.value = []
}

// Handle Escape key to dismiss
function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && !slideshowState.active) {
    router.back()
  }
}

// Load available markers on mount
onMounted(async () => {
  try {
    availableMarkers.value = await getMarkers()
  } catch (error) {
    console.error('Failed to load markers:', error)
  }
  window.addEventListener('markers-changed', handleMarkersChanged)
  window.addEventListener('keydown', handleKeydown)
})

onUnmounted(() => {
  window.removeEventListener('markers-changed', handleMarkersChanged)
  window.removeEventListener('keydown', handleKeydown)
})

// Counter to handle nested drag events correctly
let dragCounter = 0

function handleDragEnter(e: DragEvent) {
  if (!e.dataTransfer?.types.includes('Files')) return

  dragCounter++
  if (dragCounter === 1) {
    isDragging.value = true
  }
}

function handleDragLeave(e: DragEvent) {
  dragCounter--
  if (dragCounter <= 0) {
    dragCounter = 0
    isDragging.value = false
  }
}

async function handleDrop(e: DragEvent) {
  e.preventDefault()
  isDragging.value = false
  dragCounter = 0

  if (!e.dataTransfer) return

  const files = await extractFiles(e.dataTransfer)
  if (files.length > 0) {
    await doUpload(files)
  }
}

function openFilePicker() {
  fileInput.value?.click()
}

async function handleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files || input.files.length === 0) return

  const files = Array.from(input.files)
  await doUpload(files)

  // Clear the input so the same files can be selected again
  input.value = ''
}

async function doUpload(files: File[]) {
  const mediaFiles = filterMediaFiles(files)
  if (mediaFiles.length === 0) return

  const results = await uploadFiles(mediaFiles, selectedMarkerIds.value, projectId.value)
  const successful = results.filter(r => r.status === 'success' && r.file_hash && r.media_id)
  // Prepend newest first, dedup by media_id
  const existingIds = new Set(uploadedMedia.value.map(m => m.media_id))
  const fresh = successful.reverse().filter(r => !existingIds.has(r.media_id))
  uploadedMedia.value = [...fresh, ...uploadedMedia.value]
}

function openSlideshow(index: number) {
  const items = uploadedMedia.value
  enterSlideshow({
    totalCount: items.length,
    startIndex: index,
    pageProvider: async (pageNumber: number, pageSize: number) => {
      const start = pageNumber * pageSize
      return items.slice(start, start + pageSize).map(r => ({
        id: r.media_id,
        file_hash: r.file_hash,
        width: r.width || 512,
        height: r.height || 512,
        file_format: r.filename?.split('.').pop()?.toLowerCase() || 'png',
      }))
    },
  })
}

/**
 * Extract files from DataTransfer, recursively traversing folders.
 */
async function extractFiles(dataTransfer: DataTransfer): Promise<File[]> {
  const files: File[] = []
  const items = Array.from(dataTransfer.items)

  // Try to use webkitGetAsEntry for folder support
  const entries = items
    .map(item => item.webkitGetAsEntry?.())
    .filter((entry): entry is FileSystemEntry => entry !== null && entry !== undefined)

  if (entries.length > 0) {
    // Use FileSystem API for folder traversal
    await Promise.all(entries.map(entry => traverseEntry(entry, files)))
  } else {
    // Fallback to simple file list
    files.push(...Array.from(dataTransfer.files))
  }

  return files
}

/**
 * Recursively traverse a FileSystemEntry to extract all files.
 */
async function traverseEntry(entry: FileSystemEntry, files: File[]): Promise<void> {
  if (entry.isFile) {
    const fileEntry = entry as FileSystemFileEntry
    const file = await new Promise<File>((resolve, reject) => {
      fileEntry.file(resolve, reject)
    })
    files.push(file)
  } else if (entry.isDirectory) {
    const dirEntry = entry as FileSystemDirectoryEntry
    const reader = dirEntry.createReader()

    // Read all entries in the directory
    const readEntries = (): Promise<FileSystemEntry[]> => {
      return new Promise((resolve, reject) => {
        reader.readEntries(resolve, reject)
      })
    }

    // Keep reading until we get an empty result (API returns entries in batches)
    let entries: FileSystemEntry[] = []
    let batch: FileSystemEntry[]
    do {
      batch = await readEntries()
      entries = entries.concat(batch)
    } while (batch.length > 0)

    // Recursively process all entries
    await Promise.all(entries.map(e => traverseEntry(e, files)))
  }
}
</script>

<style scoped>
/* KeepAlive component name for router */
</style>
