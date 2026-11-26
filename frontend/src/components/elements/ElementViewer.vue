<template>
  <!-- An element viewer is a readable page: what this element is and what's
       in it. Like a markdown asset it scrolls inside the stage; its verbs
       (Refine in chat, Send to tool) live in the media info panel on desktop
       and under the name on a phone, where the panel is a sheet. The only
       direct edits are the name and the cover; everything else is done by
       asking in chat. -->
  <div class="h-full w-full overflow-y-auto bg-surface-raised custom-scrollbar select-text" data-testid="element-viewer" @contextmenu="$emit('contextmenu', $event)">
    <div v-if="el" class="mx-auto max-w-3xl" :class="compact ? 'px-4 pb-8 pt-4' : 'px-8 pb-12 pt-10'">
      <!-- Identity: cover, name, kind -->
      <header class="flex items-end gap-5 narrow:flex-col narrow:items-stretch narrow:gap-4">
        <div
          class="group/cover relative flex-none overflow-hidden rounded-media bg-matte"
          :class="compact ? 'h-40 w-40 narrow:aspect-[4/3] narrow:h-auto narrow:w-full' : 'h-44 w-44'"
        >
          <MediaImage
            :media-id="coverMediaId"
            :file-hash="coverHash"
            :thumbnail-size="512"
            :draggable="false"
            :enable-context-menu="false"
            container-class="h-full w-full"
            img-class="h-full w-full object-cover"
          />
        </div>

        <div class="min-w-0 flex-1">
          <div v-if="kind" class="flex items-center gap-1.5 text-xs text-content-tertiary">
            <PuzzlePieceIcon class="h-3.5 w-3.5 flex-none" :stroke-width="1.75" />
            <span>{{ kind }}</span>
          </div>
          <!-- Rename: tap the title to edit it, as chats and tool windows do.
               On a phone every rename goes through the ⋯ sheet instead. -->
          <input
            v-if="editing"
            ref="nameInput"
            v-model="draftName"
            v-no-autocorrect
            class="-mx-1.5 mt-1 w-[calc(100%+0.75rem)] rounded-md border border-edge bg-surface px-1.5 py-0.5 text-2xl font-semibold text-content outline-none focus:border-accent"
            aria-label="Element name"
            @keydown.enter.prevent="commitRename"
            @keydown.esc.stop.prevent="editing = false"
            @blur="commitRename"
          >
          <div v-else class="group/name mt-1 flex min-w-0 items-center gap-1">
            <h1
              class="m-0 min-w-0 truncate font-semibold leading-tight text-content"
              :class="[compact ? 'text-[22px]' : 'text-2xl', compact ? '' : 'cursor-text']"
              @click="!compact && startRename()"
            >{{ el.name }}</h1>
            <Tooltip v-if="!compact" text="Rename">
              <IconButton aria-label="Rename" class="opacity-0 transition-opacity group-hover/name:opacity-100 focus-visible:opacity-100" @click="startRename">
                <PencilIcon class="h-4 w-4" />
              </IconButton>
            </Tooltip>
          </div>
          <div class="mt-1 font-mono text-[11px] tabular-nums text-content-muted">Updated {{ updatedAgo }}</div>

          <!-- Phone: the two verbs under the name (the panel is a sheet here). -->
          <div v-if="compact" class="mt-4 grid grid-cols-2 gap-2">
            <Button variant="primary" size="md" class="w-full" @click="elementActions.refineInChat(mediaId)">
              <ChatBubbleLeftEllipsisIcon class="h-4 w-4" />
              Refine in chat
            </Button>
            <SendToToolMenu :media-item="sendItem" media-type="element" class="[&>button]:h-full [&>button]:justify-center" />
          </div>
        </div>
      </header>

      <!-- Instructions: ELEMENT.md, read as the agent reads it -->
      <section v-if="instructionsHtml" :class="compact ? 'mt-7' : 'mt-10'">
        <h2 :class="sectionClass">Instructions</h2>
        <ChatMarkdown class="prose prose-sm compact:prose-read max-w-none text-content select-text prose-headings:!mb-2 prose-headings:!mt-6 prose-headings:!text-[15px] compact:prose-headings:!text-[16px] prose-headings:font-semibold [&_div>:first-child]:!mt-0" :html="instructionsHtml" />
      </section>

      <!-- Media: the element's pictures and clips; one of them is the cover -->
      <section v-if="media.length" :class="compact ? 'mt-7' : 'mt-10'">
        <h2 :class="sectionClass">Media</h2>
        <div class="grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] gap-2 narrow:grid-cols-3">
          <div
            v-for="m in media"
            :key="m.key"
            class="group/media relative aspect-square overflow-hidden rounded-media bg-matte"
            :class="m.is_cover ? 'ring-2 ring-inset ring-selection' : ''"
          >
            <MediaImage
              :media-id="m.media_id"
              :file-hash="m.file_hash"
              :thumbnail-size="256"
              container-class="h-full w-full"
              img-class="h-full w-full object-cover"
            />
            <TileChip v-if="m.is_cover" class="absolute bottom-1.5 left-1.5">Cover</TileChip>
            <button
              v-else-if="!compact"
              type="button"
              class="absolute bottom-1.5 left-1.5 opacity-0 transition-opacity group-hover/media:opacity-100 focus-visible:opacity-100"
              @click="setCover(m.key)"
            ><TileChip class="hover:bg-black/75">Set as cover</TileChip></button>
            <TileChip v-if="isVideoFormat(m.file_format)" class="absolute right-1.5 top-1.5">
              <PlayIcon />
            </TileChip>
          </div>
        </div>
      </section>

      <!-- LoRAs -->
      <section v-if="el.loras.length" :class="compact ? 'mt-7' : 'mt-10'">
        <h2 :class="sectionClass">LoRAs</h2>
        <div>
          <div v-for="lora in el.loras" :key="lora.key" class="flex items-center gap-3 border-b border-edge-subtle py-2 last:border-b-0">
            <div class="min-w-0 flex-1">
              <div class="truncate text-sm text-content">{{ loraName(lora) }}</div>
              <div v-if="lora.model_family" class="truncate text-xs text-content-tertiary">For {{ familyLabel(lora.model_family) }}</div>
            </div>
            <span v-if="lora.default_weight != null" class="flex-none font-mono text-xs tabular-nums text-content-tertiary">{{ lora.default_weight.toFixed(2) }}</span>
          </div>
        </div>
      </section>

      <!-- Companion files: fonts, marks, documents the agent uses after generating -->
      <section v-if="el.files.length" :class="compact ? 'mt-7' : 'mt-10'">
        <h2 :class="sectionClass">Companion files</h2>
        <div>
          <div v-for="f in el.files" :key="f.path" class="flex items-center gap-3 border-b border-edge-subtle py-2 last:border-b-0">
            <component :is="fileIcon(f.name)" class="h-4 w-4 flex-none text-content-tertiary" :stroke-width="1.75" />
            <span class="min-w-0 flex-1 truncate text-sm text-content">{{ f.label || f.name }}</span>
            <span class="flex-none font-mono text-xs tabular-nums text-content-tertiary">{{ fileSize(f.size ?? undefined) }}</span>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, toRef, watch } from 'vue'
import {
  ChatBubbleLeftEllipsisIcon, DocumentIcon, DocumentTextIcon, PencilIcon, PencilSquareIcon, PuzzlePieceIcon,
} from '@heroicons/vue/24/outline'
import { PlayIcon } from '@heroicons/vue/16/solid'
import MediaImage from '../media/MediaImage.vue'
import TileChip from '../media/TileChip.vue'
import ChatMarkdown from '../chat/ChatMarkdown.vue'
import SendToToolMenu from '../SendToToolMenu.vue'
import Button from '../ui/Button.vue'
import IconButton from '../ui/IconButton.vue'
import Tooltip from '../ui/Tooltip.vue'
import { renderSafeMarkdown } from '../../utils/sanitizeHtml'
import { formatRelativeTime } from '../../utils/timeFormat'
import { fileSize } from '../../utils/fileRefs'
import { elementActions, elementUi, kindLabel, saveElement, useElement, type ElementLora } from './useElements'
import { elementInstructionsMarkdown, familyLabel, isVideoFormat } from './elementText'

const props = withDefaults(defineProps<{ mediaId: number; compact?: boolean }>(), { compact: false })
defineEmits<{ contextmenu: [event: MouseEvent] }>()

// The info panel's section heading, one step up for a reading page.
const sectionClass = 'm-0 mb-3 text-xs font-semibold text-content-secondary'

const el = useElement(toRef(props, 'mediaId'))
const kind = computed(() => kindLabel(el.value?.kind))
const media = computed(() => (el.value?.media || []).filter(m => !m.missing && m.media_id != null))
const coverSlot = computed(() => media.value.find(m => m.is_cover) || null)
// A text-only element has no cover member; its typographic tile stands in.
const coverMediaId = computed(() => coverSlot.value?.media_id ?? props.mediaId)
const coverHash = computed(() => coverSlot.value?.file_hash ?? undefined)
const updatedAgo = computed(() => el.value ? formatRelativeTime(el.value.updated_at) : '')
// What Send to tool hands over: the element itself, not its cover.
const sendItem = computed(() => ({ id: props.mediaId, file_format: 'stimmaelement' }))

const instructionsHtml = computed(() => {
  const md = elementInstructionsMarkdown(el.value?.instructions_display || '')
  return md.trim() ? renderSafeMarkdown(md) : ''
})

const loraName = (lora: ElementLora) => lora.display_name || lora.key
const fileIcon = (name: string) => /\.(pdf|txt|md)$/i.test(name) ? DocumentTextIcon : /\.svg$/i.test(name) ? PencilSquareIcon : DocumentIcon

async function setCover(key: string) {
  await saveElement(props.mediaId, { cover_member_key: key })
}

// ---- rename ----
const editing = ref(false)
const draftName = ref('')
const nameInput = ref<HTMLInputElement | null>(null)
async function startRename() {
  if (!el.value) return
  draftName.value = el.value.name
  editing.value = true
  await nextTick()
  nameInput.value?.select()
}
async function commitRename() {
  if (!editing.value) return
  editing.value = false
  const next = draftName.value.trim()
  if (next && next !== el.value?.name) await saveElement(props.mediaId, { name: next })
}
// Rename from a menu while this viewer is open (desktop): edit in place here.
watch(() => [props.mediaId, props.compact] as const, ([id, compact]) => {
  elementUi.inlineRenameHost = compact ? null : id
}, { immediate: true })
watch(() => elementUi.renaming, id => {
  if (!props.compact && id === props.mediaId) { elementUi.renaming = null; startRename() }
})
onBeforeUnmount(() => { if (elementUi.inlineRenameHost === props.mediaId) elementUi.inlineRenameHost = null })
</script>
