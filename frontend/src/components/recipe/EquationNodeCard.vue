<template>
  <div
    class="relative w-full h-full rounded-lg border overflow-hidden flex flex-col transition-shadow"
    :class="[cardClass, clickable ? 'cursor-pointer' : '']"
  >
    <!-- Status flag — colored bar on the left edge encodes state. Single
         channel for status; the tinted card body amplifies it at zoom-out
         without screaming up close. Running state shimmers. -->
    <div
      class="absolute left-0 top-0 bottom-0 w-[5px] rounded-l-[7px] pointer-events-none"
      :class="flagClass"
    />

    <!-- Header: type chip + title/subtitle column + optional right slot. -->
    <div class="flex items-start gap-2 px-2.5 pl-3 pt-2 pb-1 min-w-0">
      <span
        class="flex-shrink-0 inline-flex items-center px-[6px] py-[1px] rounded text-[9.5px] font-semibold tracking-wider leading-[14px] mt-[1px]"
        :class="chipClass"
      >{{ chipLabel }}</span>
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
    </div>

    <!-- Body — caller fills in media thumbnails / info markdown / chips. -->
    <div class="flex-1 min-h-0 px-2.5 pl-3 pt-1 pb-1 overflow-hidden flex items-start">
      <slot name="body" />
    </div>

    <!-- Footer: status dot + label on the left, action slot on the right. -->
    <div
      class="flex items-center justify-between gap-2 px-2.5 pl-3 py-1 mt-auto border-t flex-shrink-0"
      :class="dividerClass"
    >
      <span class="flex items-center gap-1.5 min-w-0">
        <span class="w-1.5 h-1.5 rounded-full flex-shrink-0" :class="dotClass" />
        <span
          class="text-[10.5px] truncate font-medium"
          :class="labelClass"
        >{{ statusLabel }}</span>
      </span>
      <span class="flex items-center gap-1 flex-shrink-0">
        <slot name="footer-actions" />
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface Props {
  // Status drives flag, tint, divider, dot, and label color. `null` means
  // "not present in this context" (e.g. an iteration where this body
  // position didn't apply); rendered with a dashed muted card.
  status: string | null
  chipLabel: string
  chipClass: string
  title: string
  subtitle?: string | null
  statusLabel: string
  // True when the card represents an action the user can take (e.g. an
  // awaiting-input HITL step with a live task). Pulses the dot + bumps the
  // label color so passive "preparing…" states don't read as actionable.
  actionable?: boolean
  clickable?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  subtitle: null,
  actionable: false,
  clickable: true,
})

const cardClass = computed(() => {
  switch (props.status) {
    case 'completed':      return 'bg-recipe-done-tint  border-recipe-done-soft  hover:shadow-md'
    case 'computing':      return 'bg-recipe-run-tint   border-recipe-run-soft   hover:shadow-md'
    case 'failed':         return 'bg-recipe-fail-tint  border-recipe-fail-soft  hover:shadow-md'
    case 'awaiting_input': return 'bg-recipe-await-tint border-recipe-await-soft hover:shadow-md'
    case 'invalidated':    return 'bg-recipe-stale-tint border-recipe-stale-soft hover:shadow-md'
    case 'skipped':        return 'bg-base border-edge-subtle opacity-60'
    case null:             return 'bg-base border-dashed border-edge-subtle opacity-70'
    default:               return 'bg-base border-edge-subtle hover:shadow-md'
  }
})

const flagClass = computed(() => {
  switch (props.status) {
    case 'completed':      return 'bg-recipe-done-strong'
    case 'computing':      return 'recipe-flag-running'
    case 'failed':         return 'bg-recipe-fail-strong'
    case 'awaiting_input': return 'bg-recipe-await-strong'
    case 'invalidated':    return 'bg-recipe-stale-strong'
    case 'skipped':        return 'bg-content-muted/20'
    case null:             return 'bg-content-muted/20'
    default:               return 'bg-content-muted/35'
  }
})

const dividerClass = computed(() => {
  switch (props.status) {
    case 'completed':      return 'border-recipe-done-soft'
    case 'computing':      return 'border-recipe-run-soft'
    case 'failed':         return 'border-recipe-fail-soft'
    case 'awaiting_input': return 'border-recipe-await-soft'
    case 'invalidated':    return 'border-recipe-stale-soft'
    default:               return 'border-edge-subtle'
  }
})

const dotClass = computed(() => {
  switch (props.status) {
    case 'completed':      return 'bg-recipe-done-strong'
    case 'computing':      return 'bg-recipe-run-strong recipe-dot-pulse'
    case 'failed':         return 'bg-recipe-fail-strong'
    case 'awaiting_input': return props.actionable ? 'bg-recipe-await-strong recipe-dot-pulse' : 'bg-content-muted/40'
    case 'invalidated':    return 'bg-recipe-stale-strong'
    case 'skipped':        return 'bg-content-muted/30'
    case null:             return 'bg-content-muted/30'
    default:               return 'bg-content-muted/40'
  }
})

const labelClass = computed(() => {
  switch (props.status) {
    case 'completed':      return 'text-recipe-done-strong'
    case 'computing':      return 'text-recipe-run-strong'
    case 'failed':         return 'text-recipe-fail-strong'
    case 'awaiting_input': return props.actionable ? 'text-recipe-await-strong' : 'text-content-muted/70'
    case 'invalidated':    return 'text-recipe-stale-strong'
    case 'skipped':        return 'text-content-muted/60'
    default:               return 'text-content-muted/70'
  }
})
</script>

<style scoped>
@keyframes recipe-flag-shimmer {
  0%   { background-position: 0 0%; }
  100% { background-position: 0 -120%; }
}
.recipe-flag-running {
  background: linear-gradient(
    180deg,
    var(--color-recipe-run-strong) 0%,
    var(--color-recipe-run-mid)    35%,
    var(--color-recipe-run-strong) 65%,
    var(--color-recipe-run-mid)    100%
  );
  background-size: 100% 240%;
  animation: recipe-flag-shimmer 1.8s linear infinite;
}
@keyframes recipe-dot-pulse {
  0%, 100% { transform: scale(1);   opacity: 1; }
  50%      { transform: scale(0.7); opacity: 0.5; }
}
.recipe-dot-pulse { animation: recipe-dot-pulse 1.4s ease-in-out infinite; }
</style>
