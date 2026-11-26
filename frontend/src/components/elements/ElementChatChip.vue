<template>
  <!-- An element in the transcript, on the contact sheet's pattern: the newest
       version is the element's card; earlier versions fold to one quiet line
       each. Clicking either opens that version in the panel. -->
  <button
    v-if="latest"
    type="button"
    class="flex w-full max-w-[360px] items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors"
    :class="inPanel ? 'border-accent/50 bg-accent/10 hover:bg-accent/15' : 'border-edge bg-surface hover:bg-surface-raised'"
    data-testid="element-chat-card"
    @click="$emit('click')"
  >
    <span class="h-12 w-12 flex-none overflow-hidden rounded-media bg-matte">
      <MediaImage :media-id="mediaId" :thumbnail="true" :thumbnail-size="128" container-class="h-full w-full" :enable-context-menu="false" :draggable="false" />
    </span>
    <span class="min-w-0 flex-1">
      <span class="flex items-center gap-1.5">
        <span class="truncate text-[13px] font-semibold text-content">{{ content?.name || artifact.title || 'Element' }}</span>
        <span v-if="inPanel" class="flex-none rounded-full border border-accent/40 px-1.5 py-px text-[9px] font-medium text-accent">in panel</span>
      </span>
      <span class="flex items-center gap-1 truncate text-[11px] text-content-muted">
        <PuzzlePieceIcon class="h-3 w-3 flex-none" />
        <span class="truncate">Element<template v-if="kind"> · {{ kind }}</template></span>
      </span>
    </span>
  </button>
  <button
    v-else
    type="button"
    class="flex min-w-0 max-w-full items-center gap-2 rounded-md py-1 pl-1.5 pr-2.5 text-left text-[12.5px] text-content-secondary transition-colors hover:bg-overlay-faint hover:text-content"
    :class="inPanel ? 'bg-accent/10 text-content' : ''"
    @click="$emit('click')"
  >
    <PuzzlePieceIcon class="h-3.5 w-3.5 flex-none text-content-muted" />
    <span class="min-w-0 truncate">
      <template v-if="artifact.revision_number > 1">Updated <span class="text-content">{{ title }}</span><template v-if="artifact.note"> · {{ artifact.note }}</template></template>
      <template v-else>Made <span class="text-content">{{ title }}</span></template>
    </span>
  </button>
</template>

<script setup lang="ts">
import { computed, toRef } from 'vue'
import { PuzzlePieceIcon } from '@heroicons/vue/24/outline'
import { MediaImage } from '../media'
import type { ArtifactMeta } from '../../composables/useArtifactStage'
import { kindLabel, useElement } from './useElements'

const props = defineProps<{ artifact: ArtifactMeta; mediaId: number; inPanel?: boolean; latest?: boolean }>()
defineEmits<{ click: [] }>()
const content = useElement(toRef(props, 'mediaId'))
const kind = computed(() => kindLabel(content.value?.kind))
// The element's current name; the card's saved title only until it loads.
const title = computed(() => content.value?.name || props.artifact.title || 'element')
</script>
