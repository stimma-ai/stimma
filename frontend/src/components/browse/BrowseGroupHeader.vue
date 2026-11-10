<script setup lang="ts">
// One group's header in the grouped Assets grid: select checkbox, project dot,
// title, span and count. Nothing else: no run labels, no narration. Clicking
// the header folds or opens the group; the checkbox selects the whole group
// (its "Made from" frames too).
import { ChevronRightIcon } from '@heroicons/vue/24/outline'
import type { SelectState } from '../../utils/groupedRows'

const props = defineProps<{
  title: string
  sub?: string
  countLabel: string
  open: boolean
  /** Set when the group belongs to a project and the list isn't grouped by project. */
  projectName?: string | null
  selectState: SelectState
  /** Something is selected: the checkbox shows at rest. */
  selecting?: boolean
}>()

const emit = defineEmits<{ toggle: [], select: [] }>()

function onKey(event: KeyboardEvent) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    emit('toggle')
  }
}
</script>

<template>
  <div
    role="button"
    tabindex="0"
    :aria-expanded="props.open"
    class="group/h flex h-full w-full cursor-pointer select-none items-end gap-2.5 px-page pb-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent/60"
    @click="emit('toggle')"
    @keydown="onKey"
  >
    <button
      type="button"
      role="checkbox"
      :aria-checked="selectState === 'all' ? 'true' : selectState === 'some' ? 'mixed' : 'false'"
      aria-label="Select group"
      title="Select group"
      class="mb-px flex-none rounded-md transition-opacity focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60"
      :class="selectState !== 'none' || selecting ? 'opacity-100' : 'opacity-0 group-hover/h:opacity-100 [[data-pointer=coarse]_&]:opacity-100'"
      @click.stop="emit('select')"
      @keydown.stop
    >
      <span
        class="flex h-5 w-5 items-center justify-center rounded-md border-2 transition-colors"
        :class="selectState === 'none' ? 'border-edge-strong hover:border-content-muted' : 'border-selection bg-selection'"
      >
        <svg v-if="selectState === 'all'" class="h-4 w-4 text-content" fill="none" viewBox="0 0 24 24" stroke-width="3" stroke="currentColor" data-stroke="own" aria-hidden="true">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
        </svg>
        <span v-else-if="selectState === 'some'" class="h-0.5 w-2.5 rounded-full bg-content" aria-hidden="true"></span>
      </span>
    </button>
    <span v-if="projectName" class="mb-[7px] h-2 w-2 flex-none rounded-full bg-content-tertiary" :title="projectName" :aria-label="projectName"></span>
    <span class="min-w-0 truncate text-lg font-semibold leading-tight text-content">{{ title }}</span>
    <span v-if="sub" class="mb-px flex-none whitespace-nowrap text-sm text-content-tertiary">{{ sub }}</span>
    <span class="mb-0.5 flex-none font-mono text-xs tabular-nums text-content-muted">{{ countLabel }}</span>
    <ChevronRightIcon
      class="mb-0.5 h-icon-inline w-icon-inline flex-none text-content-muted transition opacity-0 group-hover/h:opacity-100 [[data-pointer=coarse]_&]:opacity-100"
      :class="open ? 'rotate-90' : ''"
      aria-hidden="true"
    />
  </div>
</template>
