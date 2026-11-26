<template>
  <!-- The panel header's second line for an element: "Element · Character". -->
  <span>Element<template v-if="kind"> · {{ kind }}</template></span>
</template>

<script setup lang="ts">
import { computed, toRef } from 'vue'
import { kindLabel, useElement } from './useElements'

const props = defineProps<{ mediaId: number }>()
const content = useElement(toRef(props, 'mediaId'))
const kind = computed(() => kindLabel(content.value?.kind))
</script>
