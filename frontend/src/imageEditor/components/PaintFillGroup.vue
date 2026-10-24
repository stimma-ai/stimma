<script setup lang="ts">
/**
 * Paint Bucket and Gradient share one Photoshop-style tool slot.
 *
 * A quick press chooses the visible (last-used) member. Holding, right-clicking,
 * or pressing ArrowDown opens the flyout; releasing over a row chooses it in
 * the same gesture.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { consumeEscape, isTopmostEscapeLayer } from '../../utils/escapeLayers'
import Tooltip from '../../components/ui/Tooltip.vue'
import ToolIcon from './ToolIcon.vue'
import { PAINT_ENGINES, PAINT_FILL_ENGINES } from '../stack/toolFamilies'

const props = defineProps<{
  active: string
  current: string
}>()

const emit = defineEmits<{
  select: [string]
}>()

const options = PAINT_ENGINES.filter(engine =>
  (PAINT_FILL_ENGINES as readonly string[]).includes(engine.id),
)
const optionById = Object.fromEntries(options.map(option => [option.id, option]))
const visible = computed(() => optionById[props.current] ?? options[0])
const groupActive = computed(() =>
  (PAINT_FILL_ENGINES as readonly string[]).includes(props.active),
)

const HOLD_MS = 350
const open = ref(false)
let holdTimer: ReturnType<typeof setTimeout> | null = null
let press: { pointerId: number; opened: boolean } | null = null

function clearHold() {
  if (holdTimer) clearTimeout(holdTimer)
  holdTimer = null
}

function removePressListeners() {
  window.removeEventListener('pointerup', finishPress, true)
  window.removeEventListener('pointercancel', cancelPress, true)
}

function startPress(event: PointerEvent) {
  if (event.button !== 0) return
  event.preventDefault()
  event.stopPropagation()
  clearHold()
  removePressListeners()
  press = { pointerId: event.pointerId, opened: false }
  holdTimer = setTimeout(() => {
    if (!press || press.pointerId !== event.pointerId) return
    press.opened = true
    open.value = true
  }, HOLD_MS)
  window.addEventListener('pointerup', finishPress, true)
  window.addEventListener('pointercancel', cancelPress, true)
}

function finishPress(event: PointerEvent) {
  const activePress = press
  if (!activePress || activePress.pointerId !== event.pointerId) return
  clearHold()
  removePressListeners()
  press = null
  if (!activePress.opened) {
    choose(visible.value.id)
    return
  }
  const target = document.elementFromPoint(event.clientX, event.clientY)
    ?.closest<HTMLElement>('[data-paint-fill-engine]')
  const id = target?.dataset.paintFillEngine
  if (id && optionById[id]) choose(id)
}

function cancelPress(event?: PointerEvent) {
  if (event && press && event.pointerId !== press.pointerId) return
  clearHold()
  removePressListeners()
  press = null
}

function choose(id: string) {
  open.value = false
  emit('select', id)
}

function onButtonClick(event: MouseEvent) {
  // Pointer activation is completed by finishPress; detail=0 is keyboard.
  if (event.detail === 0) choose(visible.value.id)
}

function onOutsidePointerDown(event: PointerEvent) {
  if (!open.value) return
  const target = event.target as HTMLElement | null
  if (!target?.closest('[data-paint-fill-group]')) open.value = false
}

function onKeydown(event: KeyboardEvent) {
  if (!event.defaultPrevented && event.key === 'Escape' && open.value
    && isTopmostEscapeLayer(document.querySelector('[data-paint-fill-menu]'))) {
    consumeEscape(event)
    open.value = false
  }
}

onMounted(() => {
  window.addEventListener('pointerdown', onOutsidePointerDown)
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  cancelPress()
  window.removeEventListener('pointerdown', onOutsidePointerDown)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <span class="relative" data-paint-fill-group>
    <Tooltip :text="visible.hint ?? visible.label">
      <button
        type="button"
        class="relative inline-flex items-center gap-1.5 px-2 py-1.5 text-xs rounded-md
               transition-colors focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
        :class="groupActive
          ? 'bg-selection/15 text-content'
          : 'text-content-secondary hover:text-content hover:bg-overlay-subtle'"
        :aria-label="visible.label"
        :aria-pressed="groupActive"
        aria-haspopup="menu"
        :aria-expanded="open"
        @pointerdown="startPress"
        @click.prevent="onButtonClick"
        @contextmenu.prevent="open = true"
        @keydown.down.prevent="open = true"
      >
        <ToolIcon :name="visible.icon" />
        <svg
          viewBox="0 0 6 6"
          aria-hidden="true"
          class="absolute right-[3px] bottom-[3px] w-1.5 h-1.5 text-content-tertiary pointer-events-none"
        >
          <path d="M6 0v6H0z" fill="currentColor" />
        </svg>
      </button>
    </Tooltip>

    <div v-if="open" data-paint-fill-menu data-escape-layer class="absolute top-full left-1/2 -translate-x-1/2 pt-1 z-menu">
      <div
        class="flex flex-col gap-0.5 p-1 bg-surface border border-edge-subtle rounded-lg shadow-lg"
        role="menu"
      >
        <button
          v-for="option in options"
          :key="option.id"
          type="button"
          role="menuitemradio"
          :aria-checked="active === option.id"
          :data-paint-fill-engine="option.id"
          class="flex items-center gap-2 px-2 py-1.5 rounded-md text-xs whitespace-nowrap transition-colors"
          :class="active === option.id
            ? 'bg-selection/15 text-content'
            : 'text-content-secondary hover:text-content hover:bg-overlay-subtle'"
          :title="option.hint"
          @click.stop="choose(option.id)"
        >
          <ToolIcon :name="option.icon" />
          {{ option.label }}
        </button>
      </div>
    </div>
  </span>
</template>
