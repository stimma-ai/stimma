<script setup>
// The picks in a chat's image collection. Docks on the composer the way
// ChatMessageQueue does, so the screen keeps one bottom bar (§1.11).
import { inject } from 'vue'
import { EllipsisHorizontalIcon } from '@heroicons/vue/24/outline'
import Button from '../ui/Button.vue'
import IconButton from '../ui/IconButton.vue'
import { CHAT_MEDIA_COLLECTIONS } from '../../composables/useChatMediaCollections'
import { useMediaContextMenu } from '../../composables/useMediaContextMenu'
import { useViewport } from '../../composables/useViewport'

const collections = inject(CHAT_MEDIA_COLLECTIONS)
const { selection } = collections
const { isCompact } = useViewport()
const contextMenu = useMediaContextMenu()

// Everything else the picks can do (collections, print, send to a tool, trash): the
// browser selection's menu, anchored above the bar.
function openActions(event) {
  // The menu closes on any document click, and this one is still bubbling.
  event.stopPropagation()
  const target = collections.selectionMenuTarget()
  if (!target) return
  const rect = event.currentTarget.getBoundingClientRect()
  contextMenu.showAt({ x: rect.right, bottomY: rect.top - 4, ...target })
}

// On a phone the panel is full screen: go back to the message being written.
function addToMessage() {
  collections.attachSelection()
  if (isCompact.value) collections.panel.close()
}
</script>

<template>
  <div class="flex min-h-10 items-center gap-2 rounded-t-lg bg-surface py-1 pl-3 pr-1.5 coarse:min-h-14" data-testid="media-selection-bar">
    <span class="flex-1 font-mono text-xs tabular-nums text-selection">{{ selection.ids.size }} selected</span>
    <Button variant="ghost" size="sm" class="coarse:min-h-11" @click="selection.selectAll()">All</Button>
    <Button v-if="!isCompact" variant="ghost" size="sm" class="coarse:min-h-11" :disabled="selection.ids.size !== 2" title="Select two images to compare" @click="collections.compareSelection()">Compare</Button>
    <Button variant="ghost" size="sm" class="coarse:min-h-11" @click="selection.clear()">Clear</Button>
    <IconButton aria-label="More actions" title="More actions" class="coarse:!h-11 coarse:!w-11" :disabled="!selection.ids.size" @click="openActions">
      <EllipsisHorizontalIcon class="h-4 w-4" />
    </IconButton>
    <Button variant="primary" size="sm" class="coarse:min-h-11" :disabled="!selection.ids.size || !collections.canAttach.value" @click="addToMessage">Add to message</Button>
  </div>
</template>
