<template>
  <!-- Task-type glyph (the ToolIcon set). The markup comes from the static
       glyph table, looked up by a validated key; unknown keys draw the
       default glyph. -->
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    v-html="svg"
  ></svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { getTaskTypeIconSvg } from '../utils/taskTypeIcons.ts'

const props = defineProps<{ icon: string }>()
const svg = computed(() => getTaskTypeIconSvg(props.icon))
</script>
