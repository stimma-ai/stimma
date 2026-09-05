<script setup lang="ts">
/**
 * The tool families, across the top of the editor.
 *
 * Clicking a family enters its mode and opens the sub-bar directly beneath;
 * clicking the active one leaves. Entering a mode never edits the stack — the
 * step is created by the first real gesture.
 */
import { computed } from 'vue'
import { TOOL_FAMILIES } from '../stack/toolFamilies'
import type { FamilyId } from '../stack/toolFamilies'
import { sanitizeSvg } from '../../utils/sanitizeHtml'
import Tooltip from '../../components/ui/Tooltip.vue'

defineProps<{ active: FamilyId | null }>()
const emit = defineEmits<{ select: [FamilyId] }>()

const families = computed(() =>
  TOOL_FAMILIES.map(family => ({
    ...family,
    svg: sanitizeSvg(
      `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
        stroke-linecap="round" stroke-linejoin="round">${family.icon}</svg>`
    ),
  }))
)
</script>

<template>
  <div class="flex items-center gap-0.5">
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
