<script setup lang="ts">
import { ChevronDownIcon } from '@heroicons/vue/24/outline'
import { useSidebarSections } from '../../composables/useSidebarSections'

// One label recipe for every sidebar section (Projects, Pinned, Editing,
// Open): small and muted, click to collapse, the section's action on hover.
const props = defineProps<{ id: string; label: string }>()
const { isCollapsed, toggleSection } = useSidebarSections()
</script>

<template>
  <div class="group/section mt-3.5 flex h-[26px] items-center rounded pr-1 coarse:min-h-11">
    <button
      type="button"
      class="flex min-w-0 self-stretch items-center gap-1 rounded px-3 text-xs text-content-muted transition-colors hover:text-content-secondary focus-visible:outline-none focus-visible:ring-2 ring-accent/60"
      :aria-expanded="!isCollapsed(props.id)"
      @click="toggleSection(props.id)"
    >
      <span class="truncate">{{ props.label }}</span>
      <ChevronDownIcon
        class="h-2.5 w-2.5 shrink-0 transition-[transform,opacity]"
        :class="isCollapsed(props.id) ? '-rotate-90 opacity-100' : 'opacity-0 group-hover/section:opacity-100 coarse:opacity-100'"
      />
    </button>
    <div class="ml-auto flex items-center">
      <slot name="action" />
    </div>
  </div>
</template>
