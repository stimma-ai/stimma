<template>
  <span
    class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] max-w-full"
    :class="variantClass"
    @mouseenter="emit('hover', true)"
    @mouseleave="emit('hover', false)"
  >
    <!-- Chat-bubble-with-plus. Same glyph as the row "Reference in chat"
         button, so a pinned chip reads as "this is what that button added." -->
    <svg
      class="w-3.5 h-3.5 flex-shrink-0"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <path d="M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z" />
      <path d="M12 9.25v5.5M9.25 12h5.5" stroke-width="2" />
    </svg>
    <span
      v-if="breadcrumb"
      class="truncate max-w-[90px]"
      :class="breadcrumbTextClass"
    >{{ breadcrumb }} ›</span>
    <span class="font-medium truncate max-w-[160px]">{{ label }}</span>
    <button
      v-if="closable"
      type="button"
      class="flex-shrink-0 w-4 h-4 rounded-full flex items-center justify-center"
      :class="closeBtnClass"
      title="Remove"
      @click.stop="emit('close')"
    >
      <svg class="w-2.5 h-2.5" viewBox="0 0 20 20" fill="currentColor">
        <path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
      </svg>
    </button>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  label: string
  breadcrumb?: string
  // `composer` — lives in the context tray above the chat input. Light blue
  //   tint so it reads on a white surface.
  // `bubble` — lives inside a sent user message (blue bubble). Translucent
  //   white tint so it reads on the blue bg.
  variant?: 'composer' | 'bubble'
  closable?: boolean
}
const props = withDefaults(defineProps<Props>(), {
  breadcrumb: '',
  variant: 'composer',
  closable: false,
})
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'hover', state: boolean): void
}>()

// Style variants share shape + icon so chips are visually the same "thing"
// across surfaces; only the color palette flips to match the surrounding
// background (white surface vs blue bubble).
const variantClass = computed(() =>
  props.variant === 'bubble'
    ? 'bg-blue-500/30 border border-blue-300/40 text-white'
    : 'bg-blue-500/10 border border-blue-500/30 text-blue-500 dark:text-blue-400',
)
const breadcrumbTextClass = computed(() =>
  props.variant === 'bubble' ? 'text-blue-100/70' : 'text-content-muted',
)
const closeBtnClass = computed(() =>
  props.variant === 'bubble'
    ? 'text-blue-100/80 hover:bg-blue-300/30 hover:text-white'
    : 'text-blue-500/80 hover:bg-blue-500/20 hover:text-blue-600 dark:hover:text-blue-300',
)
</script>
