<template>
  <BoardsLandingView :project-id="project.id" />
</template>

<script setup>
import BoardsLandingView from './BoardsLandingView.vue'

defineProps({
  project: {
    type: Object,
    required: true
  }
})
</script>
