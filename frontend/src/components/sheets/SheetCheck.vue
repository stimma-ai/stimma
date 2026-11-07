<template>
  <label class="my-1 flex select-none items-center gap-2.5 rounded-md py-1 text-[13px] text-content coarse:min-h-11" :class="sheet.readonly.value ? '' : 'cursor-pointer'">
    <input v-model="on" type="checkbox" class="peer sr-only" :disabled="sheet.readonly.value || !kid">
    <span
      class="flex h-[18px] w-[18px] flex-none items-center justify-center rounded border transition-colors peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-accent/60"
      :class="on ? 'border-accent bg-accent text-white' : 'border-edge-strong bg-surface'"
    >
      <CheckIcon v-if="on" class="h-3 w-3" stroke-width="3" />
    </span>
    <span><slot /></span>
  </label>
</template>

<script setup lang="ts">
// <stimma-check id for>Label</stimma-check>: a yes/no the agent asks for.
import { computed } from 'vue'
import { CheckIcon } from '@heroicons/vue/24/outline'
import { useSheetContext } from './useContactSheet'

const props = defineProps<{ kid?: string; at: Record<string, any>; node: Element }>()
const sheet = useSheetContext()
const on = computed({
  get: () => !!(props.kid && sheet.answers.value[props.kid]?.value),
  set: value => { if (props.kid) sheet.setAnswer(props.kid, value) },
})
</script>
