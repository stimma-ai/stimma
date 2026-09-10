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
  /** Phone bar: the drawer is showing the stack (or a step's properties). */
  editsActive?: boolean
  /** Phone bar: how many steps the stack holds, as the Edits cell's badge. */
  count?: number
}>(), { bar: false, unavailable: () => [], editsActive: false, count: 0 })
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

/**
 * The phone dock's order: the three photo tools, then Generate and Adjust,
 * Annotate, and Paint last — the family a phone reaches for least.
 */
const PHONE_ORDER: FamilyId[] = ['crop', 'retouch', 'generate', 'levels', 'annotate', 'paint']
const barFamilies = computed(() =>
  PHONE_ORDER.map(id => families.value.find(family => family.id === id)!).filter(Boolean)
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
  <!-- Phone: the bottom bar. One docked bar per screen (DESIGN.md §1.11).
       The families first, then Edits behind a hairline: Edits is a peer of
       the tools (the stack is what the drawer shows when no family is open),
       never underneath them, and it wears the selection color because it
       selects a step rather than arming a tool. -->
  <div
    v-if="bar"
    class="flex items-stretch shrink-0 border-t border-edge-subtle bg-base pt-1 px-1 pb-[max(16px,var(--safe-bottom,0px))]"
    role="toolbar"
    aria-label="Editor families"
  >
    <button
      v-for="family in barFamilies"
      :key="family.id"
      type="button"
      class="flex-1 min-w-0 min-h-14 py-1.5 flex flex-col items-center justify-center gap-1.5 rounded-lg text-[10.5px] font-medium leading-none border-none transition-colors"
      :class="[
        active === family.id ? 'text-accent-hi bg-accent/15' : 'text-content-secondary bg-transparent',
        unavailable.includes(family.id) && 'opacity-35',
      ]"
      :aria-label="family.label"
      :aria-pressed="active === family.id"
      :aria-disabled="unavailable.includes(family.id) || undefined"
      @click="tap(family.id)"
    >
      <span class="w-6 h-6 shrink-0" v-html="family.svg" />
      {{ family.label }}
    </button>
    <span class="w-px shrink-0 my-3 mx-0.5 bg-edge-strong" aria-hidden="true" />
    <button
      type="button"
      class="relative flex-1 min-w-0 min-h-14 py-1.5 flex flex-col items-center justify-center gap-1.5 rounded-lg text-[10.5px] font-medium leading-none border-none transition-colors"
      :class="editsActive ? 'text-selection bg-selection/15' : 'text-content-secondary bg-transparent'"
      aria-label="Edits"
      :aria-pressed="editsActive"
      @click="emit('edits')"
    >
      <span class="w-6 h-6 shrink-0" v-html="STACK_ICON" />
      Edits
      <span
        v-if="count"
        class="absolute top-1 left-[calc(50%+6px)] min-w-[15px] h-[15px] px-1 rounded-full text-[9.5px] font-mono font-semibold flex items-center justify-center"
        :class="editsActive ? 'bg-selection text-base' : 'bg-content-tertiary text-base'"
        aria-hidden="true"
      >{{ count }}</span>
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
