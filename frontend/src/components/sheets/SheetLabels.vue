<template>
  <span class="flex flex-wrap gap-1" role="group" aria-label="Labels">
    <button
      v-for="label in labels"
      :key="label"
      type="button"
      class="flex max-w-full items-center gap-1 rounded-full ring-1 ring-inset transition-colors disabled:cursor-default"
      :class="[
        large ? 'h-9 px-3 text-[12px]' : 'h-[22px] px-2 text-[11px] coarse:h-8',
        isOn(label) ? 'bg-accent/15 text-accent-hi ring-accent-hi/45' : 'text-content-tertiary ring-edge hover:text-content hover:ring-edge-strong',
      ]"
      :aria-pressed="isOn(label)"
      :disabled="sheet.readonly.value"
      @click.stop="sheet.toggleLabel(anchor, label)"
    >
      <CheckIcon v-if="isOn(label)" :class="large ? 'h-3.5 w-3.5' : 'h-3 w-3'" stroke-width="2.5" /><span class="truncate">{{ label }}</span>
    </button>
    <button
      v-for="check in checks || []"
      :key="check.id"
      type="button"
      class="flex max-w-full items-center gap-1 rounded-full ring-1 ring-inset transition-colors disabled:cursor-default"
      :class="[
        large ? 'h-9 px-3 text-[12px]' : 'h-[22px] px-2 text-[11px] coarse:h-8',
        checked(check.id) ? 'bg-accent/15 text-accent-hi ring-accent-hi/45' : 'text-content-tertiary ring-edge hover:text-content hover:ring-edge-strong',
      ]"
      :aria-pressed="checked(check.id)"
      :disabled="sheet.readonly.value"
      @click.stop="sheet.setAnswer(check.id, !checked(check.id))"
    >
      <CheckIcon v-if="checked(check.id)" :class="large ? 'h-3.5 w-3.5' : 'h-3 w-3'" stroke-width="2.5" /><span class="truncate">{{ check.label }}</span>
    </button>
  </span>
</template>

<script setup lang="ts">
// What can be marked on one picture: the labels the sheet defines, and any
// yes/no check the agent tied to it.
import { CheckIcon } from '@heroicons/vue/24/outline'
import type { SheetContext } from './useContactSheet'

const props = defineProps<{ sheet: SheetContext; anchor: string; labels: string[]; checks?: Array<{ id: string; label: string }>; large?: boolean }>()
const checked = (id: string) => !!props.sheet.answers.value[id]?.value
const isOn = (label: string) => !!props.sheet.reviewOf(props.anchor).labels?.includes(label)
</script>
