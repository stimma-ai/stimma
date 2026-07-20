<template>
  <div class="flex-1 min-w-0 bg-matte flex flex-col relative overflow-hidden">
    <!-- Header -->
    <div class="flex items-center gap-2.5 px-3.5 py-2 border-b border-edge-subtle bg-surface/60 flex-shrink-0">
      <div class="w-6 h-6 rounded flex items-center justify-center bg-accent/15 border border-accent/40 text-accent flex-shrink-0">
        <Square3Stack3DIcon class="w-3.5 h-3.5" />
      </div>
      <div class="min-w-0">
        <div class="text-[12.5px] font-semibold text-content truncate">{{ asset?.title || 'Untitled' }}</div>
        <div class="text-[10.5px] text-content-muted">
          {{ kindLabel }}<template v-if="revisions.length"> · {{ versionSubline }}</template>
        </div>
      </div>

      <div class="ml-auto flex items-center gap-1.5 flex-shrink-0">
        <!-- Version dropdown -->
        <div class="relative" ref="versionMenuRef">
          <button
            type="button"
            class="flex items-center gap-1 h-6 px-2 rounded border text-[11px] font-medium transition-colors"
            :class="onNewest ? 'border-edge bg-overlay-subtle text-content-secondary hover:bg-overlay-hover' : 'border-accent/50 bg-accent/10 text-content'"
            :disabled="!revisions.length"
            @click="showVersionMenu = !showVersionMenu"
          >
            v{{ viewedRevision?.revision_number ?? '—' }}
            <ChevronDownIcon class="w-3 h-3" />
          </button>
          <div
            v-if="showVersionMenu"
            class="absolute right-0 mt-1 w-56 max-h-72 overflow-y-auto bg-surface border border-edge-subtle rounded-lg shadow-xl z-menu py-1 custom-scrollbar"
          >
            <button
              v-for="rev in reversedRevisions"
              :key="rev.id"
              type="button"
              class="w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-[11.5px] rounded-md mx-1 transition-colors"
              :class="rev.id === viewedRevisionId ? 'bg-accent/10 text-content' : 'text-content-secondary hover:bg-overlay-hover'"
              style="width: calc(100% - 8px)"
              @click="selectVersion(rev.id)"
            >
              <span class="font-semibold w-6 flex-shrink-0">v{{ rev.revision_number }}</span>
              <span class="flex-1 min-w-0 truncate text-content-muted">{{ rev.note || '—' }}</span>
              <span v-if="rev.id === latestRevisionId" class="text-[9px] text-accent flex-shrink-0">latest</span>
            </button>
          </div>
        </div>

        <button
          v-if="!onNewest"
          type="button"
          class="h-6 px-2.5 rounded border border-edge text-[11px] font-medium text-content-secondary bg-overlay-subtle hover:bg-overlay-hover hover:text-content transition-colors disabled:opacity-50"
          :disabled="loading"
          @click="$emit('set-latest')"
        >
          {{ loading ? 'Setting…' : 'Set as latest' }}
        </button>

        <!-- Overflow menu -->
        <div class="relative" ref="overflowMenuRef">
          <button
            type="button"
            class="w-6 h-6 flex items-center justify-center rounded border border-edge text-content-muted hover:text-content hover:bg-overlay-hover transition-colors"
            title="More options"
            @click="showOverflowMenu = !showOverflowMenu"
          >
            <EllipsisHorizontalIcon class="w-4 h-4" />
          </button>
          <div
            v-if="showOverflowMenu"
            class="absolute right-0 mt-1 w-44 bg-surface border border-edge-subtle rounded-lg shadow-xl z-menu py-1"
          >
            <button
              type="button"
              class="w-full px-3 py-1.5 text-left text-xs text-content-secondary hover:bg-surface-raised transition-colors"
              @click="handleOpenInLibrary"
            >Open in library</button>
          </div>
        </div>

        <button
          type="button"
          class="w-6 h-6 flex items-center justify-center rounded border border-edge text-content-muted hover:text-content hover:bg-overlay-hover transition-colors"
          title="Close stage"
          @click="$emit('close')"
        >
          <XMarkIcon class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- Hero -->
    <div class="flex-1 min-h-0 flex flex-col relative px-3 pt-3">
      <div v-if="loading && !viewedRevision" class="flex-1 flex items-center justify-center text-content-muted text-sm">
        Loading…
      </div>
      <div v-else-if="!viewedRevision" class="flex-1 flex items-center justify-center text-content-muted text-sm">
        No versions yet
      </div>
      <template v-else>
        <!-- Jump to newest -->
        <button
          v-if="!onNewest"
          type="button"
          class="absolute top-6 left-6 z-10 flex items-center gap-1.5 bg-black/55 backdrop-blur-sm text-white font-mono text-[11px] px-3 py-1.5 rounded hover:bg-black/70 transition-colors"
          @click="$emit('jump-newest')"
        >
          <ArrowUpIcon class="w-3.5 h-3.5" />
          Jump to newest
        </button>

        <div
          class="relative flex-1 min-h-0 rounded-media overflow-hidden"
          :class="heroKind !== 'layout' ? 'cursor-zoom-in' : ''"
          @click="heroKind !== 'layout' && $emit('open-slideshow', viewedRevision.media_id)"
        >
          <LayoutViewer v-if="heroKind === 'layout'" :media-id="viewedRevision.media_id" class="w-full h-full" />
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
            v-else
            :media-id="viewedRevision.media_id"
            :thumbnail="false"
            :contain="false"
            container-class="w-full h-full !bg-transparent"
            img-class="!object-contain !bg-none !bg-transparent"
            alt="Artifact"
          />
        </div>

        <!-- Chip bar beneath the hero -->
        <div class="flex-none flex items-center gap-1.5 py-2">
          <div v-if="viewedRevision.width && viewedRevision.height" class="h-7 flex items-center px-2.5 bg-black/55 backdrop-blur-sm rounded text-[11px] font-mono text-white/80">
            {{ viewedRevision.width }} × {{ viewedRevision.height }}
          </div>
          <span class="flex-1"></span>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onBeforeUnmount } from 'vue'
import {
  ChevronDownIcon,
  EllipsisHorizontalIcon,
  XMarkIcon,
  ArrowUpIcon,
  Square3Stack3DIcon,
} from '@heroicons/vue/24/outline'
import { MediaImage } from '../media'
import LayoutViewer from '../viewers/LayoutViewer.vue'
import { useMediaApi } from '../../composables/useMediaApi'
import { getMediaType } from '../../utils/mediaTypes'
import type { ArtifactRevision } from '../../composables/useArtifactStage'

const props = defineProps<{
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
  'select-revision': [revisionId: number]
  'jump-newest': []
  'set-latest': []
  'open-slideshow': [mediaId: number]
  'open-library': [assetId: number]
}>()

const { getThumbnailUrl, getMediaFileUrl } = useMediaApi()

const showVersionMenu = ref(false)
const showOverflowMenu = ref(false)
const versionMenuRef = ref<HTMLElement | null>(null)
const overflowMenuRef = ref<HTMLElement | null>(null)

function onDocumentClick(e: MouseEvent) {
  const target = e.target as Node
  if (versionMenuRef.value && !versionMenuRef.value.contains(target)) showVersionMenu.value = false
  if (overflowMenuRef.value && !overflowMenuRef.value.contains(target)) showOverflowMenu.value = false
}
document.addEventListener('click', onDocumentClick)
onBeforeUnmount(() => document.removeEventListener('click', onDocumentClick))

const reversedRevisions = computed(() => [...props.revisions].reverse())

const heroKind = computed(() => {
  if (!props.viewedRevision) return 'image'
  return getMediaType({ file_format: props.viewedRevision.file_format })
})

const kindLabel = computed(() => {
  const kind = heroKind.value
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

function handleOpenInLibrary() {
  showOverflowMenu.value = false
  if (props.asset) emit('open-library', props.asset.id)
}
</script>
