<template>
  <!-- Docks on top of the composer (which drops its top corners to match). -->
  <div class="border border-b-0 border-edge rounded-t-lg bg-surface/60 divide-y divide-edge/60">
    <div
      v-for="msg in messages"
      :key="msg.id"
      class="flex items-center gap-2.5 min-h-10 py-1.5 pl-3 pr-1.5"
    >
      <div v-if="msg.attachments.length > 0" class="flex gap-0.5 flex-shrink-0">
        <div
          v-for="(attachment, i) in msg.attachments.slice(0, 3)"
          :key="i"
          class="w-7 h-7 rounded-media overflow-hidden bg-matte"
        >
          <span
            v-if="attachment.workspace_ref"
            class="w-full h-full flex items-center justify-center text-[9px] font-mono text-content-muted truncate px-0.5"
            :title="attachment.filename"
          >{{ attachment.filename }}</span>
          <MediaImage
            v-else-if="attachment.media_id"
            :media-id="attachment.media_id"
            :thumbnail="true"
            :thumbnail-size="64"
            container-class="w-full h-full"
          />
          <AppImage v-else :src="attachmentUrl(attachment)" container-class="w-full h-full" />
        </div>
      </div>
      <div class="flex-1 min-w-0 text-sm line-clamp-2 break-words" :class="msg.mode === 'steer' ? 'text-content' : 'text-content-secondary'">
        {{ previewText(msg) }}
      </div>
      <div class="flex items-center gap-0.5 flex-shrink-0">
        <span
          v-if="msg.mode === 'steer'"
          class="h-[26px] px-2.5 inline-flex items-center gap-1.5 rounded-md border border-accent/30 text-xs text-accent"
        >
          <Spinner size="sm" />Steering
        </span>
        <button
          v-else
          type="button"
          class="h-[26px] px-2.5 rounded-md border border-edge bg-surface-raised/50 text-xs text-content-secondary hover:bg-surface-raised hover:text-content transition-colors"
          title="Send into the current turn after the running step"
          @click="emit('steer', msg.id)"
        >
          Steer
        </button>
        <!-- A steer the server has accepted can't be taken back. -->
        <span v-if="msg.steering" class="w-[58px] h-7" />
        <template v-else>
          <IconButton title="Edit" @click="emit('edit', msg.id)">
            <PencilIcon class="w-4 h-4" />
          </IconButton>
          <IconButton title="Delete" @click="emit('remove', msg.id)">
            <TrashIcon class="w-4 h-4" />
          </IconButton>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { PencilIcon, TrashIcon } from '@heroicons/vue/24/outline'
import IconButton from '../ui/IconButton.vue'
import Spinner from '../ui/Spinner.vue'
import { MediaImage, AppImage } from '../media'
import { getApiBase } from '../../apiConfig'
import { getCurrentProfileId } from '../../composables/useProfile'
import { getCachedPin } from '../../composables/usePinLock'
import { parseMessageReferences } from '../../composables/useFlowReferences'

export interface QueuedMessage {
  id: string
  text: string
  attachments: any[]
  // 'steer' goes into the running turn at its next step; 'queue' waits for
  // the turn to end.
  mode: 'steer' | 'queue'
  // The server holds it for the running turn (accepted, not yet delivered).
  steering: boolean
}

defineProps<{ messages: QueuedMessage[] }>()
const emit = defineEmits<{ steer: [id: string]; edit: [id: string]; remove: [id: string] }>()

// Queued text carries baked-in reference headers; show what the user typed.
function previewText(msg: QueuedMessage): string {
  const { refs, text } = parseMessageReferences(msg.text)
  if (text) return text
  if (refs.length > 0) return refs.map(r => r.label).join(', ')
  return msg.attachments.length > 0 ? '' : msg.text
}

function attachmentUrl(attachment: any): string {
  if (!attachment.path) return ''
  const profileId = getCurrentProfileId()
  const pin = getCachedPin(profileId)
  let url = `${getApiBase()}/generate/reference-file?path=${encodeURIComponent(attachment.path)}&profile=${encodeURIComponent(profileId)}`
  if (pin) url += `&pin=${encodeURIComponent(pin)}`
  return url
}
</script>
