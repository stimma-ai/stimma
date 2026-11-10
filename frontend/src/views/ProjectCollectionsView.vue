<template>
  <CollectionsLandingView :project-id="project.id" />
</template>

<script setup>
import CollectionsLandingView from './CollectionsLandingView.vue'

defineProps({
  project: {
    type: Object,
    required: true
  }
})
</script>
