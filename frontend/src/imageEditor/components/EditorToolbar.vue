<script setup lang="ts">
/**
 * The tool families, across the top of the editor.
 *
 * Clicking a family enters its mode and opens the sub-bar directly beneath;
 * clicking the active one leaves. Entering a mode never edits the stack — the
 * step is created by the first real gesture.
 *
 * On a phone the same list is the editor's bottom bar (`bar`): labelled 64px
 * cells with an Edits cell first, because the stack is what the drawer shows
 * when no family is open. Families in `unavailable` render dimmed and report
 * the tap instead of entering; the host explains why.
 */
import { computed } from 'vue'
import { TOOL_FAMILIES } from '../stack/toolFamilies'
import type { FamilyId } from '../stack/toolFamilies'
import { sanitizeSvg } from '../../utils/sanitizeHtml'
import Tooltip from '../../components/ui/Tooltip.vue'

const props = withDefaults(defineProps<{
  active: FamilyId | null
  /** Phone layout: a labelled bottom bar instead of the desktop chip row. */
  bar?: boolean
  /** Families the bar shows but will not enter. */
  unavailable?: FamilyId[]
}>(), { bar: false, unavailable: () => [] })
const emit = defineEmits<{ select: [FamilyId]; unavailable: [FamilyId]; edits: [] }>()

const families = computed(() =>
  TOOL_FAMILIES.map(family => ({
    ...family,
    svg: sanitizeSvg(
      `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
        stroke-linecap="round" stroke-linejoin="round">${family.icon}</svg>`
    ),
  }))
)

const STACK_ICON = sanitizeSvg(
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
    stroke-linecap="round" stroke-linejoin="round">
    <path d="M12 3 3 8l9 5 9-5-9-5z"/><path d="M3 13l9 5 9-5"/><path d="M3 17.5 12 22l9-4.5"/>
  </svg>`
)

function tap(id: FamilyId) {
  if (props.unavailable.includes(id)) emit('unavailable', id)
  else emit('select', id)
}
</script>

<template>
  <!-- Phone: the bottom bar. One docked bar per screen (DESIGN.md §1.11). -->
  <div
    v-if="bar"
    class="flex items-stretch h-16 shrink-0 border-t border-edge-subtle bg-surface pb-safe px-1"
    role="toolbar"
    aria-label="Editor families"
  >
    <button
      type="button"
      class="flex-1 min-w-0 flex flex-col items-center justify-center gap-0.5 rounded-md text-[10px] font-medium leading-none border-none bg-transparent border-r border-edge-subtle mr-0.5"
      :class="active === null ? 'text-accent-hi' : 'text-content-secondary'"
      aria-label="Edits"
      :aria-pressed="active === null"
      @click="emit('edits')"
    >
      <span class="w-[22px] h-[22px] shrink-0" v-html="STACK_ICON" />
      Edits
    </button>
    <button
      v-for="family in families"
      :key="family.id"
      type="button"
      class="flex-1 min-w-0 flex flex-col items-center justify-center gap-0.5 rounded-md text-[10px] font-medium leading-none border-none bg-transparent"
      :class="[
        active === family.id ? 'text-accent-hi' : 'text-content-secondary',
        unavailable.includes(family.id) && 'opacity-35',
      ]"
      :aria-label="family.label"
      :aria-pressed="active === family.id"
      :aria-disabled="unavailable.includes(family.id) || undefined"
      @click="tap(family.id)"
    >
      <span class="w-[22px] h-[22px] shrink-0" v-html="family.svg" />
      {{ family.label }}
    </button>
  </div>

  <div v-else class="flex items-center gap-0.5">
    <Tooltip
      v-for="family in families"
      :key="family.id"
      :text="`${family.label} · ${family.key.toUpperCase()}`"
    >
      <button
        type="button"
        class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs transition-colors compact:min-h-11 compact:text-[13px] focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
        :class="active === family.id
          ? 'bg-accent/15 text-accent-hi'
          : 'text-content-secondary hover:text-content hover:bg-overlay-subtle'"
        :aria-label="family.label"
        @click="emit('select', family.id)"
      >
        <span class="w-[15px] h-[15px] shrink-0" v-html="family.svg" />
        <!-- Below ~@3xl the labels are what overflow the row; the icons plus
             tooltips carry the names alone. -->
        <span class="hidden @3xl:inline">{{ family.label }}</span>
      </button>
    </Tooltip>
  </div>
</template>
