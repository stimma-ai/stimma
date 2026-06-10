<template>
  <div
    class="chat-item-wrapper"
    :data-item-id="itemId"
    @mouseenter="hovered = true"
    @mouseleave="hovered = false"
  >
    <!-- Chat content -->
    <slot></slot>
    <!-- Actions row (outside bubble, appears on hover) -->
    <div
      v-if="showActions"
      class="flex gap-1 mt-1"
      :class="[
        align === 'left' ? 'justify-start' : 'justify-end',
        hovered ? 'visible' : 'invisible'
      ]"
    >
      <!-- Edit (user messages only) -->
      <button
        v-if="showEdit"
        @click.stop="$emit('edit')"
        class="p-1 rounded text-content-muted hover:text-blue-500 hover:bg-blue-900/30 transition-colors"
        title="Edit message"
      >
        <PencilSquareIcon class="w-3.5 h-3.5" />
      </button>
      <!-- Replay (user messages only) -->
      <button
        v-if="showReplay"
        @click.stop="$emit('replay')"
        class="p-1 rounded text-content-muted hover:text-emerald-500 hover:bg-emerald-900/30 transition-colors"
        title="Clear chat and re-send"
      >
        <ArrowPathRoundedSquareIcon class="w-3.5 h-3.5" />
      </button>
      <!-- Thumbs (assistant messages; exists only in official builds —
           dev builds render them disabled with the source-build tooltip) -->
      <template v-if="showThumbs">
        <button
          @click.stop="handleThumb('up')"
          :disabled="!thumbsEnabled"
          class="p-1 rounded transition-colors"
          :class="thumbsEnabled
            ? 'text-content-muted hover:text-blue-500 hover:bg-blue-500/10'
            : 'text-content-muted/40 cursor-default'"
          :title="thumbsDisabledReason || 'Good response — send feedback'"
        >
          <HandThumbUpIcon class="w-3.5 h-3.5" />
        </button>
        <button
          @click.stop="handleThumb('down')"
          :disabled="!thumbsEnabled"
          class="p-1 rounded transition-colors"
          :class="thumbsEnabled
            ? 'text-content-muted hover:text-red-500 hover:bg-red-500/10'
            : 'text-content-muted/40 cursor-default'"
          :title="thumbsDisabledReason || 'Bad response — send feedback'"
        >
          <HandThumbDownIcon class="w-3.5 h-3.5" />
        </button>
      </template>
      <!-- Trash -->
      <button
        @click.stop="handleTrash($event)"
        class="p-1 rounded text-content-muted hover:text-red-500 hover:bg-red-500/10 transition-colors"
        title="Delete"
      >
        <TrashIcon class="w-3.5 h-3.5" />
      </button>
      <!-- Debug (dev mode only) -->
      <button
        v-if="devModeRef"
        @click.stop="$emit('debug')"
        class="p-1 rounded text-content-muted hover:text-purple-500 hover:bg-purple-500/10 transition-colors"
        title="Debug view"
      >
        <BugAntIcon class="w-3.5 h-3.5" />
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { TrashIcon, BugAntIcon, PencilSquareIcon, ArrowPathRoundedSquareIcon, HandThumbUpIcon, HandThumbDownIcon } from '@heroicons/vue/24/outline'
import { devModeRef } from '../../appConfig'
import { useFeedback } from '../../composables/useFeedback'

const { thumbsEnabled, thumbsDisabledReason } = useFeedback()

const hovered = ref(false)

defineProps({
  itemId: {
    type: Number,
    default: null
  },
  align: {
    type: String,
    default: 'left' // 'left' or 'right'
  },
  showActions: {
    type: Boolean,
    default: true
  },
  showEdit: {
    type: Boolean,
    default: false
  },
  showReplay: {
    type: Boolean,
    default: false
  },
  showThumbs: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['edit', 'replay', 'delete', 'delete-from-here', 'debug', 'thumb'])

function handleTrash(event) {
  if (event.shiftKey) {
    emit('delete-from-here')
  } else {
    emit('delete')
  }
}

function handleThumb(direction) {
  if (!thumbsEnabled.value) return
  emit('thumb', direction)
}
</script>
