<template>
  <div class="min-w-0"><slot /></div>
</template>

<script setup lang="ts">
defineProps<{ kid?: string; at: Record<string, any>; node: Element }>()
</script>
