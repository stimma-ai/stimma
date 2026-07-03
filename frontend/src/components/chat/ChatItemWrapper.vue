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
      <ChatThumbButtons
        v-if="showThumbs"
        :agent-context="thumbAgentContext"
        :package-source="thumbPackageSource"
      />
      <!-- Branch (copy chat up to this point into a new chat) -->
      <button
        @click.stop="$emit('branch')"
        class="p-1 rounded text-content-muted hover:text-amber-500 hover:bg-amber-500/10 transition-colors"
        title="Branch chat from here"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class="w-3.5 h-3.5">
          <line x1="6" y1="3" x2="6" y2="15" />
          <circle cx="18" cy="6" r="3" />
          <circle cx="6" cy="18" r="3" />
          <path d="M18 9a9 9 0 0 1-9 9" />
        </svg>
      </button>
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
import { TrashIcon, BugAntIcon, PencilSquareIcon, ArrowPathRoundedSquareIcon } from '@heroicons/vue/24/outline'
import { devModeRef } from '../../appConfig'
import ChatThumbButtons from '@stimma/chat-thumb-buttons'

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
