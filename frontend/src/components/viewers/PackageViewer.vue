<template>
  <div class="relative flex h-full w-full overflow-hidden bg-matte">
    <!-- The cover. A real URL, not srcdoc: relative links to sibling files
         inside the bundle (previews, run zips, extras) only resolve when the
         frame has the package-file route as its base. -->
    <div class="relative min-w-0 flex-1">
      <iframe
        v-if="coverUrl"
        :key="`${currentMediaId}-${reloadKey}`"
        :src="coverUrl"
        sandbox="allow-scripts allow-same-origin allow-downloads allow-popups"
        class="h-full w-full border-0 bg-matte"
        title="Package cover"
      />

      <!-- Show the panel again. Black-glass chip, the hero-overlay grammar. -->
      <button
        v-if="!panelOpen"
        type="button"
        class="absolute right-3 top-3 z-chrome inline-flex items-center gap-1.5 rounded-md bg-black/55 px-2.5 py-1.5 text-[11px] font-medium text-white/85 backdrop-blur transition-colors duration-150 hover:text-white coarse:min-h-11 coarse:min-w-11 coarse:justify-center focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
        @click="panelOpen = true"
      >
        <ArchiveBoxIcon class="h-4 w-4 flex-shrink-0" />
        <span>Details</span>
      </button>
    </div>

    <!-- Wide: a hairline-separated side panel. Compact: the same body in the
         kit Sheet (DESIGN §1.11 — one sheet, one dismissal). -->
    <component
      :is="isCompact ? Sheet : 'aside'"
      v-if="panelOpen || isCompact"
      v-bind="panelShell"
      @close="panelOpen = false"
    >
      <div :class="isCompact ? 'px-4 pb-4' : 'px-3 pb-4'">
        <!-- Header: title plus the icon rail, SlideshowInfoPanel grammar. -->
        <div class="flex items-center gap-0.5 pt-3">
          <h2 class="min-w-0 flex-1 truncate text-sm font-medium text-content" :title="title">{{ title }}</h2>
          <Tooltip text="Rebuild">
            <IconButton :disabled="rebuilding || !assetId" @click="rebuild">
              <Spinner v-if="rebuilding" size="sm" />
              <ArrowPathIcon v-else class="h-4 w-4" />
            </IconButton>
          </Tooltip>
          <Tooltip text="Export">
            <IconButton @click.stop="openExportMenu">
              <ArrowDownTrayIcon class="h-4 w-4" />
            </IconButton>
          </Tooltip>
          <Tooltip v-if="!isCompact" text="Hide details">
            <IconButton @click="panelOpen = false">
              <XMarkIcon class="h-4 w-4" />
            </IconButton>
          </Tooltip>
        </div>

        <!-- Stale: warning family (DESIGN §1.9), never a job status color. -->
        <p v-if="staleCount > 0" class="mt-2 flex items-center gap-1.5 text-xs text-amber-400">
          <ExclamationTriangleIcon class="h-3.5 w-3.5 flex-shrink-0" />
          <span>{{ staleCount }} {{ staleCount === 1 ? 'member has' : 'members have' }} a newer version</span>
        </p>

        <p v-if="loadError" class="mt-2 text-xs text-red-400">{{ loadError }}</p>

        <div v-if="loading" class="mt-4 flex items-center gap-2 text-xs text-content-tertiary">
          <Spinner size="sm" />
          <span>Loading package…</span>
        </div>

        <template v-else>
          <!-- Members -->
          <section v-if="members.length" class="mt-5">
            <h3 class="text-xs font-semibold text-content-secondary">Members</h3>
            <ul class="mt-2 space-y-1.5">
              <li
                v-for="member in members"
                :key="member.id"
                class="flex items-center gap-2.5"
              >
                <MediaImage
                  v-if="member.media_id"
                  :media-id="member.media_id"
                  :thumbnail-size="128"
                  :draggable="false"
                  container-class="h-9 w-9 flex-shrink-0 rounded-media overflow-hidden bg-matte"
                  img-class="h-full w-full object-cover"
                />
                <div v-else class="h-9 w-9 flex-shrink-0 rounded-media bg-overlay-faint" />
                <div class="min-w-0 flex-1">
                  <div class="truncate text-xs text-content" :title="member.name || ''">{{ member.name || 'Untitled' }}</div>
                  <div class="mt-0.5 flex items-center gap-1.5">
                    <span v-if="member.role" class="font-mono text-[10px] text-content-tertiary">{{ member.role }}</span>
                    <span v-if="member.unavailable" class="text-[10px] text-red-400">missing</span>
                    <span v-else-if="member.stale" class="text-[10px] text-amber-400">updated</span>
                  </div>
                </div>
              </li>
            </ul>
          </section>

          <!-- Runs -->
          <section v-if="runs.length" class="mt-5">
            <h3 class="text-xs font-semibold text-content-secondary">Runs</h3>
            <ul class="mt-2 space-y-1.5">
              <li v-for="run in runs" :key="run.id" class="flex items-center gap-2">
                <div class="min-w-0 flex-1">
                  <div class="truncate text-xs text-content">{{ run.recipe?.display_name || run.recipe?.id || run.root }}</div>
                  <div class="mt-0.5 font-mono text-[10px] tabular-nums text-content-tertiary">
                    {{ run.file_count }} {{ run.file_count === 1 ? 'file' : 'files' }}
                  </div>
                </div>
                <button
                  v-if="run.root"
                  type="button"
                  class="flex-shrink-0 rounded-md px-2 py-1 text-[11px] text-content-secondary transition-colors duration-150 hover:bg-overlay-subtle hover:text-content disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
                  :disabled="downloading === run.root"
                  @click="downloadRunZip(run)"
                >
                  {{ downloading === run.root ? 'Downloading…' : 'Download zip' }}
                </button>
              </li>
            </ul>
          </section>

          <!-- Extras -->
          <section v-if="extras.length" class="mt-5">
            <h3 class="text-xs font-semibold text-content-secondary">Extras</h3>
            <ul class="mt-2 space-y-1.5">
              <li v-for="extra in extras" :key="extra.path" class="flex items-center gap-2">
                <div class="min-w-0 flex-1">
                  <div class="truncate text-xs text-content" :title="extra.name || extra.path">{{ extra.name || extra.path }}</div>
                  <div v-if="extra.size" class="mt-0.5 font-mono text-[10px] tabular-nums text-content-tertiary">{{ formatBytes(extra.size) }}</div>
                </div>
                <Tooltip text="Download">
                  <IconButton :disabled="downloading === extra.path" @click="downloadExtra(extra)">
                    <ArrowDownTrayIcon class="h-4 w-4" />
                  </IconButton>
                </Tooltip>
              </li>
            </ul>
          </section>
        </template>
      </div>
    </component>

    <ActionMenu
      v-if="exportMenu"
      :x="exportMenu.x"
      :y="exportMenu.y"
      :actions="exportActions"
      @close="exportMenu = null"
    />
  </div>
</template>

<script setup>
// The package viewer: the cover as a live page, with the bundle's contents and
// the two things you can do to it (rebuild, export) in a side panel.
import { computed, ref, watch } from 'vue'
import axios from 'axios'
import {
  ArchiveBoxIcon,
  ArrowDownTrayIcon,
  ArrowPathIcon,
  ExclamationTriangleIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import ActionMenu from '../ActionMenu.vue'
import IconButton from '../ui/IconButton.vue'
import Sheet from '../ui/Sheet.vue'
import Spinner from '../ui/Spinner.vue'
import Tooltip from '../ui/Tooltip.vue'
import { MediaImage } from '../media'
import { getApiBase } from '../../apiConfig'
import { getCurrentDbGuid, getCurrentProfileId } from '../../composables/useProfile'
import { useAssetApi } from '../../composables/useAssetApi'
import { useTauriDownload } from '../../composables/useTauriDownload'
import { useToasts } from '../../composables/useToasts'
import { useViewport } from '../../composables/useViewport'

const props = defineProps({
  mediaId: {
    type: Number,
    required: true,
  },
})

const emit = defineEmits(['refresh'])

const { isCompact } = useViewport()
const { downloadFromResponse } = useTauriDownload()
const { addToast } = useToasts()
const { getAssetBrowserItem } = useAssetApi()

// A rebuild produces a NEW media id for the same asset, so the viewer tracks
// which payload it is showing rather than trusting the prop it was mounted with.
const currentMediaId = ref(props.mediaId)
const reloadKey = ref(0)
const loading = ref(true)
const loadError = ref('')
const manifest = ref(null)
const status = ref(null)
const rebuilding = ref(false)
const downloading = ref('')
const exportMenu = ref(null)
// Compact opens the sheet on demand; a wide window shows the panel by default.
const panelOpen = ref(!isCompact.value)

const panelShell = computed(() => (
  isCompact.value
    ? { show: panelOpen.value, title: '' }
    : { class: 'flex w-[320px] max-w-[85%] flex-none flex-col overflow-y-auto border-l border-edge-subtle bg-surface custom-scrollbar' }
))

const title = computed(() => status.value?.title || manifest.value?.title || 'Package')
const members = computed(() => status.value?.members || [])
const runs = computed(() => status.value?.runs || [])
const extras = computed(() => manifest.value?.extras || [])
const assetId = computed(() => status.value?.asset_id || null)
const staleCount = computed(() => members.value.filter(m => m.stale).length)

function packageFileUrl(path) {
  const dbGuid = getCurrentDbGuid()
  if (dbGuid) {
    return `${getApiBase()}/db/${dbGuid}/media/${currentMediaId.value}/package-file/${path}`
  }
  return `${getApiBase()}/media/${currentMediaId.value}/package-file/${path}?profile=${encodeURIComponent(getCurrentProfileId())}`
}

const coverUrl = computed(() => currentMediaId.value ? packageFileUrl('index.html') : '')

function formatBytes(bytes) {
  if (!bytes) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value >= 10 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`
}

function errorDetail(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback
}

async function loadPackage() {
  loading.value = true
  loadError.value = ''
  try {
    const { data } = await axios.get(`${getApiBase()}/media/${currentMediaId.value}/package`)
    manifest.value = data.manifest
    status.value = data.status
  } catch (error) {
    loadError.value = errorDetail(error, 'Could not read this package.')
  } finally {
    loading.value = false
  }
}

watch(() => props.mediaId, (id) => {
  if (!id || id === currentMediaId.value) return
  currentMediaId.value = id
})

watch(currentMediaId, () => { void loadPackage() }, { immediate: true })

// --- Rebuild ---------------------------------------------------------------

async function rebuild() {
  if (rebuilding.value || !assetId.value) return
  rebuilding.value = true
  try {
    const { data } = await axios.post(`${getApiBase()}/assets/${assetId.value}/package/rebuild`, {})
    let revisionLabel = data?.revision_number ? ` ${data.revision_number}` : ''
    if (!revisionLabel) {
      try {
        const item = await getAssetBrowserItem(assetId.value)
        if (item?.revision_number) revisionLabel = ` ${item.revision_number}`
      } catch {
        // The rebuild succeeded; the revision number is decoration.
      }
    }
    addToast(`Rebuilt as revision${revisionLabel}`, 'success')
    if (data?.media_id) currentMediaId.value = data.media_id
    reloadKey.value += 1
    emit('refresh')
  } catch (error) {
    addToast(errorDetail(error, 'Rebuild failed.'), 'error', 6000)
  } finally {
    rebuilding.value = false
  }
}

// --- Downloads -------------------------------------------------------------

function filenameFromResponse(response, fallback) {
  const header = response.headers['content-disposition'] || response.headers.get?.('content-disposition')
  const match = header?.match(/filename="([^"]+)"/)
  return match ? match[1] : fallback
}

async function downloadRunZip(run) {
  const name = `${run.root}.zip`
  downloading.value = run.root
  try {
    const response = await axios.get(packageFileUrl(name), { responseType: 'blob' })
    await downloadFromResponse(response.data, filenameFromResponse(response, name))
  } catch (error) {
    addToast(errorDetail(error, 'Download failed.'), 'error', 6000)
  } finally {
    downloading.value = ''
  }
}

async function downloadExtra(extra) {
  downloading.value = extra.path
  try {
    const response = await axios.get(packageFileUrl(extra.path), { responseType: 'blob' })
    await downloadFromResponse(response.data, filenameFromResponse(response, extra.name || extra.path))
  } catch (error) {
    addToast(errorDetail(error, 'Download failed.'), 'error', 6000)
  } finally {
    downloading.value = ''
  }
}

// --- Export ----------------------------------------------------------------

function openExportMenu(event) {
  const rect = event.currentTarget?.getBoundingClientRect?.()
  exportMenu.value = rect
    ? { x: rect.left, y: rect.bottom + 4 }
    : { x: event.clientX, y: event.clientY }
}

const exportActions = computed(() => [
  { id: 'zip', label: 'Zip', action: () => exportPackage('zip') },
  { id: 'html', label: 'Single HTML file', action: () => exportPackage('html') },
  { id: 'link', label: 'Hosted link', disabled: true, shortcut: 'Coming soon' },
])

async function exportPackage(format) {
  try {
    const response = await axios.post(
      `${getApiBase()}/media/${currentMediaId.value}/package-export`,
      { format },
      { responseType: 'blob' },
    )
    const fallback = `${(title.value || 'package')}.${format === 'zip' ? 'zip' : 'html'}`
    await downloadFromResponse(response.data, filenameFromResponse(response, fallback))
  } catch (error) {
    // A blob response body hides the detail until it is read back as text.
    const blob = error?.response?.data
    let detail = ''
    if (blob && typeof blob.text === 'function') {
      try { detail = JSON.parse(await blob.text())?.detail || '' } catch { /* not JSON */ }
    }
    addToast(detail || errorDetail(error, 'Export failed.'), 'error', 6000)
  }
}
</script>
