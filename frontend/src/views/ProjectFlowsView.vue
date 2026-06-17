<template>
  <FlowsLandingView :project-id="project.id" />
</template>

<script setup>
import FlowsLandingView from './FlowsLandingView.vue'

defineProps({
  project: {
    type: Object,
    required: true
  }
})
</script>
