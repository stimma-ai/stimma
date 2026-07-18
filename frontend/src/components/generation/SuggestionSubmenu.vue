<template>
  <Teleport to="body">
    <div
      v-if="visible"
      class="fixed inset-0 z-menu"
      @click="emit('close')"
      @keydown.escape="emit('close')"
    >
      <!-- Card popover -->
      <div
        ref="cardRef"
        class="absolute z-menu suggestion-submenu-card rounded-lg border border-edge p-3 max-w-[340px]"
        :style="menuStyle"
        @click.stop
      >
        <!-- Category header -->
        <div class="text-xs font-semibold text-content-secondary mb-2 px-0.5 text-center">
          {{ label }}
        </div>

        <!-- Pills flow layout -->
        <div class="flex flex-wrap justify-center gap-1.5 max-h-[70vh] overflow-y-auto">
          <button
            v-for="item in items"
            :key="item"
            class="px-2.5 py-1 text-xs rounded-full whitespace-nowrap transition-all duration-150
                   suggestion-submenu-pill"
            :class="{ 'opacity-50 pointer-events-none': loading }"
            @click="emit('select', item)"
          >
            {{ item }}
          </button>
        </div>

        <!-- Action buttons -->
        <div class="border-t border-edge mt-2 pt-2 flex justify-center gap-1">
          <button
            :disabled="loading"
            class="flex items-center gap-1 px-2 py-1 text-xs rounded-full whitespace-nowrap transition-all duration-150
                   text-content-muted hover:text-content-secondary suggestion-submenu-pill"
            @click="emit('refresh')"
          >
            <svg :class="['w-3 h-3', loading ? 'animate-spin' : '']" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="2" y="2" width="20" height="20" rx="3" />
              <circle cx="8" cy="8" r="1.5" fill="currentColor" stroke="none" />
              <circle cx="16" cy="8" r="1.5" fill="currentColor" stroke="none" />
              <circle cx="8" cy="16" r="1.5" fill="currentColor" stroke="none" />
              <circle cx="16" cy="16" r="1.5" fill="currentColor" stroke="none" />
              <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
            </svg>
            reroll
          </button>
          <button
            :disabled="loading || items.length === 0"
            class="flex items-center gap-1 px-2 py-1 text-xs rounded-full whitespace-nowrap transition-all duration-150
                   text-content-muted hover:text-content-secondary suggestion-submenu-pill"
            @click="emit('surprise')"
          >
            <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
            </svg>
            surprise me
          </button>
          <button
            :disabled="loading || items.length === 0"
            class="flex items-center gap-1 px-2 py-1 text-xs rounded-full whitespace-nowrap transition-all duration-150
                   text-content-muted hover:text-content-secondary suggestion-submenu-pill"
            @click="emit('wildcard')"
          >
            <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 2v8m0 4v8m-6-10h4m4 0h4M5.6 5.6l2.8 2.8m7.2 7.2l2.8 2.8M18.4 5.6l-2.8 2.8m-7.2 7.2l-2.8 2.8" />
            </svg>
            add wildcard
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'

interface Props {
  visible: boolean
  label: string
  items: string[]
  loading?: boolean
  // Anchor: horizontal center (x) plus the top/bottom edges of the pill.
  position: { x: number; top: number; bottom: number }
}

const props = withDefaults(defineProps<Props>(), {
  loading: false
})

const emit = defineEmits<{
  select: [instruction: string]
  refresh: []
  surprise: []
  wildcard: []
  close: []
}>()

const GAP = 8 // space between pill and card
const MARGIN = 8 // min distance from viewport edges

const cardRef = ref<HTMLElement | null>(null)
// Hidden until measured so it never flashes at the wrong spot.
const menuStyle = ref<Record<string, string>>({ visibility: 'hidden' })

// Measure the rendered card and place it, flipping above the anchor when
// there isn't room below, and clamping horizontally to the viewport.
function updatePosition() {
  const card = cardRef.value
  if (!card) return

  const cw = card.offsetWidth
  const ch = card.offsetHeight
  const vw = window.innerWidth
  const vh = window.innerHeight

  // Horizontal: center on the anchor, then clamp inside the viewport.
  let left = props.position.x - cw / 2
  left = Math.max(MARGIN, Math.min(left, vw - cw - MARGIN))

  // Vertical: prefer below; flip above when it fits better there.
  const spaceBelow = vh - props.position.bottom
  const spaceAbove = props.position.top
  const fitsBelow = spaceBelow >= ch + GAP + MARGIN
  const fitsAbove = spaceAbove >= ch + GAP + MARGIN

  let top: number
  if (fitsBelow || (!fitsAbove && spaceBelow >= spaceAbove)) {
    top = props.position.bottom + GAP
    if (top + ch > vh - MARGIN) top = Math.max(MARGIN, vh - ch - MARGIN)
  } else {
    top = props.position.top - GAP - ch
    if (top < MARGIN) top = MARGIN
  }

  menuStyle.value = {
    left: `${left}px`,
    top: `${top}px`,
    visibility: 'visible'
  }
}

function onViewportChange() {
  updatePosition()
}

watch(
  () => [props.visible, props.position, props.items] as const,
  async ([visible]) => {
    if (visible) {
      menuStyle.value = { visibility: 'hidden' }
      await nextTick()
      updatePosition()
      window.addEventListener('resize', onViewportChange)
      window.addEventListener('scroll', onViewportChange, true)
    } else {
      window.removeEventListener('resize', onViewportChange)
      window.removeEventListener('scroll', onViewportChange, true)
    }
  },
  { immediate: true, deep: true }
)

onBeforeUnmount(() => {
  window.removeEventListener('resize', onViewportChange)
  window.removeEventListener('scroll', onViewportChange, true)
})
</script>

<style>
/* Card container */
[data-theme="dark"] .suggestion-submenu-card {
  background-color: var(--color-surface-raised);
  box-shadow: 0 8px 24px rgba(0,0,0,0.5);
}
[data-theme="light"] .suggestion-submenu-card {
  background-color: #ffffff;
  box-shadow: 0 4px 16px rgba(0,0,0,0.1);
}

/* Pills - simple, no individual shadows */
[data-theme="dark"] .suggestion-submenu-pill {
  background-color: var(--color-surface);
  color: var(--color-text-secondary);
}
[data-theme="dark"] .suggestion-submenu-pill:hover {
  background-color: var(--color-surface-overlay);
  color: var(--color-text-primary);
}
[data-theme="light"] .suggestion-submenu-pill {
  background-color: var(--color-surface);
  color: var(--color-text-secondary);
}
[data-theme="light"] .suggestion-submenu-pill:hover {
  background-color: var(--color-surface-raised);
  color: var(--color-text-primary);
}
</style>
