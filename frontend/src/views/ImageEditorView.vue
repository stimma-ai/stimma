<template>
  <div class="w-full h-full bg-surface flex flex-col">
    <!-- Landing state - no image selected -->
    <div
      v-show="!mediaId && !imageUrl"
      class="flex-1 flex items-center justify-center transition-colors"
      :class="isDragOver ? 'bg-accent/10 ring-1 ring-inset ring-accent/50' : ''"
      @dragover="handleLandingDragOver"
      @dragenter="handleLandingDragEnter"
      @dragleave="handleLandingDragLeave"
      @drop="handleLandingDrop"
    >
      <div class="text-center max-w-md px-6 pointer-events-none">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-16 h-16 mx-auto mb-6 text-accent">
          <path d="M21.731 2.269a2.625 2.625 0 00-3.712 0l-1.157 1.157 3.712 3.712 1.157-1.157a2.625 2.625 0 000-3.712zM19.513 8.199l-3.712-3.712-8.4 8.4a5.25 5.25 0 00-1.32 2.214l-.8 2.685a.75.75 0 00.933.933l2.685-.8a5.25 5.25 0 002.214-1.32l8.4-8.4z" />
          <path d="M5.25 5.25a3 3 0 00-3 3v10.5a3 3 0 003 3h10.5a3 3 0 003-3V13.5a.75.75 0 00-1.5 0v5.25a1.5 1.5 0 01-1.5 1.5H5.25a1.5 1.5 0 01-1.5-1.5V8.25a1.5 1.5 0 011.5-1.5h5.25a.75.75 0 000-1.5H5.25z" />
        </svg>
        <h2 class="text-xl font-semibold text-content font-brand mb-3">Edit Image</h2>
        <p class="text-content-tertiary mb-6 leading-relaxed">
          A powerful non-destructive editor for your images. Crop, adjust colors, apply filters, add annotations, and retouch photos.
        </p>
        <div class="space-y-3 text-sm text-content-tertiary">
          <div class="flex items-center gap-3 justify-center">
            <svg class="w-4 h-4 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15.042 21.672L13.684 16.6m0 0l-2.51 2.225.569-9.47 5.227 7.917-3.286-.672zM12 2.25V4.5m5.834.166l-1.591 1.591M20.25 10.5H18M7.757 14.743l-1.59 1.59M6 10.5H3.75m4.007-4.243l-1.59-1.59" />
            </svg>
            <span>{{ isDragOver ? 'Drop to edit' : 'Drag an image to Edit Image in the sidebar' }}</span>
          </div>
          <div class="flex items-center gap-3 justify-center">
            <svg class="w-4 h-4 text-content-muted" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
            </svg>
            <span>Or right-click any image and select "Edit Image"</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Editor Container - full height, no header -->
    <div v-show="mediaId || imageUrl" class="flex-1 min-h-0 relative">
      <div
        v-if="targetAssetId && (isEditingOlderVersion || newerVersionArrived)"
        class="absolute left-1/2 top-3 z-chrome flex max-w-[680px] -translate-x-1/2 items-center gap-3 rounded-lg border border-amber-500/40 bg-surface-raised px-4 py-2 text-xs text-amber-400 shadow-lg"
      >
        <span>
          {{ newerVersionArrived
            ? 'A newer version was saved elsewhere. Your work is safe; Save will create a new latest version from the version you opened.'
            : `You opened version ${baseVersionNumber}. Save will branch from it and make the result latest; newer versions remain in history.` }}
        </span>
      </div>
      <div v-show="loading" class="absolute inset-0 flex items-center justify-center z-chrome">
        <div class="text-content-tertiary">Loading editor...</div>
      </div>
      <div v-show="error" class="absolute inset-0 flex items-center justify-center z-chrome">
        <div class="text-center">
          <div class="text-red-400 mb-2">{{ error }}</div>
          <Button variant="secondary" @click="loadImage">
            Retry
          </Button>
        </div>
      </div>
      <StimmaEditor
        v-if="editorMounted"
        ref="editorRef"
        :src="imageUrl"
        :plugins="plugins"
        :storage-prefix="editorStoragePrefix"
        :theme="resolvedTheme"
        :show-close-button="false"
        :show-done-button="false"
        @update="handleUpdate"
        @load="handleEditorReady"
        @load-error="handleLoadError"
      >
        <!-- Custom toolbar controls via slot - Auto-markers + Save buttons -->
        <template #toolbar-end>
          <div class="flex items-center gap-1 ml-auto">
            <AutoMarkPicker
              :markers="availableMarkers"
              v-model="editorAutoMarkerIds"
            />
            <span v-if="hasChanges" class="px-2 text-xs text-content-muted">{{ draftStatus }}</span>
            <div class="stimma-toolbar__divider"></div>
            <!-- Save button - creates new edited version -->
            <Button :loading="saving" :disabled="!hasChanges" @click="handleSave()">
              Save
            </Button>
            <Button variant="secondary" :disabled="saving || !hasChanges" @click="handleSave(true)">
              Save as New Asset
            </Button>
          </div>
        </template>
      </StimmaEditor>
    </div>
  </div>
</template>

<script>
// Module-level singleton: shared auto-marker state across all editor instances
import { ref, watch } from 'vue'
import { makeProfileKey, makeGlobalKey } from '../utils/storageKeys'

// Migrate legacy unscoped key
const _legacyAutoMarkersKey = 'stimma-editor-auto-marker-ids'
const EDITOR_AUTO_MARKERS_KEY = makeProfileKey('editor_auto_marker_ids')
if (localStorage.getItem(_legacyAutoMarkersKey) !== null) {
  localStorage.setItem(EDITOR_AUTO_MARKERS_KEY, localStorage.getItem(_legacyAutoMarkersKey))
  localStorage.removeItem(_legacyAutoMarkersKey)
}
const editorAutoMarkerIds = ref(JSON.parse(localStorage.getItem(EDITOR_AUTO_MARKERS_KEY) || '[]'))
watch(editorAutoMarkerIds, (ids) => {
  localStorage.setItem(EDITOR_AUTO_MARKERS_KEY, JSON.stringify(ids))
})
</script>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, onActivated, onDeactivated, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  StimmaEditor,
  cropPlugin,
  retouchPlugin,
  finetunePlugin,
  filterPlugin,
  effectsPlugin,
  annotatePlugin,
} from '@stimma/image-editor'
import '@stimma/image-editor/style.css'
import {
  isEditorDebugEnabled,
  logEditorDebug,
  nextEditorDebugSession,
} from '../../../packages/image-editor/src/utils/editorDebug'
import { useMediaApi } from '../composables/useMediaApi'
import { useAssetApi } from '../composables/useAssetApi'
import { useMarkers } from '../composables/useMarkers'
import { loadProfiles } from '../composables/useProfile'
import { makeStorageKey, makeProfileKey } from '../utils/storageKeys'
import { useTheme } from '../composables/useTheme'
import AutoMarkPicker from '../components/generation/AutoMarkPicker.vue'
import Button from '../components/ui/Button.vue'
import axios from 'axios'
import { useTelemetry } from '../composables/useTelemetry'
import { addToast } from '../composables/useToasts'
import { useWebSocket } from '../composables/useWebSocket'

const { track: trackTelemetry } = useTelemetry()

// IndexedDB helpers for large project storage
const IDB_NAME = 'stimma-editor'
const IDB_STORE = 'projects'

async function openIDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(IDB_NAME, 1)
    request.onerror = () => reject(request.error)
    request.onsuccess = () => resolve(request.result)
    request.onupgradeneeded = (event) => {
      event.target.result.createObjectStore(IDB_STORE)
    }
  })
}

async function saveProjectToIDB(key, project) {
  try {
    const db = await openIDB()
    // Stringify to handle non-cloneable values (functions, etc.)
    const projectJson = JSON.stringify(project)
    return new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, 'readwrite')
      tx.objectStore(IDB_STORE).put(projectJson, key)
      tx.oncomplete = () => { db.close(); resolve() }
      tx.onerror = () => { db.close(); reject(tx.error) }
    })
  } catch (e) {
    console.warn('[ImageEditor] IndexedDB save failed:', e)
    throw e
  }
}

async function loadProjectFromIDB(key) {
  try {
    const db = await openIDB()
    return new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, 'readonly')
      const request = tx.objectStore(IDB_STORE).get(key)
      request.onsuccess = () => {
        db.close()
        const result = request.result
        if (result && typeof result === 'string') {
          try {
            resolve(JSON.parse(result))
          } catch (e) {
            console.warn('[ImageEditor] Failed to parse stored project:', e)
            resolve(null)
          }
        } else {
          resolve(result) // null or already an object (legacy)
        }
      }
      request.onerror = () => { db.close(); reject(request.error) }
    })
  } catch (e) {
    console.warn('[ImageEditor] IndexedDB load failed:', e)
    return null
  }
}

async function deleteProjectFromIDB(key) {
  try {
    const db = await openIDB()
    return new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, 'readwrite')
      tx.objectStore(IDB_STORE).delete(key)
      tx.oncomplete = () => { db.close(); resolve() }
      tx.onerror = () => { db.close(); reject(tx.error) }
    })
  } catch (e) {
    console.warn('[ImageEditor] IndexedDB delete failed:', e)
  }
}

// Clear all projects from IndexedDB (for debugging/migration)
async function clearAllProjectsFromIDB() {
  try {
    const db = await openIDB()
    return new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, 'readwrite')
      tx.objectStore(IDB_STORE).clear()
      tx.oncomplete = () => { db.close(); console.log('[ImageEditor] Cleared all projects from IndexedDB'); resolve() }
      tx.onerror = () => { db.close(); reject(tx.error) }
    })
  } catch (e) {
    console.warn('[ImageEditor] IndexedDB clear failed:', e)
  }
}

// One-time migration: clear old projects that don't have mediaId tags
const IDB_MIGRATED_KEY = makeGlobalKey('editor_migrated_v1')
async function migrateIDBIfNeeded() {
  if (localStorage.getItem(IDB_MIGRATED_KEY)) return

  console.log('[ImageEditor] Running one-time IndexedDB migration...')
  await clearAllProjectsFromIDB()
  localStorage.setItem(IDB_MIGRATED_KEY, 'true')
}

const route = useRoute()
const router = useRouter()
const { getMediaItem, getMediaFileUrl, addMarkerToMedia } = useMediaApi()
const { addMarker: addMarkerToAsset, getAsset, getRevisions } = useAssetApi()
const { on: onWebSocketEvent } = useWebSocket()
const { resolvedTheme } = useTheme()
const { availableMarkers, init: initMarkers } = useMarkers()

// Props
const props = defineProps({
  editorId: {
    type: [String, null],
    default: null
  },
  mediaId: {
    type: [String, Number, null],
    default: null
  }
})

// State
const loading = ref(true)
const error = ref(null)
const saving = ref(false)
const editorRef = ref(null)
const imageUrl = ref(null)
const sourceItem = ref(null)
const savedProject = ref(null)
const hasChanges = ref(false)
const editorReady = ref(false)
const actualSourceMediaId = ref(null)  // The original source image ID (for re-editing saved edits)
const targetAssetId = ref(null)
const baseRevisionId = ref(null)
const latestRevisionId = ref(null)
const headRevisionAtOpen = ref(null)
const baseVersionNumber = ref(null)
const newerVersionArrived = ref(false)
const draftStatus = ref('Draft saved locally')
const projectFromLocalStorage = ref(false)  // Track if project came from localStorage (unsaved local edits)
const editorMounted = ref(false)  // When to mount the StimmaEditor
const restoringProject = ref(false)
const isDragOver = ref(false)
let dragCounter = 0
const debugEnabled = isEditorDebugEnabled()
let activeRestoreSession = null
let autosaveSessionCounter = 0

function debugLog(event, details = {}) {
  if (!debugEnabled) return
  logEditorDebug('ImageEditorView', event, {
    mediaId: mediaIdNum.value,
    restoreSession: activeRestoreSession,
    ...details,
  })
}

// Plugins (already instantiated objects from the library)
const plugins = [
  cropPlugin,
  retouchPlugin,
  finetunePlugin,
  filterPlugin,
  effectsPlugin,
  annotatePlugin,
]

// Auto-save debounce
let saveDebounceTimer = null
const SAVE_DEBOUNCE_MS = 500

// Computed
const mediaIdNum = computed(() => props.mediaId ? parseInt(props.mediaId, 10) : null)
const isEditingOlderVersion = computed(() => (
  !!baseRevisionId.value
  && !!headRevisionAtOpen.value
  && baseRevisionId.value !== headRevisionAtOpen.value
))

async function refreshAssetVersionState({ initial = false } = {}) {
  if (!targetAssetId.value) return
  try {
    const [assetResult, revisionResult] = await Promise.all([
      getAsset(targetAssetId.value),
      getRevisions(targetAssetId.value),
    ])
    latestRevisionId.value = assetResult.asset.current_revision_id
    if (initial) headRevisionAtOpen.value = latestRevisionId.value
    const base = (revisionResult.items || []).find(item => item.id === baseRevisionId.value)
    baseVersionNumber.value = base?.revision_number || null
  } catch (error) {
    console.error('Failed to load editor version state:', error)
  }
}

// Storage prefix for editor settings (follows Stimma conventions: stimma_{modifier}_{accountId}_{profileId}_)
const editorStoragePrefix = computed(() => {
  return makeProfileKey('image-editor') + '-'
})

// Storage keys
function getProjectStorageKey() {
  return makeStorageKey('image-editor', 'project', mediaIdNum.value)
}

function getSettingsStorageKey() {
  return makeProfileKey('image-editor', 'settings')
}

function getLastEditedKey() {
  return makeProfileKey('image-editor', 'last-edited')
}

// Save current mediaId as last edited
function saveLastEdited(mediaId) {
  if (mediaId) {
    localStorage.setItem(getLastEditedKey(), mediaId.toString())
  }
}

// Get last edited mediaId
function getLastEdited() {
  const saved = localStorage.getItem(getLastEditedKey())
  return saved ? parseInt(saved, 10) : null
}

// Load source image
async function loadImage() {
  loading.value = true
  error.value = null
  trackTelemetry('image_editor_opened')
  debugLog('load-image:start', {
    routeMediaId: props.mediaId ?? null,
  })

  try {
    // Ensure profiles are loaded before getting media URL (for db_guid)
    // This is critical - without db_guid, the URL will be wrong
    await loadProfiles()

    const item = await getMediaItem(mediaIdNum.value)
    debugLog('load-image:media-item', {
      itemId: item?.id ?? null,
      hasWorkingDocument: item?.has_working_document ?? false,
      isVideo: item?.is_video ?? false,
    })
    if (!item) {
      throw new Error('Media item not found')
    }

    if (item.is_video) {
      throw new Error('Cannot edit video files')
    }

    sourceItem.value = item
    targetAssetId.value = item.asset_id || null
    baseRevisionId.value = item.revision_id || null
    if (targetAssetId.value) {
      // Opening an Asset in a mutable editor is first use, even if the user
      // ultimately closes without saving.
      await axios.delete(`/api/assets/item/${targetAssetId.value}/expiration`)
    }
    await refreshAssetVersionState({ initial: true })

    // Determine which image to load as the source
    let imageToLoadId = mediaIdNum.value
    actualSourceMediaId.value = mediaIdNum.value  // Default: we're editing this image directly

    // WorkingDocument is Asset state and does not set the legacy Media sidecar
    // flag. Always ask the server; a 404 simply means this Asset has no saved
    // non-destructive editor state.
    try {
      const response = await axios.get(`/api/media/${mediaIdNum.value}/editor-project`)
      savedProject.value = response.data.project
      hasChanges.value = false  // No unsaved changes yet when loading from server
      projectFromLocalStorage.value = false
      console.log('[ImageEditor] Restored project from server sidecar')
      debugLog('load-image:server-project', {
        sourceMediaId: response.data.source_media_id ?? null,
        hasProject: !!response.data.project,
        projectHasRetouch: !!response.data.project?.state?.retouchLayerData,
      })

      // If sidecar has source_media_id, load the original rather than the rasterized revision.
      if (response.data.source_media_id) {
        imageToLoadId = response.data.source_media_id
        actualSourceMediaId.value = response.data.source_media_id
        console.log('[ImageEditor] Will load original source image:', imageToLoadId)
      }
    } catch (e) {
      if (e?.response?.status !== 404) {
        console.warn('Failed to fetch editor project from server:', e)
      }
    }

    // Fall back to IndexedDB for in-progress edits (not yet saved)
    if (!savedProject.value) {
      const storageKey = getProjectStorageKey()

      // Try IndexedDB first (preferred storage)
      let project = await loadProjectFromIDB(storageKey)

      // Fall back to localStorage and migrate if found
      if (!project) {
        const savedProjectJson = localStorage.getItem(storageKey)
        if (savedProjectJson) {
          try {
            project = JSON.parse(savedProjectJson)
            // Migrate to IndexedDB
            await saveProjectToIDB(storageKey, project)
            localStorage.removeItem(storageKey)
            console.log('[ImageEditor] Migrated project from localStorage to IndexedDB')
          } catch (e) {
            console.warn('Failed to parse/migrate saved project:', e)
            localStorage.removeItem(storageKey)
          }
        }
      }

      // Validate the project has imageDataUrl (required for loadProject)
      if (project) {
        const hasValidImage = project.imageDataUrl?.startsWith('data:image/')
        const mediaIdMatches = !project._stimmaMediaId || project._stimmaMediaId === mediaIdNum.value

        if (hasValidImage && mediaIdMatches) {
          savedProject.value = project
          hasChanges.value = true // Restored project means there are unsaved changes
          projectFromLocalStorage.value = true
          console.log('[ImageEditor] Restored project from IndexedDB, key:', storageKey, 'mediaId:', project._stimmaMediaId)
          debugLog('load-image:idb-project', {
            storageKey,
            projectMediaId: project._stimmaMediaId ?? null,
            hasRetouch: !!project.state?.retouchLayerData,
          })
        } else if (!hasValidImage) {
          console.warn('[ImageEditor] Invalid project (missing imageDataUrl), discarding. Key:', storageKey)
          await deleteProjectFromIDB(storageKey)
        } else {
          console.warn('[ImageEditor] Project mediaId mismatch! Expected:', mediaIdNum.value, 'Got:', project._stimmaMediaId, '- discarding')
          await deleteProjectFromIDB(storageKey)
        }
      } else {
        console.log('[ImageEditor] No saved project found in IndexedDB for key:', storageKey)
      }
    }

    // Build the image URL - use the determined image ID (original or current)
    const url = getMediaFileUrl(imageToLoadId)
    if (!url) {
      throw new Error('Could not construct image URL')
    }
    console.log('[ImageEditor] Loading image URL:', url, 'for media ID:', imageToLoadId)
    console.log('[ImageEditor] Has savedProject:', !!savedProject.value)
    debugLog('load-image:resolved-source', {
      imageToLoadId,
      actualSourceMediaId: actualSourceMediaId.value,
      hasSavedProject: !!savedProject.value,
      projectFromLocalStorage: projectFromLocalStorage.value,
    })

    imageUrl.value = url

    // Mount the editor - it will load the image via :src
    // handleEditorReady will then apply any saved editing state
    editorMounted.value = true
  } catch (e) {
    console.error('Failed to load image:', e)
    debugLog('load-image:error', {
      error: e?.message || String(e),
    })
    error.value = e.message || 'Failed to load image'
  } finally {
    loading.value = false
    debugLog('load-image:end', {
      hasError: !!error.value,
    })
  }
}

// Note: IndexedDB is async, so we can't do synchronous saves in beforeunload.
// The debounced auto-save ensures data is persisted frequently during editing.

// Force immediate save of project state to IndexedDB
async function saveProjectNow() {
  if (!editorRef.value || !mediaIdNum.value) return

  // Cancel any pending debounced save
  if (saveDebounceTimer) {
    clearTimeout(saveDebounceTimer)
    saveDebounceTimer = null
  }

  try {
    const project = await editorRef.value.serialize({
      includeHistory: false
    })

    // Validate the project has imageDataUrl
    if (!project.imageDataUrl) {
      console.error('[ImageEditor] serialize() did not include imageDataUrl')
      return
    }

    // Save to IndexedDB
    const storageKey = getProjectStorageKey()
    await saveProjectToIDB(storageKey, project)
    // Also keep it in memory for faster restore
    savedProject.value = project
    projectFromLocalStorage.value = true
    console.log('[ImageEditor] Saved project to IndexedDB')
  } catch (e) {
    console.warn('Failed to save project state:', e)
  }
}


// Handle editor updates (auto-save project state)
function handleUpdate() {
  if (restoringProject.value) {
    debugLog('autosave:suppressed-during-restore')
    return
  }

  hasChanges.value = true
  draftStatus.value = 'Saving draft…'

  // Capture the current mediaId NOW, not when debounce fires
  const currentMediaId = mediaIdNum.value
  const currentStorageKey = getProjectStorageKey()

  // Debounce serialize + save (serialize is async and can be slow)
  if (saveDebounceTimer) {
    clearTimeout(saveDebounceTimer)
  }

  saveDebounceTimer = setTimeout(async () => {
    const autosaveSession = ++autosaveSessionCounter
    debugLog('autosave:start', {
      autosaveSession,
      currentMediaId,
      storageKey: currentStorageKey,
    })

    // Verify we're still editing the same image
    if (!editorRef.value || !currentMediaId || mediaIdNum.value !== currentMediaId) {
      console.log('[ImageEditor] Skipping save - mediaId changed')
      debugLog('autosave:skip-media-changed', {
        autosaveSession,
        currentMediaId,
        latestMediaId: mediaIdNum.value,
      })
      return
    }

    try {
      // Use serialize() to get a complete project that loadProject() can restore
      const project = await editorRef.value.serialize({
        includeHistory: false
      })

      // Validate the project has imageDataUrl
      if (!project.imageDataUrl) {
        console.error('[ImageEditor] serialize() did not include imageDataUrl')
        debugLog('autosave:missing-image-data', { autosaveSession })
        return
      }

      // Double-check we're still on the same image after async serialize
      if (mediaIdNum.value !== currentMediaId) {
        console.log('[ImageEditor] Skipping save - mediaId changed during serialize')
        debugLog('autosave:skip-media-changed-after-serialize', {
          autosaveSession,
          currentMediaId,
          latestMediaId: mediaIdNum.value,
        })
        return
      }

      // Tag the project with the mediaId for verification on load
      project._stimmaMediaId = currentMediaId

      // Save to IndexedDB (handles large data better than localStorage)
      await saveProjectToIDB(currentStorageKey, project)
      savedProject.value = project
      projectFromLocalStorage.value = true
      draftStatus.value = 'Draft saved locally'
      console.log('[ImageEditor] Saved project to IndexedDB for mediaId:', currentMediaId)
      debugLog('autosave:done', {
        autosaveSession,
        hasRetouch: !!project.state?.retouchLayerData,
      })
    } catch (e) {
      draftStatus.value = 'Draft save failed'
      console.warn('[ImageEditor] Failed to serialize/save project:', e)
      debugLog('autosave:error', {
        autosaveSession,
        error: e?.message || String(e),
      })
    }
  }, 300) // Short debounce
}

// Handle editor ready - fires after image loads via :src
async function handleEditorReady() {
  editorReady.value = true
  console.log('[ImageEditor] Editor loaded image via :src')
  debugLog('editor-ready:start', {
    hasSavedProject: !!savedProject.value,
  })

  // Check if we have a saved project to restore
  let projectToRestore = savedProject.value

  // Also check IndexedDB directly as fallback
  if (!projectToRestore && mediaIdNum.value) {
    const storageKey = getProjectStorageKey()
    projectToRestore = await loadProjectFromIDB(storageKey)

    // Fall back to localStorage for legacy projects
    if (!projectToRestore) {
      const savedProjectJson = localStorage.getItem(storageKey)
      if (savedProjectJson) {
        try {
          projectToRestore = JSON.parse(savedProjectJson)
          // Migrate to IndexedDB
          if (projectToRestore.imageDataUrl?.startsWith('data:image/')) {
            await saveProjectToIDB(storageKey, projectToRestore)
            localStorage.removeItem(storageKey)
            console.log('[ImageEditor] Migrated project to IndexedDB')
          }
        } catch (e) {
          console.warn('[ImageEditor] Failed to parse localStorage project:', e)
          localStorage.removeItem(storageKey)
        }
      }
    }

    if (projectToRestore) {
      projectFromLocalStorage.value = true
      console.log('[ImageEditor] Found project in storage')
      debugLog('editor-ready:found-storage-project', {
        hasRetouch: !!projectToRestore.state?.retouchLayerData,
      })
    }
  }

  if (projectToRestore && editorRef.value) {
    try {
      activeRestoreSession = nextEditorDebugSession('view-restore')
      restoringProject.value = true
      debugLog('restore:start', {
        source: projectFromLocalStorage.value ? 'local' : 'server',
        hasRetouch: !!projectToRestore.state?.retouchLayerData,
        sourceMediaId: actualSourceMediaId.value,
      })
      if (projectToRestore.imageDataUrl?.startsWith('data:image/')) {
        console.log('[ImageEditor] Restoring saved project via loadProject()')
        await editorRef.value.loadProject(projectToRestore)
        hasChanges.value = projectFromLocalStorage.value
        console.log('[ImageEditor] Project restored successfully')
        debugLog('restore:load-project-done', {
          hasChanges: hasChanges.value,
        })
      } else if (projectToRestore.state) {
        console.log('[ImageEditor] Restoring legacy saved state')
        editorRef.value.setState(projectToRestore.state)
        hasChanges.value = projectFromLocalStorage.value
        console.log('[ImageEditor] Legacy state restored successfully')
        debugLog('restore:legacy-state-done', {
          hasChanges: hasChanges.value,
        })
      } else {
        throw new Error('Saved project is missing both imageDataUrl and state')
      }
    } catch (e) {
      console.warn('[ImageEditor] Failed to restore editing state:', e.message)
      debugLog('restore:error', {
        error: e?.message || String(e),
      })
      // Clear corrupted project from both storages
      const storageKey = getProjectStorageKey()
      await deleteProjectFromIDB(storageKey)
      localStorage.removeItem(storageKey)
      savedProject.value = null
    } finally {
      restoringProject.value = false
      debugLog('restore:end', {
        hasError: !!error.value,
      })
      activeRestoreSession = null
    }
  }

  debugLog('editor-ready:end', {
    restored: !!projectToRestore,
  })
}

// Handle load error
function handleLoadError(err) {
  console.error('[ImageEditor] Failed to load image in editor:', err)
  console.error('[ImageEditor] Image URL was:', imageUrl.value)
  error.value = `Failed to load image in editor: ${err?.message || 'Unknown error'}`
}

// Landing page drag-drop handlers
function handleLandingDragOver(e) {
  if (e.dataTransfer?.types.includes('application/x-media-id')) {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }
}

function handleLandingDragEnter(e) {
  if (e.dataTransfer?.types.includes('application/x-media-id')) {
    e.preventDefault()
    dragCounter++
    isDragOver.value = true
  }
}

function handleLandingDragLeave(e) {
  dragCounter--
  if (dragCounter <= 0) {
    isDragOver.value = false
    dragCounter = 0
  }
}

function handleLandingDrop(e) {
  e.preventDefault()
  isDragOver.value = false
  dragCounter = 0

  const mediaIdStr = e.dataTransfer?.getData('application/x-media-id')
  if (mediaIdStr) {
    const mediaId = parseInt(mediaIdStr, 10)
    router.push({ name: 'edit-image', params: { editorId: props.editorId, mediaId } })
  }
}

// Save edited image
async function handleSave(saveAsNew = false) {
  if (!editorRef.value || saving.value) return

  saving.value = true

  try {
    // Get rasterized image from editor
    const result = await editorRef.value.rasterize()
    const blob = result.dest  // rasterize returns { dest: Blob, ... }

    // Try to serialize project state (compact, no history) for non-destructive editing
    let project = null
    try {
      project = await editorRef.value.serialize({
        includeHistory: false
      })
    } catch (serializeErr) {
      console.warn('[ImageEditor] Failed to serialize project (non-destructive editing disabled):', serializeErr)
      // Continue without project - user will get rasterized image only
    }

    // Create form data
    // Use actualSourceMediaId for lineage - this is the original image being edited
    const sourceId = actualSourceMediaId.value || mediaIdNum.value
    const formData = new FormData()
    formData.append('file', blob, `edited_${sourceId}.png`)
    formData.append('source_media_id', sourceId.toString())
    if (targetAssetId.value) {
      formData.append('asset_id', targetAssetId.value.toString())
    }
    if (baseRevisionId.value) {
      formData.append('base_revision_id', baseRevisionId.value.toString())
    }
    formData.append('save_as_new', saveAsNew ? 'true' : 'false')
    if (project) {
      formData.append('editor_project', JSON.stringify(project))
    }

    // Upload to backend
    console.log('[ImageEditor] Saving with source_media_id:', sourceId, 'editor_project length:', JSON.stringify(project).length)
    const response = await axios.post('/api/media/save-edit', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    })
    console.log('[ImageEditor] Save response:', response.data)

    // Clear saved project state from both storages
    const storageKey = getProjectStorageKey()
    await deleteProjectFromIDB(storageKey)
    localStorage.removeItem(storageKey)
    hasChanges.value = false

    const newMediaId = response.data.media_id
    const savedAssetId = response.data.asset_id
    console.log('[ImageEditor] Navigating to new media:', newMediaId)

    // Adopt our own new revision so the asset_current_revision_changed
    // broadcast from this save isn't misread as an external save.
    if (savedAssetId && Number(savedAssetId) === Number(targetAssetId.value)) {
      const savedRevisionId = response.data.revision_id
      baseRevisionId.value = savedRevisionId
      latestRevisionId.value = savedRevisionId
      headRevisionAtOpen.value = savedRevisionId
    }
    newerVersionArrived.value = false

    // Apply auto-markers to the new media item
    if (editorAutoMarkerIds.value.length > 0) {
      try {
        await Promise.all(
          editorAutoMarkerIds.value.map(markerId => (
            savedAssetId
              ? addMarkerToAsset(savedAssetId, markerId)
              : addMarkerToMedia(newMediaId, markerId)
          ))
        )
        console.log('[ImageEditor] Applied auto-markers:', editorAutoMarkerIds.value)
      } catch (markerErr) {
        console.error('[ImageEditor] Failed to apply auto-markers:', markerErr)
      }
    }

    // Navigate to the new media item in browse view, opening slideshow directly
    router.push({
      name: 'browse',
      query: { slideshowAsset: savedAssetId }
    })
  } catch (e) {
    console.error('Failed to save edited image:', e)
    const message = e.response?.data?.detail || e.message || 'Failed to save'
    addToast(`Failed to save: ${message}`, 'error', 8000)
  } finally {
    saving.value = false
  }
}

// Handle beforeunload - warn about unsaved changes
// Note: We can't save to IndexedDB here since it's async.
// The debounced auto-save (300ms) ensures data is persisted during editing.
function handleBeforeUnload(e) {
  if (hasChanges.value) {
    e.preventDefault()
    e.returnValue = ''
  }
}

// Lifecycle
onMounted(async () => {
  // Initialize markers system for auto-marking
  initMarkers()

  // Clear stale projects from before mediaId tagging was added
  await migrateIDBIfNeeded()

  if (props.mediaId) {
    // Save as last edited and load
    saveLastEdited(props.mediaId)
    loadImage()
  } else if (props.editorId) {
    // No mediaId provided - check if we have a last edited to restore
    const lastEdited = getLastEdited()
    if (lastEdited) {
      // Redirect to the last edited image, keeping this editor instance
      router.replace({ name: 'edit-image', params: { editorId: props.editorId, mediaId: lastEdited } })
    }
  }
  window.addEventListener('beforeunload', handleBeforeUnload)
})

const unsubscribeAssetVersions = onWebSocketEvent('asset_current_revision_changed', (data) => {
  if (!targetAssetId.value || Number(data?.asset_id) !== Number(targetAssetId.value)) return
  const incomingRevisionId = data?.revision_id || data?.asset?.revision_id
  if (incomingRevisionId && incomingRevisionId !== latestRevisionId.value) {
    latestRevisionId.value = incomingRevisionId
    newerVersionArrived.value = true
  }
})

onBeforeUnmount(() => {
  if (saveDebounceTimer) {
    clearTimeout(saveDebounceTimer)
  }
  window.removeEventListener('beforeunload', handleBeforeUnload)
  unsubscribeAssetVersions()
})

// Save state when deactivated (navigating away with KeepAlive)
onDeactivated(() => {
  // Force immediate save so state persists
  saveProjectNow()
})

// Handle re-activation from KeepAlive
onActivated(() => {
  console.log('[ImageEditor] onActivated, props.mediaId:', props.mediaId, 'current sourceItem:', sourceItem.value?.id)

  // If no mediaId in route but we have a last edited, redirect to it
  if (!props.mediaId && props.editorId) {
    const lastEdited = getLastEdited()
    if (lastEdited) {
      router.replace({ name: 'edit-image', params: { editorId: props.editorId, mediaId: lastEdited } })
    }
    return
  }

  // If we're activated with a different mediaId than what's loaded, reload
  const newIdNum = parseInt(props.mediaId, 10)
  if (sourceItem.value && sourceItem.value.id !== newIdNum) {
    console.log('[ImageEditor] onActivated: mediaId changed, reloading. Was:', sourceItem.value.id, 'Now:', newIdNum)
    // Reset state and reload
    if (saveDebounceTimer) {
      clearTimeout(saveDebounceTimer)
      saveDebounceTimer = null
    }
    savedProject.value = null
    hasChanges.value = false
    editorReady.value = false
    actualSourceMediaId.value = null
    projectFromLocalStorage.value = false
    imageUrl.value = null
    editorMounted.value = false
    saveLastEdited(props.mediaId)
    nextTick(() => {
      loadImage()
    })
  }
})

// Watch for mediaId changes (if navigating between edits)
watch(() => props.mediaId, (newId, oldId) => {
  // If changing to null, check for last edited and redirect
  if (!newId) {
    if (props.editorId) {
      const lastEdited = getLastEdited()
      if (lastEdited) {
        router.replace({ name: 'edit-image', params: { editorId: props.editorId, mediaId: lastEdited } })
        return  // Don't clear state, we're redirecting
      }
    }
    return
  }

  const newIdNum = parseInt(newId, 10)
  const oldIdNum = oldId ? parseInt(oldId, 10) : null

  // Only clear and reload if actually changing to a different image
  if (newIdNum !== oldIdNum) {
    console.log('[ImageEditor] mediaId changed from', oldIdNum, 'to', newIdNum)
    // Cancel any pending save from the old image
    if (saveDebounceTimer) {
      clearTimeout(saveDebounceTimer)
      saveDebounceTimer = null
    }
    savedProject.value = null
    hasChanges.value = false
    editorReady.value = false
    actualSourceMediaId.value = null
    projectFromLocalStorage.value = false
    imageUrl.value = null
    editorMounted.value = false  // Force editor to unmount so it remounts fresh
    saveLastEdited(newId)
    // Wait for Vue to unmount the editor before loading the new image
    nextTick(() => {
      loadImage()
    })
  }
})
</script>
