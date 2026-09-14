<template>
  <span aria-hidden="true" class="flex items-center justify-center w-8 h-8 shrink-0 text-content-secondary">
    <span v-if="language" class="font-mono text-[10px] font-semibold tracking-tight text-content-secondary">{{ language }}</span>
    <component v-else :is="icon" class="w-6 h-6" stroke-width="1.5" />
  </span>
</template>
<script setup lang="ts">
import { computed } from 'vue'
import { DocumentTextIcon, TableCellsIcon, ArchiveBoxIcon, PhotoIcon, FilmIcon, MusicalNoteIcon } from '@heroicons/vue/24/outline'
import { fileKind } from '../../utils/fileRefs'
const props = defineProps<{ name: string; mime?: string }>()
const language = computed(() => {
  const labels: Record<string, string> = { py: 'PY', json: 'JSON', js: 'JS', jsx: 'JSX', ts: 'TS', tsx: 'TSX', html: 'HTML', css: 'CSS', sql: 'SQL', sh: 'SH', yaml: 'YAML', yml: 'YAML', toml: 'TOML', xml: 'XML', rs: 'RS', go: 'GO', c: 'C', cpp: 'C++', h: 'C', java: 'JAVA', rb: 'RB' }
  return labels[props.name.toLowerCase().split('.').pop() || '']
})
const icon = computed(() => {
  switch (fileKind(props.name, props.mime)) {
    case 'table': return TableCellsIcon
    case 'zip': return ArchiveBoxIcon
    case 'image': return PhotoIcon
    case 'video': return FilmIcon
    case 'audio': return MusicalNoteIcon
    default: return DocumentTextIcon
  }
})
</script>
