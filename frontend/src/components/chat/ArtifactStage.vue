<template>
  <div class="flex-1 min-w-0 bg-matte flex flex-col relative overflow-hidden">
    <!-- Header -->
    <div v-if="!isEmpty" class="flex flex-wrap items-center gap-2.5 px-3.5 py-2 border-b border-edge-subtle bg-surface/60 flex-shrink-0">
      <div v-if="!workspaceArchive" class="min-w-0" :draggable="!!workspaceFile" @dragstart="workspaceFile && chatId != null && dragWorkspaceFile($event, chatId, workspaceFile)">
        <div class="text-[12.5px] font-semibold text-content truncate">{{ workspaceFile?.name || asset?.title || 'Untitled' }}</div>
        <div class="text-[10.5px] text-content-muted">
          <span v-if="workspaceFile" class="font-mono">{{ workspaceFile.path }} · {{ fileSize(workspaceFile.size) }}</span>
          <template v-else>{{ kindLabel }}<template v-if="revisions.length"> · {{ versionSubline }}</template></template>
        </div>
      </div>

      <div class="ml-auto flex flex-wrap items-center justify-end gap-0.5 min-w-0" :class="workspaceArchive ? 'w-full' : ''">
        <!-- The kebab is the same menu the artwork's right-click gives, anchored
             under the button. A second, smaller menu of its own would just be a
             place for actions to go missing. -->
        <div ref="fileControlsRef" class="flex items-center min-w-0" :class="workspaceArchive ? 'flex-1' : ''" />
        <template v-if="workspaceFile && !workspaceArchive">
          <FileActions :file="workspaceFile" :url="fileUrl(chatId!, workspaceFile, 'content', true)" @attach="$emit('attach-file', workspaceFile)" @save="$emit('save-file', workspaceFile)" />
        </template>
        <template v-else-if="!workspaceFile && !isEmpty">
          <!-- A package is a deliverable: the zip is one click, named and sized, not a menu away. -->
          <button
            v-if="heroKind === 'package'"
            type="button"
            class="inline-flex items-center gap-2 h-7 pl-2 pr-2.5 mr-1 rounded-md bg-overlay-subtle hover:bg-overlay-medium text-xs text-content transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 ring-accent/60 disabled:opacity-50"
            :title="`Download ${packageZipName}`"
            :disabled="downloadingPackage"
            @click="downloadPackage('zip')"
          >
            <ArchiveBoxIcon class="w-4 h-4 text-accent" />
            <span class="font-medium">Download {{ packageZipName }}</span>
            <span v-if="packageZipSize" class="font-mono text-content-tertiary">{{ packageZipSize }}</span>
          </button>
          <button
            v-if="heroKind === 'package'"
            type="button"
            class="inline-flex items-center gap-2 h-7 px-2.5 mr-1 rounded-md bg-overlay-subtle hover:bg-overlay-medium text-xs text-content transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 ring-accent/60 disabled:opacity-50"
            :disabled="downloadingPackage"
            @click="downloadPackage('pdf')"
          >
            <DocumentArrowDownIcon class="w-4 h-4 text-accent" />
            <span class="font-medium">Download PDF</span>
          </button>
          <!-- Version dropdown. Trigger-ghost per §7: no border, no fill; the
               off-latest state earns the accent because it is a real state, not
               decoration. -->
          <div v-if="!workspaceFile && !isEmpty" class="relative" ref="versionMenuRef">
            <button
              type="button"
              class="flex items-center gap-1 h-7 px-2 rounded-md text-[11px] font-medium transition-colors hover:bg-overlay-subtle disabled:opacity-50"
              :class="onNewest ? 'text-content-secondary hover:text-content' : 'text-accent'"
              :disabled="!revisions.length"
              @click="showVersionMenu = !showVersionMenu"
            >
              v{{ viewedRevision?.revision_number ?? '—' }}
              <ChevronDownIcon class="w-3 h-3" />
            </button>
            <div
              v-if="showVersionMenu"
              class="absolute right-0 mt-1 w-60 max-h-72 overflow-y-auto bg-surface border border-edge-subtle rounded-lg shadow-lg z-menu py-1 custom-scrollbar"
            >
              <button
                v-for="rev in reversedRevisions"
                :key="rev.id"
                type="button"
                class="w-full flex items-center gap-2 px-3 py-2 text-left text-xs transition-colors"
                :class="rev.id === viewedRevisionId ? 'text-content bg-overlay-subtle' : 'text-content hover:bg-overlay-subtle'"
                @click="selectVersion(rev.id)"
              >
                <span class="font-semibold w-6 flex-shrink-0">v{{ rev.revision_number }}</span>
                <span class="flex-1 min-w-0 truncate text-content-muted">{{ rev.note || '—' }}</span>
                <span v-if="rev.id === latestRevisionId" class="text-[10px] text-content-tertiary flex-shrink-0">latest</span>
              </button>
            </div>
          </div>

          <button
            v-if="!workspaceFile && !isEmpty && !onNewest"
            type="button"
            class="h-7 px-2 rounded-md text-[11px] font-medium text-content-secondary hover:text-content hover:bg-overlay-subtle transition-colors disabled:opacity-50"
            :disabled="loading"
            @click="$emit('set-latest')"
          >
            {{ loading ? 'Setting…' : 'Set as latest' }}
          </button>
          <div ref="overflowButtonRef" class="flex">
            <IconButton title="Actions" @click="onOverflowClick">
              <EllipsisVerticalIcon class="w-4 h-4" />
            </IconButton>
          </div>
        </template>
      </div>
    </div>

    <!-- Hero -->
    <div class="flex-1 min-h-0 flex flex-col relative" :class="workspaceFile ? '' : 'px-3 pt-3'">
      <FileViewer v-if="workspaceFile && chatId != null" :controls-target="fileControlsRef" :key="fileUrl(chatId, workspaceFile)" :url="fileUrl(chatId, workspaceFile)" :name="workspaceFile.name" :mime="workspaceFile.mime" :size="workspaceFile.size" :workspace-file="workspaceFile" :chat-id="chatId" class="flex-1 min-h-0" @attach="$emit('attach-file', $event)" @save="$emit('save-file', $event)" />
      <div v-else-if="loading && !viewedRevision" class="flex-1 flex items-center justify-center text-content-muted text-sm">
        Loading…
      </div>
      <div v-else-if="isEmpty" class="flex-1 flex flex-col items-center justify-center gap-1.5 text-center px-8">
        <div class="text-sm text-content-secondary">Nothing selected</div>
        <div class="text-xs text-content-muted max-w-xs leading-relaxed">Click a file or version in the conversation to view it here.</div>
      </div>
      <div v-else-if="!viewedRevision" class="flex-1 flex items-center justify-center text-content-muted text-sm">
        No versions yet
      </div>
      <template v-else>
        <!-- Jump to newest -->
        <button
          v-if="!workspaceFile && !onNewest"
          type="button"
          class="absolute top-6 left-6 z-10 flex items-center gap-1.5 bg-black/55 backdrop-blur-sm text-white font-mono text-[11px] px-3 py-1.5 rounded hover:bg-black/70 transition-colors"
          @click="$emit('jump-newest')"
        >
          <ArrowUpIcon class="w-3.5 h-3.5" />
          Jump to newest
        </button>

        <div
          class="relative flex-1 min-h-0 rounded-media overflow-hidden"
          :class="heroKind === 'package' ? '' : 'cursor-zoom-in'"
          @click="onHeroClick"
          @contextmenu="onHeroContextMenu"
        >
          <LayoutViewer v-if="heroKind === 'layout'" :media-id="viewedRevision.media_id" class="w-full h-full" />
          <SvgViewer v-else-if="heroKind === 'vector'" :media-id="viewedRevision.media_id" class="w-full h-full" />
          <SpritePlayer v-else-if="heroKind === 'sprite'" :key="viewedRevision.media_id" :media-id="viewedRevision.media_id" class="w-full h-full" />
          <PackageViewer v-else-if="heroKind === 'package'" :key="viewedRevision.media_id" :media-id="viewedRevision.media_id" class="w-full h-full" />
          <video
            v-else-if="heroKind === 'video'"
            :key="viewedRevision.media_id"
            :src="getMediaFileUrl(viewedRevision.media_id)"
            :poster="getThumbnailUrl(viewedRevision.media_id, 1024, { mode: 'fit' })"
            class="w-full h-full object-contain"
            controls
            playsinline
            @click.stop
          />
          <MediaImage
            v-else-if="fileKind(viewedRevision.file_format) === 'image'"
            :media-id="viewedRevision.media_id"
            :thumbnail="false"
            :contain="false"
            container-class="w-full h-full !bg-transparent"
            img-class="!object-contain !bg-none !bg-transparent"
            alt="Artifact"
          />
          <FileViewer v-else :controls-target="fileControlsRef" :url="getMediaFileUrl(viewedRevision.media_id)" :name="viewedRevision.filename || 'artifact.' + viewedRevision.file_format" :mime="viewedRevision.mime" :size="viewedRevision.file_size" :media-id="viewedRevision.media_id" :workspace-file="artifactFile" :chat-id="chatId" class="w-full h-full" @attach="$emit('attach-file', $event)" @save="$emit('save-file', $event)" />
        </div>

        <!-- Chip bar beneath the hero. The vector viewer reports the document's
             own size in its control row, so this would just say it twice. -->
        <div v-if="showDimensionChip" class="flex-none flex items-center gap-1.5 py-2">
          <div class="h-7 flex items-center px-2.5 bg-black/55 backdrop-blur-sm rounded text-[11px] font-mono text-white/80">
            {{ viewedRevision.width }} × {{ viewedRevision.height }}
          </div>
          <span class="flex-1"></span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import FileActions from './FileActions.vue'
import FileViewer from '../viewers/FileViewer.vue'
import Button from '../ui/Button.vue'
import { fileUrl, fileSize, dragWorkspaceFile, fileKind, type WorkspaceFile } from '../../utils/fileRefs'
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import {
  ChevronDownIcon,
  EllipsisVerticalIcon,
  ArrowUpIcon,
  ArchiveBoxIcon,
  DocumentArrowDownIcon,
} from '@heroicons/vue/24/outline'
import axios from 'axios'
import { getApiBase } from '../../apiConfig'
import { useTauriDownload } from '../../composables/useTauriDownload'
import { MediaImage } from '../media'
import IconButton from '../ui/IconButton.vue'
import LayoutViewer from '../viewers/LayoutViewer.vue'
import SvgViewer from '../viewers/SvgViewer.vue'
import SpritePlayer from '../viewers/SpritePlayer.vue'
import PackageViewer from '../viewers/PackageViewer.vue'
import { useMediaApi } from '../../composables/useMediaApi'
import { useMediaContextMenu } from '../../composables/useMediaContextMenu'
import { getMediaType } from '../../utils/mediaTypes'
import type { ArtifactRevision } from '../../composables/useArtifactStage'

const props = defineProps<{
  workspaceFile?: WorkspaceFile | null
  chatId?: number | string
  asset: { id: number; title: string | null; current_revision_id: number } | null
  revisions: ArtifactRevision[]
  viewedRevisionId: number | null
  viewedRevision: ArtifactRevision | null
  latestRevisionId: number | null
  onNewest: boolean
  loading: boolean
}>()

const emit = defineEmits<{
  close: []
  'attach-file': [file: WorkspaceFile]
  'save-file': [file: WorkspaceFile]
  'select-revision': [revisionId: number]
  'jump-newest': []
  'set-latest': []
  'open-slideshow': [mediaId: number]
}>()

const { getThumbnailUrl, getMediaFileUrl } = useMediaApi()
// The <MediaContextMenu> itself is mounted once by ChatView.
const contextMenu = useMediaContextMenu()

const workspaceArchive = computed(() => !!props.workspaceFile && fileKind(props.workspaceFile.name, props.workspaceFile.mime) === 'zip')
const fileControlsRef = ref<HTMLElement | null>(null)
const showVersionMenu = ref(false)
const versionMenuRef = ref<HTMLElement | null>(null)
const overflowButtonRef = ref<HTMLElement | null>(null)

function onDocumentClick(e: MouseEvent) {
  const target = e.target as Node
  if (versionMenuRef.value && !versionMenuRef.value.contains(target)) showVersionMenu.value = false
}
document.addEventListener('click', onDocumentClick)
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))

const reversedRevisions = computed(() => [...props.revisions].reverse())

const artifactFile = computed<WorkspaceFile | undefined>(() => props.viewedRevision ? {
  root: 'chat', path: 'artifact.' + props.viewedRevision.file_format,
  name: props.viewedRevision.filename || 'artifact.' + props.viewedRevision.file_format, size: props.viewedRevision.file_size || 0, mime: props.viewedRevision.mime || '', media_id: props.viewedRevision.media_id,
} : undefined)
// Panel toggled open with nothing to show: neither a previewed file nor an
// artifact asset for this chat.
const isEmpty = computed(() => !props.workspaceFile && !props.asset && !props.loading)

const heroKind = computed(() => {
  if (!props.viewedRevision) return 'image'
  return getMediaType({ file_format: props.viewedRevision.file_format })
})

const showDimensionChip = computed(() =>
  heroKind.value !== 'vector' && heroKind.value !== 'sprite' && heroKind.value !== 'package' && !!props.viewedRevision?.width && !!props.viewedRevision?.height
)

// A package's cover is a page you read in place; zooming it into the slideshow
// is the surface a package must never land on.
function onHeroClick() {
  if (heroKind.value === 'package') return
  if (props.viewedRevision) emit('open-slideshow', props.viewedRevision.media_id)
}

function contextMenuTarget() {
  const mediaId = props.viewedRevision?.media_id
  if (!mediaId) return null
  return {
    mediaId,
    mediaIds: [mediaId],
    assetId: props.asset?.id,
    assetIds: props.asset?.id ? [props.asset.id] : [],
  }
}

function onHeroContextMenu(event: MouseEvent) {
  const target = contextMenuTarget()
  if (!target) return
  contextMenu.show({ event, ...target })
}

function onOverflowClick(event?: MouseEvent) {
  // The menu closes on any document click, and this click is still on its
  // way up the tree — so it would open and close in the same beat.
  event?.stopPropagation()
  const target = contextMenuTarget()
  if (!target) return
  const rect = overflowButtonRef.value?.getBoundingClientRect()
  contextMenu.showAt({
    x: rect ? rect.right : 0,
    y: rect ? rect.bottom + 4 : 0,
    ...target,
  })
}

const { downloadFromResponse } = useTauriDownload()
const downloadingPackage = ref(false)

// The button says what it hands over: the export's real filename, and how
// much is in it. Both come from the manifest.
const packageZipName = ref('package.zip')
const packageZipSize = ref('')
watch(() => [heroKind.value, props.viewedRevision?.media_id] as const, async ([kind, mediaId]) => {
  packageZipName.value = 'package.zip'
  packageZipSize.value = ''
  if (kind !== 'package' || !mediaId) return
  try {
    const { data } = await axios.get(`${getApiBase()}/media/${mediaId}/package`)
    const manifest = data?.manifest || {}
    if (props.viewedRevision?.media_id !== mediaId) return
    const slug = manifest.slug || String(manifest.title || 'package').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
    packageZipName.value = `${slug}.zip`
    let bytes = 0
    for (const m of manifest.members || []) bytes += Number(m.size || 0)
    for (const run of manifest.runs || []) for (const f of run.files || []) bytes += Number(f.size || 0)
    for (const e of manifest.extras || []) bytes += Number(e.size || 0)
    packageZipSize.value = bytes ? fileSize(bytes) : ''
  } catch {
    /* the button still downloads; it just says less */
  }
}, { immediate: true })

async function downloadPackage(format: 'zip' | 'pdf') {
  const mediaId = props.viewedRevision?.media_id
  if (!mediaId || downloadingPackage.value) return
  downloadingPackage.value = true
  try {
    const response = await axios.post(
      `${getApiBase()}/media/${mediaId}/package-export`,
      { format },
      { responseType: 'blob' },
    )
    const disposition = response.headers['content-disposition'] || ''
    const match = disposition.match(/filename="([^"]+)"/)
    await downloadFromResponse(response.data, match ? match[1] : `package.${format}`)
  } finally {
    downloadingPackage.value = false
  }
}

const kindLabel = computed(() => {
  const kind = heroKind.value
  if (kind === 'vector') return 'SVG'
  return kind.charAt(0).toUpperCase() + kind.slice(1)
})

const versionSubline = computed(() => {
  const n = props.revisions.length
  if (props.onNewest) return `${n} version${n === 1 ? '' : 's'}`
  return `viewing v${props.viewedRevision?.revision_number} of ${n}`
})

function selectVersion(revisionId: number) {
  showVersionMenu.value = false
  emit('select-revision', revisionId)
}
</script>
