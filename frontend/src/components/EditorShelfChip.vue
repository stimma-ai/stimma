<template>
  <div class="relative group/chip w-8 h-8 coarse:w-11 coarse:h-11">
    <button
      class="block w-full h-full rounded-media bg-matte overflow-hidden cursor-pointer border-none p-0"
      :title="title"
      @click="$emit('open')"
      @contextmenu.prevent="$emit('contextmenu', $event)"
    >
      <MediaImage
        v-if="entry.mediaId"
        :media-id="Number(entry.mediaId)"
        :asset-id="Number(entry.assetId)"
        thumbnail
        :thumbnail-size="96"
        :enable-context-menu="false"
        container-class="w-full h-full"
        img-class="w-full h-full object-cover"
      />
      <span v-else class="block w-full h-full bg-overlay-subtle"></span>
    </button>

    <!-- Selection ring as an overlay, not a ring on the button: an inset
         box-shadow paints under the element's children, so a full-bleed
         thumbnail hides it. Drawn inside the footprint so nothing resizes. -->
    <span
      v-if="active"
      class="absolute inset-0 rounded-media ring-2 ring-selection ring-inset pointer-events-none"
    ></span>

    <!-- No unsaved indicator here. The editor's own header carries it where
         it can be acted on, and on a 48px thumbnail it was a mark you had to
         decode rather than read. Unsaved still outranks recency for shelf
         slots, so the state protects the chip without decorating it. -->

    <!-- Pinned chips hold their slot and never fall behind the +N chip. -->
    <span
      v-if="entry.pinned"
      class="absolute left-0.5 bottom-0.5 w-3 h-3 rounded bg-black/55 backdrop-blur flex items-center justify-center pointer-events-none"
      title="Pinned"
    >
      <svg class="w-2 h-2 text-content-secondary" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 17v5M7 4h10l-1.2 6.5 2.7 3H5.5l2.7-3z" />
      </svg>
    </span>

    <!-- Removes the shortcut, not the work: the stack lives on the asset. -->
    <button
      class="absolute right-0.5 top-0.5 w-3.5 h-3.5 rounded bg-black/55 backdrop-blur text-content-secondary hover:text-content flex items-center justify-center opacity-0 group-hover/chip:opacity-100 focus:opacity-100 transition-opacity"
      title="Remove from shelf (edits stay with the image)"
      @click.stop="$emit('remove')"
    >
      <svg class="w-2.5 h-2.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" data-stroke="own">
        <path d="M6 18L18 6M6 6l12 12" />
      </svg>
    </button>
  </div>
</template>

<script setup lang="ts">
/**
 * One open editor on the shelf. The chip is the asset — no title, because a
 * name derived from a batch of near-identical generations tells you less than
 * the thumbnail does.
 *
 * Media-tile grammar (DESIGN.md §media tile): matte, `rounded-media`, no
 * border, no hover-scale, inset selection ring, overlay controls fading in on
 * hover. A chip never changes size or position on interaction.
 */
import { computed } from 'vue'
import MediaImage from './media/MediaImage.vue'
import type { ShelfEntry } from '../utils/editorShelf'

const props = defineProps<{
  entry: ShelfEntry
  /** This editor is the one on screen. */
  active?: boolean
}>()

defineEmits<{
  open: []
  remove: []
  contextmenu: [event: MouseEvent]
}>()

const title = computed(() => {
  const name = props.entry.displayName?.trim() || 'Edit'
  return props.entry.unsaved ? `${name} — unsaved edits` : name
})
</script>
