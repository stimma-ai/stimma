<template>
  <div>
    <div
      v-for="(row, i) in rows"
      :key="row.key ?? i"
      class="flex justify-between gap-4 py-1.5 border-b border-edge-subtle last:border-b-0"
      :class="row.actions ? 'items-center' : 'items-baseline'"
    >
      <span class="text-xs text-content-tertiary flex-shrink-0">{{ row.label }}</span>
      <div v-if="row.actions" class="ml-auto flex min-w-0 items-center justify-end gap-0.5">
        <span
          :class="[
            'text-xs text-right min-w-0 select-text',
            row.valueClass || 'text-content',
            row.mono !== false ? 'font-mono tabular-nums' : '',
            row.truncate ? 'truncate' : 'break-words',
          ]"
          :title="row.truncate ? String(row.value) : undefined"
        >{{ row.value }}</span>
        <slot name="actions" :row="row" :index="i" />
      </div>
      <span
        v-else
        :class="[
          'text-xs text-right min-w-0 select-text',
          row.valueClass || 'text-content',
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
  /** stable identity for slots and list rendering */
  key?: string
  /** render the row's compact trailing actions slot beside its value */
  actions?: boolean
  label: string
  value: string | number
  /** mono is the default facts voice; set false for plain-text values */
  mono?: boolean
  /** single-line ellipsis with full value in the title tooltip */
  truncate?: boolean
  /** semantic value color override (status green, cloud gradient…); replaces text-content */
  valueClass?: string
}

defineProps<{ rows: KeyValueRow[] }>()
</script>
