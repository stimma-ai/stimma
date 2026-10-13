<template>
  <div v-if="text">
    <div v-if="label" class="flex items-center justify-between gap-2 mb-1">
      <span class="text-xs text-content-tertiary">{{ label }}</span>
      <Tip v-if="copyButton && host.copy" text="Copy">
        <IconButton aria-label="Copy" class="!w-6 !h-6" @click="copy">
          <ClipboardDocumentIcon class="w-3.5 h-3.5" />
        </IconButton>
      </Tip>
    </div>
    <!-- Read-only prose is typeset, never boxed. A plain click copies it; a
         click that ends a text selection is a selection, not a copy request. -->
    <p
      class="m-0 text-xs leading-relaxed whitespace-pre-wrap break-words select-text"
      :class="muted ? 'text-content-tertiary' : 'text-content-secondary'"
      @click="copyOnClick"
    >{{ text }}</p>
  </div>
</template>

<script setup lang="ts">
import { ClipboardDocumentIcon } from '@heroicons/vue/24/outline'
import IconButton from '../components/ui/IconButton.vue'
import Tip from './Tip.vue'
import { useProvenanceHost } from './host.ts'

const props = withDefaults(defineProps<{
  text: string | null | undefined
  label?: string
  /** Show an explicit copy control beside the label. */
  copyButton?: boolean
  muted?: boolean
}>(), {
  label: '',
  copyButton: false,
  muted: false,
})

const host = useProvenanceHost()

function copy() {
  if (props.text && host.copy) void host.copy(props.text)
}

function copyOnClick() {
  const selection = window.getSelection()
  if (selection && !selection.isCollapsed) return
  copy()
}
</script>
