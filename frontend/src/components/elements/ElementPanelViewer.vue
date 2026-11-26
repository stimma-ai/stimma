<template>
  <!-- An element in the artifact panel, read like a document: its cover, then
       its instructions in the Markdown viewer's type, then what it holds.
       A section with nothing in it is left out. -->
  <div class="overflow-y-auto custom-scrollbar bg-base" data-testid="element-viewer">
    <div v-if="!content" class="flex h-full items-center justify-center text-sm text-content-muted">Loading…</div>
    <div v-else class="mx-auto max-w-2xl space-y-section px-5 py-5 compact:px-4">
      <button
        type="button"
        class="block w-full overflow-hidden rounded-media bg-matte cursor-zoom-in"
        :title="`Open ${content.name}'s media`"
        @click="openMedia(coverMediaId)"
      >
        <MediaImage :media-id="coverMediaId" :thumbnail="true" :thumbnail-size="1024" thumbnail-mode="fit" :contain="true" :enable-context-menu="false" container-class="w-full aspect-[16/9]" />
      </button>

      <section v-if="instructionsHtml">
        <h3 class="mb-1 text-sm font-semibold text-content">Instructions</h3>
        <div
          class="md-viewer-prose prose prose-sm max-w-none select-text [&>:first-child]:mt-0 [&_h2]:!text-[1.05em] [&_h2]:!mt-5 [&_h2]:!mb-1.5"
          :class="isDark ? 'prose-invert md-viewer-dark' : 'md-viewer-light'"
          v-html="instructionsHtml"
        />
      </section>

      <section v-if="mediaIds.length">
        <h3 class="mb-2 text-sm font-semibold text-content">Media</h3>
        <div class="grid grid-cols-4 gap-0.5 compact:grid-cols-3">
          <button
            v-for="id in mediaIds"
            :key="id"
            type="button"
            class="aspect-square overflow-hidden rounded-media bg-matte"
            @click="openMedia(id)"
          >
            <MediaImage :media-id="id" :thumbnail="true" :thumbnail-size="256" :contain="true" container-class="h-full w-full" />
          </button>
        </div>
      </section>

      <section v-if="content.loras.length">
        <h3 class="mb-1 text-sm font-semibold text-content">LoRAs</h3>
        <div class="divide-y divide-edge-subtle">
          <div v-for="lora in content.loras" :key="lora.key" class="flex min-h-11 items-center gap-3 py-1.5">
            <div class="min-w-0 flex-1">
              <div class="truncate text-sm text-content">{{ lora.display_name || lora.key }}</div>
              <div v-if="lora.model_family" class="truncate text-xs text-content-muted">{{ familyLabel(lora.model_family) }}</div>
            </div>
            <span v-if="lora.default_weight != null" class="font-mono text-xs tabular-nums text-content-secondary">{{ lora.default_weight.toFixed(2) }}</span>
          </div>
        </div>
      </section>

      <section v-if="content.files.length">
        <h3 class="mb-1 text-sm font-semibold text-content">Companion files</h3>
        <div class="divide-y divide-edge-subtle">
          <div v-for="file in content.files" :key="file.path" class="flex min-h-11 items-center gap-2.5 py-1.5">
            <FileChipIcon :name="file.name" />
            <span class="min-w-0 flex-1 truncate text-sm text-content">{{ file.label || file.name }}</span>
            <span class="text-xs text-content-muted">{{ fileSize(file.size ?? undefined) }}</span>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, toRef } from 'vue'
import { MediaImage } from '../media'
import FileChipIcon from '../chat/FileChipIcon.vue'
// Imported for its stylesheet: the element's instructions use the Markdown
// viewer's prose styles, so they read like any other document in the app.
import '../viewers/MarkdownViewer.vue'
import { renderSafeMarkdown } from '../../utils/sanitizeHtml'
import { useTheme } from '../../composables/useTheme'
import { fileSize } from '../../utils/fileRefs'
import { useElement } from './useElements'
import { elementInstructionsMarkdown, familyLabel } from './elementText'

const props = defineProps<{ mediaId: number }>()
const emit = defineEmits<{ 'open-media': [mediaIds: number[], index: number] }>()

const content = useElement(toRef(props, 'mediaId'))
const { resolvedTheme } = useTheme()
const isDark = computed(() => resolvedTheme.value === 'dark')

const mediaIds = computed(() => (content.value?.media || [])
  .filter(m => !m.missing && m.media_id != null)
  .map(m => m.media_id as number))
const coverMediaId = computed(() => content.value?.cover?.missing === false && content.value.cover.media_id != null
  ? content.value.cover.media_id
  : props.mediaId)

// The panel header already names the element, so a leading "# Name" is not repeated.
const instructionsHtml = computed(() => {
  const md = elementInstructionsMarkdown(content.value?.instructions_display || '')
  return md.trim() ? renderSafeMarkdown(md) : ''
})

function openMedia(id: number) {
  const ids = mediaIds.value
  if (!ids.length) return
  const index = ids.indexOf(id)
  emit('open-media', ids, Math.max(0, index))
}
</script>
