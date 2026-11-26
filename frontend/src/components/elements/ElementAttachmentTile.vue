<template>
  <!-- An element attached to a message: its cover in the attachment tile, with
       the type chip every tile uses for a non-image type (glyph only). -->
  <div class="relative h-full w-full bg-matte" :title="attachment.element?.name">
    <MediaImage :media-id="attachment.media_id" :thumbnail="true" :thumbnail-size="128" container-class="h-full w-full" />
    <span class="pointer-events-none absolute bottom-1 left-1"><TileChip><PuzzlePieceIcon aria-label="Element" /></TileChip></span>
  </div>
</template>

<script setup lang="ts">
import { PuzzlePieceIcon } from '@heroicons/vue/24/outline'
import { MediaImage, TileChip } from '../media'

defineProps<{ attachment: { media_id: number; element?: { name: string; kind: string } } }>()
</script>
