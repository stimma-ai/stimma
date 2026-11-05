<script setup lang="ts">
import { ChevronDownIcon } from '@heroicons/vue/24/outline'
import { useSidebarSections } from '../../composables/useSidebarSections'

// One label recipe for every sidebar section (Projects, Pinned, Editing,
// Open): small and muted, click to collapse, the section's action on hover.
// The label starts on the glyph column (row px-3 + the 4px glyph margin), and
// the gap above it matches the spacer between the places and the destinations
// in NavigationSidebar (both 18px of air against the rows around them).
const props = defineProps<{ id: string; label: string }>()
const { isCollapsed, toggleSection } = useSidebarSections()
</script>

<template>
  <div class="group/section mt-4 flex h-6 coarse:mt-1 items-center rounded pr-1 coarse:min-h-11">
    <button
      type="button"
      class="flex min-w-0 self-stretch items-center gap-1 rounded px-4 text-xs font-medium text-content-muted transition-colors hover:text-content-secondary focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
      :aria-expanded="!isCollapsed(props.id)"
      @click="toggleSection(props.id)"
    >
      <span class="truncate">{{ props.label }}</span>
      <ChevronDownIcon
        class="h-icon-inline w-icon-inline shrink-0 transition-[transform,opacity]"
        :class="isCollapsed(props.id) ? '-rotate-90 opacity-100' : 'opacity-0 group-hover/section:opacity-100 coarse:opacity-100'"
      />
    </button>
    <div class="ml-auto flex items-center">
      <slot name="action" />
    </div>
  </div>
</template>
