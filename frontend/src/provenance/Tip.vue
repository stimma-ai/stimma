<template>
  <!-- The host's tooltip when it has one (the app's kit Tooltip); a plain
       title otherwise, which needs no positioning layer outside the panel. -->
  <component :is="host.tooltip" v-if="host.tooltip" :text="text"><slot /></component>
  <span v-else class="inline-flex" :title="text"><slot /></span>
</template>

<script setup lang="ts">
import { useProvenanceHost } from './host.ts'

defineProps<{ text: string }>()
const host = useProvenanceHost()
</script>
