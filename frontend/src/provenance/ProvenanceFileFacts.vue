<template>
  <!-- File facts: what the file is. Hosts may add trailing row actions. -->
  <div v-if="rows.length">
    <h4 class="m-0 mb-1 text-xs font-semibold text-content-secondary">{{ label }}</h4>
    <KeyValueList :rows="rows">
      <template #actions="slotProps">
        <slot name="actions" v-bind="slotProps" />
      </template>
    </KeyValueList>
  </div>
</template>

<script setup lang="ts">
import KeyValueList from '../components/ui/KeyValueList.vue'
import type { ViewFact } from './types.ts'

withDefaults(defineProps<{
  rows: ViewFact[]
  label?: string
}>(), {
  label: 'File',
})
</script>
