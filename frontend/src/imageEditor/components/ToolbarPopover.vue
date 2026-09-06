<script setup lang="ts">
/**
 * A panel hanging off a toolbar chip.
 *
 * Properties that stay mutable live in the Edits inspector; properties that
 * are consumed at the moment of the gesture — which brush, which color — do
 * not belong to any step, so they hang off the toolbar instead, the way
 * Photoshop does it.
 *
 * The panel is teleported to the body and positioned against the trigger's
 * viewport rect. Absolute positioning inside the trigger's own box put a
 * 300px color picker inside a scrolling properties panel, where it was
 * clipped by the first ancestor with overflow — the picker was there, just
 * unreachable. A popover belongs above the layout, not inside it.
 */
import { ref, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'

const props = withDefaults(defineProps<{
  label: string
  width?: number
  disabled?: boolean
  ariaLabel?: string
  /** Close when a descendant marked data-close-popover is activated. */
  closeOnSelect?: boolean
  /** Icon-only triggers drop the ▾ — the icon is the whole affordance. */
  chevron?: boolean
}>(), {
  width: 248,
  disabled: false,
  ariaLabel: undefined,
  closeOnSelect: false,
  chevron: true,
})

const open = ref(false)
const root = ref<HTMLElement | null>(null)
const panel = ref<HTMLElement | null>(null)

/** Gap between the trigger and the panel, and from the viewport edge. */
const GAP = 6
const MARGIN = 8

/**
 * Parked off-screen until measured. The panel has to exist before its height
 * can be read, and a panel that existed at its natural width in body flow for
 * one frame is a full-width flash across the app.
 */
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

/**
 * Where the panel sits, measured rather than assumed.
 *
 * A toolbar trigger has the whole window to its right; the same control inside
 * the properties panel is a handful of pixels from the screen edge, and the
 * answer changes with the sidebar width. Vertically it flips above the trigger
 * when the space below cannot hold it, and caps its height either way so a
 * tall picker scrolls itself instead of running off the bottom.
 */
function place() {
  const trigger = root.value?.getBoundingClientRect()
  if (!trigger) return

  const width = props.width
  const left = Math.min(
    Math.max(MARGIN, trigger.right - width),
    Math.max(MARGIN, window.innerWidth - width - MARGIN),
  )
  // Prefer left-aligned with the trigger while that fits on screen.
  const preferred = trigger.left + width <= window.innerWidth - MARGIN ? trigger.left : left

  const below = window.innerHeight - trigger.bottom - GAP - MARGIN
  const above = trigger.top - GAP - MARGIN
  const height = panel.value?.scrollHeight ?? 0
  const flip = height > below && above > below

  style.value = {
    position: 'fixed',
    visibility: 'visible',
    width: `${width}px`,
    left: `${Math.max(MARGIN, preferred)}px`,
    maxHeight: `${Math.max(160, flip ? above : below)}px`,
    ...(flip
      ? { bottom: `${window.innerHeight - trigger.top + GAP}px` }
      : { top: `${trigger.bottom + GAP}px` }),
  }
}

watch(open, async isOpen => {
  if (!isOpen) {
    style.value = hidden()
    return
  }
  // Twice: once to have a box to measure, once with the measured height so the
  // flip decision is made against the panel's real size.
  await nextTick()
  place()
  await nextTick()
  place()
})
watch(() => props.disabled, disabled => {
  if (disabled) open.value = false
})

function onDocumentPointerDown(event: PointerEvent) {
  if (!open.value) return
  const target = event.target as Node
  if (root.value?.contains(target) || panel.value?.contains(target)) return
  // A picker launched from this panel may promote itself to a real modal
  // (the LoRA catalog does). That modal is still owned by the popover even
  // though both are teleported to body; closing the popover here would unmount
  // the modal on its first click.
  if ((target as Element).closest?.('[data-modal-layer]')) return
  open.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (document.querySelector('[data-modal-layer]')) return
  if (event.key === 'Escape') open.value = false
}

function onPanelClick(event: MouseEvent) {
  if (
    props.closeOnSelect
    && (event.target as Element).closest('[data-close-popover]')
  ) {
    open.value = false
  }
}

/** Anything that moves the trigger moves the panel with it. */
function onViewportChange() {
  if (open.value) place()
}

onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown, true)
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', onViewportChange)
  window.addEventListener('scroll', onViewportChange, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown, true)
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
})
</script>

<template>
  <div ref="root" class="relative inline-flex">
    <button
      type="button"
      class="inline-flex items-center gap-1.5 px-2 py-1.5 text-xs rounded-md transition-colors compact:min-h-11 compact:px-3 compact:text-[13px] compact:whitespace-nowrap"
      :class="disabled
        ? 'text-content-tertiary/50 cursor-default'
        : open
          ? 'bg-selection/15 text-content'
          : 'text-content-secondary hover:text-content hover:bg-overlay-subtle'"
      :disabled="disabled"
      :aria-label="ariaLabel"
      :aria-expanded="open"
      @click="open = !open"
    >
      <slot name="trigger" />
      <span v-if="label">{{ label }}</span>
      <svg v-if="chevron" viewBox="0 0 24 24" class="w-3 h-3" fill="none" stroke="currentColor" stroke-width="2">
        <path d="m6 9 6 6 6-6" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>
    <Teleport to="body">
      <div
        v-if="open"
        ref="panel"
        class="popover-panel z-menu fixed overflow-y-auto rounded-lg
               border border-edge-subtle bg-surface shadow-xl p-3"
        :style="style"
        @click="onPanelClick"
      >
        <slot />
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/*
 * The ported pickers carry their own stylesheets, written against the snapshot
 * editor's variable names. Those names alias app tokens one-for-one, so the
 * panel just republishes them rather than the pickers being rewritten.
 */
.popover-panel {
  --stimma-color-background: var(--color-surface-rgb);
  --stimma-color-foreground: var(--color-text-primary-rgb);
  --stimma-color-primary: var(--color-accent-rgb);
  --stimma-border-radius: var(--radius-md, 6px);
  --stimma-border-radius-sm: var(--radius-sm, 4px);
  --stimma-border-radius-lg: var(--radius-lg, 8px);
  --stimma-border-radius-round: 9999px;
}
</style>
