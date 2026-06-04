<template>
  <div
    :class="[
      'rounded-lg border transition-colors',
      'border-edge-subtle bg-overlay-faint'
    ]"
  >
    <!-- Group header -->
    <div
      v-if="!hideHeader"
      class="flex items-center gap-1.5 px-2.5 py-1.5 cursor-grab active:cursor-grabbing"
      @pointerdown="onHeaderPointerDown"
    >
      <!-- Editable title -->
      <input
        v-if="isEditing && !fixedLabel"
        ref="titleInput"
        v-model="editLabel"
        type="text"
        class="flex-1 min-w-0 text-[11px] font-medium uppercase tracking-wide text-content-muted bg-transparent border-none outline-none focus:text-content"
        placeholder="Group name..."
        @blur="commitRename"
        @keydown.enter="commitRename"
        @keydown.escape="cancelRename"
        @click.stop
        @pointerdown.stop
      />
      <span
        v-else
        :class="[
          'flex-1 min-w-0 text-[11px] tracking-wide truncate cursor-text',
          group.label
            ? 'font-medium uppercase text-content-muted'
            : 'italic text-content-muted/50'
        ]"
        @click.stop="!fixedLabel && startRename()"
      >{{ group.label || 'Name this group...' }}</span>

      <!-- Remove group button -->
      <button
        @click.stop="$emit('remove')"
        @pointerdown.stop
        type="button"
        class="shrink-0 w-4 h-4 flex items-center justify-center text-content-muted/50 hover:!text-red-500 rounded transition-colors"
        title="Remove group"
      >
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3">
          <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
        </svg>
      </button>
    </div>

    <!-- Chips container -->
    <div :class="['grid gap-1.5 px-2 pb-2', hideHeader ? 'pt-2' : '']" :style="{ gridTemplateColumns: `repeat(auto-fill, minmax(${chipMinWidth}px, 1fr))` }">
      <slot />

      <!-- Empty state -->
      <div
        v-if="group.items.length === 0"
        class="col-span-full py-3 text-center text-[11px] text-content-muted/50"
      >
        Drag LoRAs here
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'
import type { LoraGroup } from '../../composables/useLoraPool'

interface Props {
  group: LoraGroup
  groupIndex: number
  hideHeader?: boolean
  fixedLabel?: boolean  // If true, label is not editable
  chipMinWidth?: number // Min chip width in px for grid sizing
}

const props = withDefaults(defineProps<Props>(), {
  hideHeader: false,
  fixedLabel: false,
  chipMinWidth: 300,
})

const emit = defineEmits<{
  (e: 'rename', label: string): void
  (e: 'remove'): void
  (e: 'group-drag-intent', event: PointerEvent, groupId: string): void
}>()

// Rename state
const isEditing = ref(false)
const editLabel = ref('')
const titleInput = ref<HTMLInputElement | null>(null)

// Auto-focus title on new (unnamed) groups
onMounted(() => {
  if (!props.group.label && !props.fixedLabel) {
    startRename()
  }
})

function startRename() {
  editLabel.value = props.group.label
  isEditing.value = true
  nextTick(() => {
    titleInput.value?.focus()
    titleInput.value?.select()
  })
}

function commitRename() {
  isEditing.value = false
  if (editLabel.value !== props.group.label) {
    emit('rename', editLabel.value)
  }
}

function cancelRename() {
  isEditing.value = false
}

function onHeaderPointerDown(event: PointerEvent) {
  if (event.button !== 0) return
  if (isEditing.value) return
  event.preventDefault() // Prevent text selection during drag
  emit('group-drag-intent', event, props.group.id)
}
</script>
