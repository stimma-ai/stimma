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
      <Tooltip v-if="showEdit" text="Edit message">
        <button
          @click.stop="$emit('edit')"
          class="p-1 rounded-md text-content-muted hover:text-accent hover:bg-accent/10 transition-colors focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface"
        >
          <PencilSquareIcon class="w-3.5 h-3.5" />
        </button>
      </Tooltip>
      <!-- Replay (user messages only) -->
      <Tooltip v-if="showReplay" text="Clear chat and re-send">
        <button
          @click.stop="$emit('replay')"
          class="p-1 rounded-md text-content-muted hover:text-emerald-500 hover:bg-emerald-500/10 transition-colors focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface"
        >
          <ArrowPathRoundedSquareIcon class="w-3.5 h-3.5" />
        </button>
      </Tooltip>
      <ChatThumbButtons
        v-if="showThumbs"
        :agent-context="thumbAgentContext"
        :package-source="thumbPackageSource"
      />
      <!-- Branch (copy chat up to this point into a new chat) -->
      <Tooltip text="Branch chat from here">
        <button
          @click.stop="$emit('branch')"
          class="p-1 rounded-md text-content-muted hover:text-amber-500 hover:bg-amber-500/10 transition-colors focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="w-3.5 h-3.5">
            <line x1="6" y1="3" x2="6" y2="15" />
            <circle cx="18" cy="6" r="3" />
            <circle cx="6" cy="18" r="3" />
            <path d="M18 9a9 9 0 0 1-9 9" />
          </svg>
        </button>
      </Tooltip>
      <!-- Trash -->
      <Tooltip text="Delete">
        <button
          @click.stop="handleTrash($event)"
          class="p-1 rounded-md text-content-muted hover:text-red-500 hover:bg-red-500/10 transition-colors focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface"
        >
          <TrashIcon class="w-3.5 h-3.5" />
        </button>
      </Tooltip>
      <!-- Debug (dev mode only) -->
      <Tooltip v-if="devModeRef" text="Debug view">
        <button
          @click.stop="$emit('debug')"
          class="p-1 rounded-md text-content-muted hover:text-purple-500 hover:bg-purple-500/10 transition-colors focus-visible:outline-none focus-visible:ring-2 ring-accent/60 ring-offset-1 ring-offset-surface"
        >
          <BugAntIcon class="w-3.5 h-3.5" />
        </button>
      </Tooltip>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { TrashIcon, BugAntIcon, PencilSquareIcon, ArrowPathRoundedSquareIcon } from '@heroicons/vue/24/outline'
import { devModeRef } from '../../appConfig'
import ChatThumbButtons from '@stimma/chat-thumb-buttons'
import Tooltip from '../ui/Tooltip.vue'

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
  },
  thumbAgentContext: {
    type: String,
    default: 'main'
  },
  thumbPackageSource: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['edit', 'replay', 'delete', 'delete-from-here', 'debug', 'branch'])

function handleTrash(event) {
  if (event.shiftKey) {
    emit('delete-from-here')
  } else {
    emit('delete')
  }
}

</script>
