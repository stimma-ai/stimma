<template>
  <div class="grid gap-7 [grid-template-columns:repeat(auto-fit,minmax(240px,1fr))]"><slot /></div>
</template>

<script setup lang="ts">
defineProps<{ kid?: string; at: Record<string, any>; node: Element }>()
</script>
