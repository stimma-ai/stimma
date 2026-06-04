<template>
  <BrowseGridView :project-id="project.id" />
</template>

<script setup>
import BrowseGridView from './BrowseGridView.vue'

defineProps({
  project: {
    type: Object,
    required: true
  }
})
</script>
