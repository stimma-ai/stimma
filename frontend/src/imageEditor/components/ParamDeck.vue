<script setup lang="ts">
/**
 * The phone deck's parameter surface (DESIGN.md §3.6a): every numeric
 * control of the open tool as a grid of cells — name and value, all visible
 * at once, nothing to scroll sideways for — and the chosen one on the dial
 * beneath. One grammar for Adjust, the brushes, the selection tools, Crop
 * and Annotate, so a phone user learns it once.
 *
 * Layout is STABLE: a host that switches between parameter sets (segments,
 * brushes, selection tools) passes `rows`, and the grid then always stands
 * that many rows tall and the dial's slot is always reserved, so a tap on a
 * segment never moves the segments — or the row beneath — out from under
 * the finger. Without `rows` the deck is content-sized, and a single
 * parameter is just the dial. The host may put extra cells in the grid
 * (Adjust's Curve) and swap the dial for something else through the `dial`
 * slot when one of those is active.
 *
 * Reset is a long press on a cell or the dial, or a double tap on the dial:
 * nothing on screen for it.
 */
import { computed, useSlots, watch } from 'vue'
import ParamDial from './ParamDial.vue'

export interface DeckParam {
  key: string
  label: string
  value: number
  min: number
  max: number
  step?: number
  default?: number
  unit?: string
  /** A hue: the dial is a spectrum. */
  hue?: boolean
  /** A swatch before the label (Mixer's bands). */
  swatch?: string
  /** A readout other than the raw value (a nonlinear slider's real-world unit). */
  format?: (value: number) => string
}

const props = withDefaults(defineProps<{
  params: DeckParam[]
  /** The key on the dial. Stale or null resolves to the first parameter. */
  active: string | null
  columns?: number
  /** Fixed layout: the grid is always this many rows and the dial slot always stands. */
  rows?: number
  disabled?: boolean
}>(), { columns: 3, rows: 0, disabled: false })

const emit = defineEmits<{
  'update:active': [string]
  /** Continuous, while dragging; also the reset value. */
  change: [key: string, value: number]
  /** The gesture ended (or a reset happened). */
  commit: [key: string]
}>()

const slots = useSlots()

/**
 * The parameter on the dial. An active key the host owns but this grid does
 * not (Adjust's curve) shows the host's slot instead; anything else that
 * fails to match falls back to the first cell so the dial is never empty.
 */
const shown = computed(() => {
  const found = props.params.find(p => p.key === props.active)
  if (found) return found
  if (slots.dial && props.active) return null
  return props.params[0] ?? null
})
watch(shown, s => { if (s && s.key !== props.active) emit('update:active', s.key) }, { immediate: true })

function readout(p: DeckParam) {
  if (p.format) return p.format(p.value)
  const step = p.step ?? 1
  const text = step < 1 ? p.value.toFixed(step < 0.1 ? 2 : 1) : String(Math.round(p.value))
  return (p.min < 0 && p.value > 0 ? '+' : '') + text + (p.unit ?? '')
}
function modified(p: DeckParam) { return p.value !== (p.default ?? 0) }
function reset(p: DeckParam) {
  emit('change', p.key, p.default ?? 0)
  emit('commit', p.key)
}

// A long press on a cell resets its parameter; the tap that ends it is not a pick.
let hold: { timer: ReturnType<typeof setTimeout>; x: number; y: number; fired: boolean } | null = null
function holdStart(p: DeckParam, event: PointerEvent) {
  holdEnd()
  hold = {
    x: event.clientX, y: event.clientY, fired: false,
    timer: setTimeout(() => {
      if (!hold) return
      hold.fired = true
      navigator.vibrate?.(10)
      reset(p)
    }, 500),
  }
}
function holdMove(event: PointerEvent) {
  if (hold && Math.hypot(event.clientX - hold.x, event.clientY - hold.y) > 8) holdEnd()
}
function holdEnd() { if (hold) { clearTimeout(hold.timer); hold = null } }
function tap(p: DeckParam) {
  if (hold?.fired) { holdEnd(); return }
  holdEnd()
  emit('update:active', p.key)
}
</script>

<template>
  <div class="flex flex-col" data-param-deck>
    <div
      v-if="rows > 0 || params.length > 1 || $slots.default"
      class="grid gap-x-1 content-start"
      :style="{
        gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
        gridAutoRows: rows > 0 ? '44px' : undefined,
        minHeight: rows > 0 ? `${rows * 44}px` : undefined,
      }"
      role="tablist"
      aria-label="Parameters"
    >
      <button
        v-for="p in params"
        :key="p.key"
        type="button"
        role="tab"
        class="min-w-0 min-h-11 px-2 rounded-md flex items-center justify-between gap-1.5 text-[13px] font-medium transition-colors"
        :class="[shown?.key === p.key ? 'bg-accent/15 text-accent-hi' : 'text-content-secondary', disabled && 'opacity-50']"
        :aria-selected="shown?.key === p.key"
        :data-param-chip="p.key"
        :disabled="disabled"
        @pointerdown="holdStart(p, $event)"
        @pointermove="holdMove"
        @pointerup="holdEnd"
        @pointercancel="holdEnd"
        @contextmenu.prevent
        @click="tap(p)"
      >
        <span class="flex items-center gap-1.5 min-w-0">
          <span v-if="p.swatch" class="w-2.5 h-2.5 rounded-full shrink-0" :style="{ background: p.swatch }" />
          <span class="truncate">{{ p.label }}</span>
        </span>
        <span
          class="font-mono text-xs tabular-nums shrink-0"
          :class="shown?.key === p.key || modified(p) ? 'text-accent-hi' : 'text-content-tertiary'"
        >{{ readout(p) }}</span>
      </button>
      <slot />
    </div>
    <slot v-if="!shown && active && $slots.dial" name="dial" />
    <div v-else-if="!shown && rows > 0" class="h-[52px]" aria-hidden="true" />
    <ParamDial
      v-else
      :label="shown.label"
      :value="shown.value"
      :min="shown.min"
      :max="shown.max"
      :step="shown.step ?? 1"
      :default="shown.default ?? 0"
      :unit="shown.unit ?? ''"
      :readout="shown.format ? shown.format(shown.value) : undefined"
      :hue="!!shown.hue"
      :disabled="disabled"
      @input="emit('change', shown!.key, $event)"
      @commit="emit('commit', shown!.key)"
      @reset="reset(shown!)"
    />
  </div>
</template>
