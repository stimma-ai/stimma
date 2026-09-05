<template>
  <!-- In-flight generation as a full result tile. For preview-capable
       providers every active job renders at tile size (no slim/tile mixing in
       the strip): queued/waiting show a clock, processing shows a spinner
       until the live diffusion preview arrives, then frames sharpen in place.
       The preview is an ephemeral blob: URL, never library media — hence a
       raw <img> with no MediaImage drag/context machinery. -->
  <div
    :class="[
      'group relative w-full rounded-media overflow-hidden bg-matte',
      clickable && previewUrl ? 'cursor-pointer' : 'cursor-default',
    ]"
    :style="{ aspectRatio: aspect || '1 / 1' }"
    :title="name"
    @click="clickable && previewUrl && $emit('click')"
    @contextmenu.prevent.stop="onContextMenu"
  >
    <LivePreviewImage v-if="previewUrl" :url="previewUrl" />
    <!-- Placeholder: centered status glyph on the matte. -->
    <div v-else class="w-full h-full flex flex-col items-center justify-center gap-2 text-content-muted">
      <Spinner
        v-if="status === 'processing'"
        size="md"
        :hue="spinnerHue('running')"
      />
      <Spinner
        v-else-if="status === 'enhancing'"
        size="md"
        :hue="spinnerHue('special')"
      />
      <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clip-rule="evenodd" />
      </svg>
      <span class="text-[11px] compact:hidden">{{ placeholderLabel }}</span>
    </div>

    <!-- Progress on the bottom edge (blue-500 = status). Determinate only once
         real work is visible; before the first frame the fraction is not
         meaningful (see `shownProgress`) so the track shimmers instead. -->
    <div v-if="status === 'processing' || status === 'enhancing'" class="absolute inset-x-0 bottom-0 h-[3px] bg-white/10 overflow-hidden">
      <div
        v-if="shownProgress != null"
        :class="['h-full transition-all duration-300', dotClass('running')]"
        :style="{ width: `${Math.round(shownProgress * 100)}%` }"
      ></div>
      <span
        v-else
        class="absolute inset-0 animate-shimmer bg-gradient-to-r from-transparent via-blue-400/50 to-transparent bg-[length:300%_100%]"
      ></span>
    </div>

    <!-- Forming, not finished: a softly pulsing status hairline frames the
         tile the whole time it's live — the cue for why this item doesn't
         click into the slideshow like its finished neighbors. Distinct from
         the indigo selection ring (blue-500 = status). -->
    <div :class="['pointer-events-none absolute inset-0 rounded-media ring-1 ring-inset animate-pulse-soft', ringClass('running')]"></div>

    <!-- Current-item ring, same treatment as completed tiles. -->
    <div
      v-if="current"
      class="pointer-events-none absolute inset-0 z-chrome rounded-media ring-2 ring-inset ring-selection"
    ></div>

    <button
      v-if="status !== 'waiting'"
      @click.stop="$emit('cancel')"
      class="absolute top-1.5 right-1.5 w-6 h-6 rounded-md bg-black/55 flex items-center justify-center text-white/80 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
      title="Cancel"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5">
        <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
      </svg>
    </button>

    <!-- A generating tile has no media, so the media context menu doesn't
         apply — but it must still claim the right-click, or the event falls
         through to the webview's own menu. Cancel is the only action that
         means anything here. -->
    <ActionMenu
      v-if="menu.visible"
      :x="menu.x"
      :y="menu.y"
      :actions="menuActions"
      @close="menu.visible = false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, reactive } from 'vue'
import Spinner from '../ui/Spinner.vue'
import ActionMenu from '../ActionMenu.vue'
import LivePreviewImage from './LivePreviewImage.vue'
import { dotClass, ringClass, spinnerHue } from '../../utils/statusColors'

const props = withDefaults(defineProps<{
  /** Tool/model name — tooltip only; the strip is single-tool so showing it
      on every tile is noise. */
  name: string
  /** 'queued' | 'assigned' | 'enhancing' | 'processing' | 'waiting'. */
  status?: string
  /** CSS aspect-ratio (e.g. "1024 / 576") from the job's requested
      resolution; the tile holds this shape from spinner to finished media. */
  aspect?: string | null
  /** Ephemeral blob: URL of the latest preview frame ('' until one exists). */
  previewUrl?: string
  /** 0..1 determinate progress, or null while unknown. */
  progress?: number | null
  /** Show the current-item ring (stage: this tile drives the hero). */
  current?: boolean
  /** Whether clicking selects the live view (stage). */
  clickable?: boolean
  /** Preview-capable tool that hasn't produced its first frame yet: the
      reported fraction is a floor, not real progress, so hide it. */
  awaitingFirstPreview?: boolean
}>(), {
  status: 'processing',
  aspect: null,
  previewUrl: '',
  progress: null,
  current: false,
  clickable: false,
  awaitingFirstPreview: false,
})

// Progress before the first preview frame is not a useful number: the
// provider reports a floor (~10%) while it is still loading models and has
// produced nothing, so a tile would sit at "10%" and then jump to 10% again
// once sampling actually starts. On preview-capable tools, hold the bar
// indeterminate until the first frame lands, then track the real fraction.
const shownProgress = computed(() => {
  if (props.awaitingFirstPreview) return null
  return props.progress
})

const menu = reactive({ visible: false, x: 0, y: 0 })
const menuActions = computed(() => [
  { id: 'cancel', label: 'Cancel', danger: true, action: () => emit('cancel') },
])
function onContextMenu(event: MouseEvent) {
  menu.x = event.clientX
  menu.y = event.clientY
  menu.visible = true
}

// The placeholder carries no percentage — a number next to a spinner on an
// empty tile reads as filler; the progress bar is the readout.
//
// "Preparing…" is only honest while a first preview frame is actually coming
// (model load, VAE encode). With previews unavailable — the setting is off, or
// the provider doesn't stream them — no frame will ever arrive, so the tile
// would sit on "Preparing…" for the whole run; say "Generating…" instead.
const placeholderLabel = computed(() => {
  switch (props.status) {
    case 'processing': return props.awaitingFirstPreview ? 'Preparing…' : 'Generating…'
    case 'enhancing': return 'Enhancing prompt…'
    case 'waiting': return 'Waiting for slot…'
    default: return 'Queued…'
  }
})

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'click'): void
}>()
</script>
