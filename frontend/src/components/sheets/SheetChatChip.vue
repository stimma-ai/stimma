<template>
  <!-- The newest version is the sheet's card, wherever it lands in the chat.
       Earlier versions fold to one quiet line each, so a long run reads as a
       short list of updates with the sheet at the bottom, not a wall of media. -->
  <button
    v-if="latest"
    type="button"
    class="flex w-full max-w-[360px] items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors"
    :class="inPanel ? 'border-accent/50 bg-accent/10 hover:bg-accent/15' : 'border-edge bg-surface hover:bg-surface-raised'"
    @click="$emit('click')"
  >
    <span class="h-12 w-12 flex-none overflow-hidden rounded-media bg-matte">
      <MediaImage :media-id="mediaId" :thumbnail="true" :thumbnail-size="128" container-class="h-full w-full" :enable-context-menu="false" :draggable="false" />
    </span>
    <span class="min-w-0 flex-1">
      <span class="flex items-center gap-1.5">
        <span class="truncate text-[13px] font-semibold text-content">{{ artifact.title || 'Contact sheet' }}</span>
        <span v-if="inPanel" class="flex-none rounded-full border border-accent/40 px-1.5 py-px text-[9px] font-medium text-accent">in panel</span>
      </span>
      <span class="block truncate text-[11px] text-content-muted">Contact sheet<template v-if="artifact.revision_number > 1"> · v{{ artifact.revision_number }}</template><template v-if="artifact.note"> · {{ artifact.note }}</template></span>
    </span>
  </button>
  <button
    v-else
    type="button"
    class="flex min-w-0 max-w-full items-center gap-2 rounded-md py-1 pl-1.5 pr-2.5 text-left text-[12.5px] text-content-secondary transition-colors hover:bg-overlay-faint hover:text-content"
    @click="$emit('click')"
  >
    <RectangleGroupIcon class="h-3.5 w-3.5 flex-none text-content-muted" />
    <span class="min-w-0 truncate">{{ artifact.revision_number > 1 ? 'Updated' : 'Started' }} the contact sheet · <span class="text-content">{{ artifact.note || `v${artifact.revision_number}` }}</span></span>
  </button>
</template>

<script setup lang="ts">
import { RectangleGroupIcon } from '@heroicons/vue/24/outline'
import { MediaImage } from '../media'
import type { ArtifactMeta } from '../../composables/useArtifactStage'

defineProps<{ artifact: ArtifactMeta; mediaId: number; inPanel?: boolean; latest?: boolean }>()
defineEmits<{ click: [] }>()
</script>
