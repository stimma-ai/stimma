<script setup lang="ts">
/**
 * A popover anchored to a viewport POINT instead of a trigger element — the
 * pen's quick brush picker, opened beside the cursor by a stylus side button.
 *
 * Positioning follows ToolbarPopover's discipline: teleported to body, parked
 * off-screen until measured, then placed against the point — preferring the
 * right of it, flipping left when the screen edge cannot hold it, and
 * clamping vertically so a tall panel scrolls itself instead of running off
 * the bottom. The vertical bias puts the panel's upper third at the pointer,
 * which lands the preset grid under the pen.
 */
import { consumeEscape, isTopmostEscapeLayer } from '../../utils/escapeLayers'
import { ref, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'

const props = withDefaults(defineProps<{
  x: number
  y: number
  width?: number
}>(), {
  width: 336,
})

const emit = defineEmits<{ (e: 'close'): void }>()

const panel = ref<HTMLElement | null>(null)

/** Gap between the pointer and the panel, and from the viewport edge. */
const GAP = 18
const MARGIN = 8

function hidden(): Record<string, string> {
  return {
    position: 'fixed',
    left: '-9999px',
    top: '0px',
    width: `${props.width}px`,
    visibility: 'hidden',
  }
}

const style = ref<Record<string, string>>(hidden())

function place() {
  const width = props.width
  const height = panel.value?.offsetHeight ?? 0

  let left = props.x + GAP
  if (left + width > window.innerWidth - MARGIN) left = props.x - GAP - width
  left = Math.max(MARGIN, Math.min(left, window.innerWidth - width - MARGIN))

  let top = props.y - Math.round(height / 3)
  top = Math.max(MARGIN, Math.min(top, window.innerHeight - height - MARGIN))

  style.value = {
    position: 'fixed',
    visibility: 'visible',
    width: `${width}px`,
    left: `${left}px`,
    top: `${top}px`,
    maxHeight: `${window.innerHeight - MARGIN * 2}px`,
  }
}

async function measureAndPlace() {
  style.value = hidden()
  // Twice: once to have a box to measure, once with the measured height.
  await nextTick()
  place()
  await nextTick()
  place()
}

watch(() => [props.x, props.y], () => { void measureAndPlace() })

function onDocumentPointerDown(event: PointerEvent) {
  const target = event.target as Node
  if (panel.value?.contains(target)) return
  emit('close')
}

function onKeydown(event: KeyboardEvent) {
  if (!event.defaultPrevented && event.key === 'Escape' && isTopmostEscapeLayer(panel.value)) {
    consumeEscape(event)
    emit('close')
  }
}

onMounted(() => {
  void measureAndPlace()
  document.addEventListener('pointerdown', onDocumentPointerDown, true)
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', place)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown, true)
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', place)
})
</script>

<template>
  <Teleport to="body">
    <div
      ref="panel" data-escape-layer
      class="z-menu overflow-y-auto rounded-lg border border-edge-subtle bg-surface shadow-xl p-3"
      :style="style"
    >
      <slot />
    </div>
  </Teleport>
</template>
