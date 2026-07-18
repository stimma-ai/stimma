<template>
  <div>
    <div
      v-for="row in rows"
      :key="row.label"
      class="flex items-baseline justify-between gap-4 py-1.5 border-b border-edge-subtle last:border-b-0"
    >
      <span class="text-xs text-content-tertiary flex-shrink-0">{{ row.label }}</span>
      <span
        :class="[
          'text-xs text-content text-right min-w-0 select-text',
          row.mono !== false ? 'font-mono tabular-nums' : '',
          row.truncate ? 'truncate' : 'break-words',
        ]"
        :title="row.truncate ? String(row.value) : undefined"
      >{{ row.value }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
// Atelier KeyValueList — typeset read-only facts: muted sans label left,
// mono value right, hairline rules between rows. Replaces the bordered
// "field tile" treatment for read-only data (read-only facts must never
// look like form inputs). Long prose values (prompts, descriptions) don't
// belong here — this is for facts, not paragraphs.
export interface KeyValueRow {
  label: string
  value: string | number
  /** mono is the default facts voice; set false for plain-text values */
  mono?: boolean
  /** single-line ellipsis with full value in the title tooltip */
  truncate?: boolean
}

defineProps<{ rows: KeyValueRow[] }>()
</script>
