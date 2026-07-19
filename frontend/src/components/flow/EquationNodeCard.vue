<template>
  <div
    class="relative w-full h-full border bg-surface overflow-hidden flex flex-col transition-colors"
    :class="[cardClass, compact ? 'rounded-full' : 'rounded-[12px]', clickable ? 'cursor-pointer' : '']"
  >
    <!-- Header: type icon tile + title/subtitle column + status glyph. The
         tile says what the step IS; the corner glyph is the ONE place status
         lives (plus the running progress hairline below). In compact mode
         (small scalar nodes — seeds, sizes, code helpers) this header IS the
         whole card, vertically centered. -->
    <div
      class="flex items-center min-w-0 flex-shrink-0"
      :class="compact ? 'my-auto gap-2 pl-2 pr-3' : 'gap-2.5 px-3 pt-2.5 pb-1'"
    >
      <span
        class="flex-shrink-0 rounded-full flex items-center justify-center"
        :class="[tileClass, compact ? 'w-6 h-6' : 'w-7 h-7']"
      >
        <!-- eslint-disable-next-line vue/no-v-html — fragments come from the
             static flowNodeVisuals map, never user content. -->
        <svg
          :class="compact ? 'w-3.5 h-3.5' : 'w-4 h-4'"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.75"
          stroke-linecap="round"
          stroke-linejoin="round"
          v-html="icon"
        />
      </span>
      <div class="flex-1 min-w-0">
        <div
          class="truncate text-[12.5px] leading-tight text-content font-medium"
          :title="title"
        >{{ title }}</div>
        <div
          v-if="$slots.subtitle || subtitle"
          class="truncate text-[10.5px] leading-tight text-content-muted"
          :title="subtitle"
        >
          <slot name="subtitle">{{ subtitle }}</slot>
        </div>
      </div>
      <slot name="header-right" />
      <!-- Status glyph — done ✓ / running spinner / failed ✕ / queued dashed
           ring / your-turn pulsing dot / stale refresh. -->
      <span
        v-if="statusGlyph"
        class="flex-shrink-0 w-4 h-4 flex items-center justify-center self-start mt-0.5"
        :class="glyphClass"
      >
        <svg
          class="w-3.5 h-3.5"
          :class="statusGlyph === 'spinner' ? 'animate-spin' : statusGlyph === 'dot' && actionable ? 'flow-glyph-pulse' : ''"
          viewBox="0 0 24 24"
          :fill="statusGlyph === 'dot' ? 'currentColor' : 'none'"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <path v-if="statusGlyph === 'check'" d="M20 6 9 17l-5-5" />
          <path v-else-if="statusGlyph === 'spinner'" d="M21 12a9 9 0 1 1-6.2-8.56" />
          <path v-else-if="statusGlyph === 'x'" d="M18 6 6 18M6 6l12 12" />
          <circle v-else-if="statusGlyph === 'ring'" cx="12" cy="12" r="8.5" stroke-dasharray="2.5 4" />
          <circle v-else-if="statusGlyph === 'dot'" cx="12" cy="12" r="4.5" stroke="none" />
          <path v-else-if="statusGlyph === 'stale'" d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" />
          <path v-else-if="statusGlyph === 'minus'" d="M5 12h14" />
        </svg>
      </span>
    </div>

    <!-- Body — caller fills in media heroes / info markdown / chips. Hero
         bodies get a 12px mat on all sides and run to the card's bottom
         edge; there is no footer band under a picture. -->
    <div
      v-if="!compact"
      class="flex-1 min-h-0 px-3 pt-1 overflow-hidden flex items-start"
      :class="hero ? 'pb-3' : 'pb-1'"
    >
      <slot name="body" />
    </div>

    <!-- Footer: quiet status words (only when there's something to say) on
         the left, hover-revealed actions on the right. No rule above it, no
         dot — the header glyph already carries state. -->
    <div v-if="!compact && !hero" class="flex items-center justify-between gap-2 px-3 pb-2 pt-0.5 mt-auto flex-shrink-0 min-h-[24px]">
      <span
        class="text-[10.5px] truncate"
        :class="labelClass"
      >{{ statusLabel }}</span>
      <span class="flex items-center gap-1 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
        <slot name="footer-actions" />
      </span>
    </div>

    <!-- Hero cards move their actions onto the media as hover-revealed
         black-glass chips (§3.3 overlay grammar). -->
    <div
      v-if="hero"
      class="absolute bottom-4 right-4 z-10 flex items-center gap-0.5 rounded-md bg-black/55 backdrop-blur-sm px-1 py-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
    >
      <slot name="footer-actions" />
    </div>

    <!-- Running: a single thin progress hairline along the bottom edge. -->
    <div
      v-if="status === 'computing'"
      class="absolute bottom-0 inset-x-0 h-[2px] bg-overlay-subtle overflow-hidden pointer-events-none"
    >
      <div class="h-full w-2/5 bg-flow-run-strong flow-progress-slide" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  // Status drives the corner glyph, border (failed/awaiting only), dimming,
  // and the running progress hairline. `null` means "not present in this
  // context" (e.g. an iteration where this body position didn't apply);
  // rendered as a dashed muted card.
  status: string | null
  // Inner-SVG fragment + tile tint classes from flowNodeVisuals.
  icon: string
  tileClass: string
  title: string
  subtitle?: string | null
  // Quiet footer words ("Waiting its turn", "3 err · 2 running"). Pass ''
  // when the glyph says it all (e.g. done).
  statusLabel: string
  // True when the card represents an action the user can take (e.g. an
  // awaiting-input HITL step with a live task). Raises the card + pulses the
  // glyph so passive "preparing…" states don't read as actionable.
  actionable?: boolean
  clickable?: boolean
  // Compact = a capsule-height node that is just the header row (icon +
  // name + glyph). For plumbing-grade steps (inputs, size readers, code
  // helpers) so media-bearing nodes read as the canvas landmarks.
  compact?: boolean
  // Hero = the body is media: 12px mat, no footer band, actions overlay
  // the picture as black-glass chips on hover.
  hero?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  subtitle: null,
  actionable: false,
  clickable: true,
  compact: false,
  hero: false,
})

// One quiet surface for every node. Only two states may touch the border:
// failed (red) and actionable awaiting-input (the ONE raised card —
// elevation = actionability, §3.1). Everything else stays neutral; the
// corner glyph carries the state.
const cardClass = computed(() => {
  switch (props.status) {
    case 'failed':
      // flow-* tokens are hex vars — no /NN modifiers (they silently break);
      // the -soft variants ARE the softened border colors.
      return 'border-flow-fail-soft'
    case 'awaiting_input':
      return props.actionable
        ? 'bg-surface-raised border-accent/50 shadow-[0_0_0_4px_rgb(var(--color-accent-rgb)/0.08)]'
        : 'border-edge'
    case 'skipped':        return 'border-edge-subtle opacity-60'
    case 'pending':        return 'border-edge-subtle opacity-[0.65]'
    case null:             return 'border-dashed border-edge-subtle opacity-70'
    default:               return 'border-edge hover:border-edge-strong/60'
  }
})

type Glyph = 'check' | 'spinner' | 'x' | 'ring' | 'dot' | 'stale' | 'minus' | null

const statusGlyph = computed<Glyph>(() => {
  switch (props.status) {
    case 'completed':      return 'check'
    case 'computing':      return 'spinner'
    case 'failed':         return 'x'
    case 'pending':        return 'ring'
    case 'awaiting_input': return 'dot'
    case 'invalidated':    return 'stale'
    case 'skipped':        return 'minus'
    default:               return null
  }
})

const glyphClass = computed(() => {
  switch (props.status) {
    case 'completed':      return 'text-flow-done-strong'
    case 'computing':      return 'text-flow-run-strong'
    case 'failed':         return 'text-flow-fail-strong'
    case 'awaiting_input': return props.actionable ? 'text-accent-hi' : 'text-content-muted/60'
    case 'invalidated':    return 'text-flow-stale-strong'
    default:               return 'text-content-muted/60'
  }
})

const labelClass = computed(() => {
  switch (props.status) {
    case 'failed':         return 'text-flow-fail-strong'
    case 'awaiting_input': return props.actionable ? 'text-accent-hi font-medium' : 'text-content-muted'
    case 'invalidated':    return 'text-flow-stale-strong'
    default:               return 'text-content-muted'
  }
})
</script>

<style scoped>
@keyframes flow-progress-slide {
  0%   { margin-left: 0; }
  100% { margin-left: 60%; }
}
.flow-progress-slide {
  animation: flow-progress-slide 1.5s ease-in-out infinite alternate;
}
@keyframes flow-glyph-pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.4; }
}
.flow-glyph-pulse { animation: flow-glyph-pulse 1.6s ease-in-out infinite; }
</style>
