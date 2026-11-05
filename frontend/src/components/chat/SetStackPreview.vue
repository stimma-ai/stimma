<script>
// Members are read once per set and shared by every tile showing it.
const membersBySet = new Map()
</script>

<script setup>
// A set drawn from its own members: the first image as the picture, the next
// two as quiet layers behind it, all on the matte (DESIGN.md §3.5b). Nothing
// here depends on the thumbnail the server bakes for a set. While the members
// load it shows the bare matte; if there is nothing to draw from it asks its
// parent (`unavailable`) to fall back to the baked thumbnail.
import { computed, ref, watch } from 'vue'
import axios from 'axios'
import { MediaImage } from '../media'
import { getMediaType } from '../../utils/mediaTypes'

const props = defineProps({
  mediaId: { type: Number, required: true },
  thumbnailSize: { type: Number, default: 512 },
})
const emit = defineEmits(['unavailable'])

const members = ref(null)

function loadMembers(mediaId) {
  if (!membersBySet.has(mediaId)) {
    membersBySet.set(mediaId, axios.get(`/api/media/${mediaId}/content`)
      .then(({ data }) => (data.items || [])
        .map(item => item.resolved)
        .filter(resolved => resolved?.media_id && ['image', 'video'].includes(getMediaType({ file_format: resolved.file_format })))
        .slice(0, 3)
        .map(resolved => resolved.media_id))
      .catch(() => {
        membersBySet.delete(mediaId)
        return []
      }))
  }
  return membersBySet.get(mediaId)
}

watch(() => props.mediaId, async (mediaId) => {
  members.value = null
  const ids = await loadMembers(mediaId)
  if (mediaId !== props.mediaId) return
  members.value = ids
  if (ids.length === 0) emit('unavailable')
}, { immediate: true })

// Layers sit back to front. Each steps 3% of the square up and to the right of the picture, so
// only a narrow edge of each shows; the whole pile is centred in the square. The scrim fades the
// layers into the matte: lighter on the paper matte, where a heavy scrim erases them, and
// heavier on the near-black one, where a pale image would otherwise glow grey.
const CARD = 78
const STEP = 3
const cards = computed(() => {
  const ids = members.value || []
  const margin = (100 - CARD - STEP * (ids.length - 1)) / 2
  return ids
    .map((id, depth) => ({
      id,
      depth,
      style: { width: `${CARD}%`, height: `${CARD}%`, left: `${margin + STEP * depth}%`, bottom: `${margin + STEP * depth}%` },
      scrim: depth === 0 ? '' : depth === 1 ? 'opacity-[.15] dark:opacity-[.78]' : 'opacity-[.35] dark:opacity-[.9]',
    }))
    .reverse()
})
</script>

<template>
  <div class="h-full w-full bg-matte [container-type:size]" data-testid="set-stack-preview">
    <div v-if="cards.length" class="relative mx-auto" style="width: min(100cqw, 100cqh); height: min(100cqw, 100cqh)">
      <div v-for="card in cards" :key="card.id" class="absolute overflow-hidden rounded-media bg-matte shadow-[0_1px_4px_rgb(0_0_0/0.22)] dark:shadow-none" :style="card.style">
        <MediaImage
          :media-id="card.id"
          :thumbnail="true"
          :thumbnail-size="thumbnailSize"
          :draggable="false"
          :enable-context-menu="false"
          container-class="h-full w-full"
          img-class="h-full w-full object-cover"
        />
        <span v-if="card.scrim" class="pointer-events-none absolute inset-0 bg-matte" :class="card.scrim"></span>
      </div>
    </div>
  </div>
</template>
