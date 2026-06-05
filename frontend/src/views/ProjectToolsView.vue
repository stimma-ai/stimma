<template>
  <AllToolsView :project-id="project.id" />
</template>

<script setup>
import AllToolsView from './AllToolsView.vue'

defineProps({
  project: {
    type: Object,
    required: true
  }
})
</script>
