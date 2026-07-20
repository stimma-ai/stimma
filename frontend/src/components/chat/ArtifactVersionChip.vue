<template>
  <button
    type="button"
    class="flex items-center gap-2.5 rounded-lg border px-2.5 py-2 text-left transition-colors max-w-[280px]"
    :class="isCurrent
      ? 'border-accent/50 bg-accent/10 hover:bg-accent/15'
      : 'border-edge-subtle bg-overlay-subtle hover:bg-overlay-hover'"
    @click="$emit('click')"
  >
    <div class="w-8 h-11 rounded flex-shrink-0 overflow-hidden bg-matte">
      <MediaImage
        v-if="revision"
        :media-id="revision.media_id"
        :thumbnail="true"
        :thumbnail-size="128"
        :contain="true"
        container-class="w-full h-full"
      />
    </div>
    <div class="min-w-0 flex-1">
      <div class="flex items-center gap-1.5">
        <span class="text-[12px] font-semibold text-content">v{{ artifact.revision_number }}</span>
        <span v-if="isCurrent" class="text-[9px] font-medium text-accent border border-accent/40 rounded-full px-1.5 py-px flex-shrink-0">
          current
        </span>
        <span v-else-if="isLatest" class="text-[9px] font-medium text-content-muted border border-edge rounded-full px-1.5 py-px flex-shrink-0">
          latest
        </span>
      </div>
      <div v-if="artifact.note" class="text-[11px] text-content-muted truncate">{{ artifact.note }}</div>
    </div>
  </button>
</template>

<script setup lang="ts">
import { MediaImage } from '../media'
import type { ArtifactMeta, ArtifactRevision } from '../../composables/useArtifactStage'

defineProps<{
  artifact: ArtifactMeta
  revision: ArtifactRevision | null
  isCurrent?: boolean
  isLatest?: boolean
}>()
defineEmits<{ click: [] }>()
</script>
