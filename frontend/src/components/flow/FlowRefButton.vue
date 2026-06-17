<template>
  <button
    type="button"
    :title="isAttached ? 'Remove from chat context' : 'Reference in chat'"
    @click.stop="onClick"
    :class="buttonClass"
  >
    <!-- Heroicons chat-bubble-oval-left, with a plus centered in the bubble -->
    <svg
      :class="iconClass"
      viewBox="0 0 24 24"
      :fill="isAttached ? 'currentColor' : 'none'"
      stroke="currentColor"
      stroke-width="1.8"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <path
        d="M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25z"
      />
      <path
        :stroke="isAttached ? 'white' : 'currentColor'"
        stroke-width="2"
        d="M12 9.25v5.5M9.25 12h5.5"
        fill="none"
      />
    </svg>
  </button>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useFlowReferences, injectFlowChatIdRef, type FlowRefKind } from '../../composables/useFlowReferences'

interface Props {
  refKey: string
  kind: FlowRefKind
  label: string
  breadcrumb?: string
  // `inline` — lives in a row's trailing action cluster alongside the rerun
  //   button. Always rendered (low opacity at rest, brighter on row hover).
  // `tile` — absolute-positioned corner button for iteration tiles. Hidden
  //   until the tile is hovered; filled-blue persists once attached.
  variant?: 'inline' | 'tile'
}
const props = withDefaults(defineProps<Props>(), {
  breadcrumb: '',
  variant: 'inline',
})

const refs = useFlowReferences(injectFlowChatIdRef())
const isAttached = computed(() => refs.has(props.refKey))

function onClick() {
  refs.toggle({
    kind: props.kind,
    refKey: props.refKey,
    label: props.label,
    breadcrumb: props.breadcrumb || undefined,
  })
}

// Styling mirrors the row's existing icon buttons (rerun, etc) so the chat
// icon reads as "one of this row's actions" rather than a bolted-on control.
const buttonClass = computed<string>(() => {
  if (props.variant === 'tile') {
    const base = 'absolute top-1 left-1 z-10 w-6 h-6 flex items-center justify-center rounded transition-opacity'
    if (isAttached.value) {
      return `${base} bg-blue-500 text-white opacity-100`
    }
    return `${base} bg-black/55 text-white/85 hover:bg-blue-500/80 hover:text-white opacity-0 group-hover/iteration-card:opacity-100`
  }
  // inline — match rerun button chrome (24×24 bordered rounded box), but
  // low-opacity at rest so the column doesn't feel crowded. Filled-blue
  // when attached so the attached state is visible without hovering.
  const base = 'flex-shrink-0 w-6 h-6 flex items-center justify-center rounded border transition-colors'
  if (isAttached.value) {
    return `${base} border-blue-500 bg-blue-500 text-white opacity-100`
  }
  return `${base} border-transparent text-content hover:bg-overlay-hover hover:border-edge-subtle`
})

const iconClass = computed<string>(() =>
  props.variant === 'tile' ? 'w-3.5 h-3.5' : 'w-3.5 h-3.5'
)
</script>
