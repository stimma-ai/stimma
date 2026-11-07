<template>
  <label class="mt-3 block">
    <span v-if="at.label" class="mb-1 block text-[12px] font-medium text-content-secondary">{{ at.label }}</span>
    <textarea
      v-model="value"
      rows="2"
      :placeholder="at.placeholder || ''"
      :disabled="sheet.readonly.value || !kid"
      class="block w-full resize-y rounded-lg border border-edge bg-surface px-3 py-2 text-[13px] text-content placeholder:text-content-muted focus:border-accent/60 focus:outline-none disabled:opacity-60"
    />
  </label>
</template>

<script setup lang="ts">
// <stimma-field id label placeholder>: free text for the agent.
import { computed } from 'vue'
import { useSheetContext } from './useContactSheet'

const props = defineProps<{ kid?: string; at: Record<string, any>; node: Element }>()
const sheet = useSheetContext()
const value = computed({
  get: () => (props.kid ? String(sheet.answers.value[props.kid]?.value ?? '') : ''),
  set: text => { if (props.kid) sheet.setAnswer(props.kid, text) },
})
</script>
