<script setup lang="ts">
import { ref, onBeforeUnmount } from 'vue'

const props = defineProps<{
  text: string
}>()

const triggerRef = ref<HTMLElement | null>(null)
const visible = ref(false)
const top = ref(0)
const left = ref(0)
const placement = ref<'top' | 'bottom'>('top')

let showTimer: ReturnType<typeof setTimeout> | null = null

const GAP = 6

function computePosition() {
  const el = triggerRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()

  // Default: above the trigger. Flip below if there isn't room.
  const estimatedTipHeight = 28
  if (rect.top - estimatedTipHeight - GAP < 0) {
    placement.value = 'bottom'
    top.value = rect.bottom + GAP
  } else {
    placement.value = 'top'
    top.value = rect.top - GAP
  }
  left.value = rect.left + rect.width / 2
}

function scheduleShow() {
  clearTimer()
  showTimer = setTimeout(() => {
    computePosition()
    visible.value = true
  }, 450)
}

function hide() {
  clearTimer()
  visible.value = false
}

function clearTimer() {
  if (showTimer) {
    clearTimeout(showTimer)
    showTimer = null
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') hide()
}

onBeforeUnmount(() => {
  clearTimer()
})
</script>

<template>
  <span
    ref="triggerRef"
    class="inline-flex"
    @mouseenter="scheduleShow"
    @mouseleave="hide"
    @focusin="scheduleShow"
    @focusout="hide"
    @keydown="onKeydown"
  >
    <slot />
    <Teleport to="body">
      <div
        v-if="visible"
        class="fixed z-menu bg-surface-raised text-content text-[11px] px-2 py-1 rounded shadow-lg pointer-events-none whitespace-nowrap"
        :style="{
          top: `${top}px`,
          left: `${left}px`,
          transform: placement === 'top'
            ? 'translate(-50%, -100%)'
            : 'translate(-50%, 0)',
        }"
        role="tooltip"
      >
        {{ props.text }}
      </div>
    </Teleport>
  </span>
</template>
