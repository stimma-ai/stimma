<template>
  <!-- Full-screen overlay that appears when dragging files over the window -->
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="isDragging"
        class="fixed inset-0 z-[9999] flex items-center justify-center bg-black/70 backdrop-blur-sm"
        @dragover.prevent
      >
        <div class="flex flex-col items-center gap-4 p-8 border-2 border-dashed border-blue-500 rounded-xl bg-surface/90">
          <!-- Upload icon -->
          <svg class="w-16 h-16 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
          </svg>
          <div class="text-xl font-medium text-content">Drop files to upload</div>
          <div class="text-sm text-content-tertiary">Images and videos will be added to your library</div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useLibraryUpload } from '../composables/useLibraryUpload'

const { uploadFiles } = useLibraryUpload()
const route = useRoute()

const isDragging = ref(false)
const projectId = computed(() => {
  if (!String(route.name || '').startsWith('project-')) return null
  const raw = route.params.id
  if (typeof raw !== 'string' || !raw.trim()) return null
  const parsed = Number.parseInt(raw, 10)
  return Number.isFinite(parsed) ? parsed : null
})

// Counter to handle nested drag events correctly
let dragCounter = 0

/**
 * Check if the target element is inside a component-level drop zone.
 * These should handle their own drops and not trigger the global overlay.
 */
function isInsideDropZone(target: EventTarget | null): boolean {
  if (!target || !(target instanceof Element)) return false
  return target.closest('[data-drop-zone]') !== null
}

function handleDragEnter(e: DragEvent) {
  // Skip if inside a component-level drop zone
  if (isInsideDropZone(e.target)) return

  // Skip if not dragging files
  if (!e.dataTransfer?.types.includes('Files')) return

  dragCounter++
  if (dragCounter === 1) {
    isDragging.value = true
  }
}

function handleDragLeave(e: DragEvent) {
  // Skip if inside a component-level drop zone
  if (isInsideDropZone(e.target)) return

  dragCounter--
  if (dragCounter <= 0) {
    dragCounter = 0
    isDragging.value = false
  }
}

function handleDragOver(e: DragEvent) {
  // ALWAYS prevent default to stop browser from opening files
  // Even if we're inside a drop zone, we don't want the browser default
  if (e.dataTransfer?.types.includes('Files')) {
    e.preventDefault()
  }
}

async function handleDrop(e: DragEvent) {
  // ALWAYS prevent default for file drops to stop browser from opening files
  if (e.dataTransfer?.types.includes('Files')) {
    e.preventDefault()
  }

  // Reset drag state
  isDragging.value = false
  dragCounter = 0

  // Skip if inside a component-level drop zone (they handle their own drops)
  if (isInsideDropZone(e.target)) return

  if (!e.dataTransfer) return

  // Extract files, including from folders
  const files = await extractFiles(e.dataTransfer)

  if (files.length > 0) {
    console.log(`[GlobalDropOverlay] Uploading ${files.length} files`)
    await uploadFiles(files, undefined, projectId.value)
  }
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

onMounted(() => {
  document.addEventListener('dragenter', handleDragEnter)
  document.addEventListener('dragleave', handleDragLeave)
  document.addEventListener('dragover', handleDragOver)
  document.addEventListener('drop', handleDrop)
})

onUnmounted(() => {
  document.removeEventListener('dragenter', handleDragEnter)
  document.removeEventListener('dragleave', handleDragLeave)
  document.removeEventListener('dragover', handleDragOver)
  document.removeEventListener('drop', handleDrop)
})
</script>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
