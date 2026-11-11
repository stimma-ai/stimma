<template>
  <div v-if="text" data-testid="prompt-block">
    <!-- With a second version (the prompt as the user typed it), the switch
         takes the label's place: one prompt shows at a time, the one the
         image was made from first. -->
    <div v-if="label || hasAsTyped" class="flex items-center justify-between gap-2" :class="hasAsTyped ? 'mb-1.5' : 'mb-1'">
      <SegmentedControl
        v-if="hasAsTyped"
        v-model="shown"
        :options="VERSIONS"
        aria-label="Prompt version"
      />
      <span v-else class="text-xs text-content-tertiary">{{ label }}</span>
      <Tip v-if="copyButton && host.copy" text="Copy">
        <IconButton aria-label="Copy" class="!w-6 !h-6" @click="copy">
          <ClipboardDocumentIcon class="w-3.5 h-3.5" />
        </IconButton>
      </Tip>
    </div>
    <!-- Read-only prose is typeset, never boxed. A plain click copies it; a
         click that ends a text selection is a selection, not a copy request.
         The typed version keeps the editor's syntax colors. -->
    <p
      class="m-0 text-xs leading-relaxed whitespace-pre-wrap break-words select-text"
      :class="muted ? 'text-content-tertiary' : 'text-content-secondary'"
      :data-version="hasAsTyped ? shown : undefined"
      @click="copyOnClick"
    ><template v-if="typedShown"><span v-for="(span, i) in typedSpans" :key="i" :class="span.kind ? PROMPT_SYNTAX_CLASS[span.kind] : undefined" :data-syntax="span.kind || undefined">{{ span.text }}</span></template><template v-else>{{ text }}</template></p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ClipboardDocumentIcon } from '@heroicons/vue/24/outline'
import IconButton from '../components/ui/IconButton.vue'
import SegmentedControl from '../components/ui/SegmentedControl.vue'
import Tip from './Tip.vue'
import { useProvenanceHost } from './host.ts'
import { PROMPT_SYNTAX_CLASS, promptSyntaxSpans } from '../utils/promptSyntax.ts'

const props = withDefaults(defineProps<{
  text: string | null | undefined
  label?: string
  /** The prompt as the user typed it, when the image was made from a different one. */
  asTyped?: string | null
  /** Show an explicit copy control beside the label. */
  copyButton?: boolean
  muted?: boolean
}>(), {
  label: '',
  asTyped: null,
  copyButton: false,
  muted: false,
})

const VERSIONS = [
  { label: 'Prompt', value: 'made' },
  { label: 'As typed', value: 'typed' },
]

const host = useProvenanceHost()

const hasAsTyped = computed(() => !!props.asTyped && props.asTyped.trim() !== (props.text || '').trim())
// Each item opens on the prompt it was made from; the choice doesn't carry over.
const shown = ref<string | number>('made')
watch(() => [props.text, props.asTyped], () => { shown.value = 'made' })
const typedShown = computed(() => hasAsTyped.value && shown.value === 'typed')
const typedSpans = computed(() => (typedShown.value ? promptSyntaxSpans(props.asTyped || '') : []))
const shownText = computed(() => (typedShown.value ? props.asTyped : props.text))

function copy() {
  if (shownText.value && host.copy) void host.copy(shownText.value)
}

function copyOnClick() {
  const selection = window.getSelection()
  if (selection && !selection.isCollapsed) return
  copy()
}
</script>
