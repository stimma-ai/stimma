<template>
  <div class="flex-1 min-w-0 bg-matte flex flex-col relative overflow-hidden">
    <!-- Header -->
    <div class="flex items-center gap-2.5 px-3.5 py-2 border-b border-edge-subtle bg-surface/60 flex-shrink-0">
      <div class="min-w-0">
        <div class="text-[12.5px] font-semibold text-content truncate">{{ asset?.title || 'Untitled' }}</div>
        <div class="text-[10.5px] text-content-muted">
          {{ kindLabel }}<template v-if="revisions.length"> · {{ versionSubline }}</template>
        </div>
      </div>

      <div class="ml-auto flex items-center gap-0.5 flex-shrink-0">
        <!-- Version dropdown. Trigger-ghost per §7: no border, no fill; the
             off-latest state earns the accent because it is a real state, not
             decoration. -->
        <div class="relative" ref="versionMenuRef">
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
          v-if="!onNewest"
          type="button"
          class="h-7 px-2 rounded-md text-[11px] font-medium text-content-secondary hover:text-content hover:bg-overlay-subtle transition-colors disabled:opacity-50"
          :disabled="loading"
          @click="$emit('set-latest')"
        >
          {{ loading ? 'Setting…' : 'Set as latest' }}
        </button>

        <!-- The kebab is the same menu the artwork's right-click gives, anchored
             under the button. A second, smaller menu of its own would just be a
             place for actions to go missing. -->
        <div ref="overflowButtonRef" class="flex">
          <IconButton title="Actions" @click="onOverflowClick">
            <EllipsisHorizontalIcon class="w-4 h-4" />
          </IconButton>
        </div>

        <IconButton title="Close stage" @click="$emit('close')">
          <XMarkIcon class="w-4 h-4" />
        </IconButton>
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
          class="relative flex-1 min-h-0 rounded-media overflow-hidden cursor-zoom-in"
          @click="$emit('open-slideshow', viewedRevision.media_id)"
          @contextmenu="onHeroContextMenu"
        >
          <LayoutViewer v-if="heroKind === 'layout'" :media-id="viewedRevision.media_id" class="w-full h-full" />
          <SvgViewer v-else-if="heroKind === 'vector'" :media-id="viewedRevision.media_id" class="w-full h-full" />
          <SpritePlayer v-else-if="heroKind === 'sprite'" :key="viewedRevision.media_id" :media-id="viewedRevision.media_id" class="w-full h-full" />
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
import { computed, ref, onBeforeUnmount } from 'vue'
import {
  ChevronDownIcon,
  EllipsisHorizontalIcon,
  XMarkIcon,
  ArrowUpIcon,
} from '@heroicons/vue/24/outline'
import { MediaImage } from '../media'
import IconButton from '../ui/IconButton.vue'
import LayoutViewer from '../viewers/LayoutViewer.vue'
import SvgViewer from '../viewers/SvgViewer.vue'
import SpritePlayer from '../viewers/SpritePlayer.vue'
import { useMediaApi } from '../../composables/useMediaApi'
import { useMediaContextMenu } from '../../composables/useMediaContextMenu'
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
}>()

const { getThumbnailUrl, getMediaFileUrl } = useMediaApi()
// The <MediaContextMenu> itself is mounted once by ChatView.
const contextMenu = useMediaContextMenu()

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

const heroKind = computed(() => {
  if (!props.viewedRevision) return 'image'
  return getMediaType({ file_format: props.viewedRevision.file_format })
})

const showDimensionChip = computed(() =>
  heroKind.value !== 'vector' && heroKind.value !== 'sprite' && !!props.viewedRevision?.width && !!props.viewedRevision?.height
)

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

function onOverflowClick() {
  const target = contextMenuTarget()
  if (!target) return
  const rect = overflowButtonRef.value?.getBoundingClientRect()
  contextMenu.showAt({
    x: rect ? rect.right : 0,
    y: rect ? rect.bottom + 4 : 0,
    ...target,
  })
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
