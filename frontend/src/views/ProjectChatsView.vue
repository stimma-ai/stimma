<template>
  <ChatsLandingView :project-id="project.id" />
</template>

<script setup>
import ChatsLandingView from './ChatsLandingView.vue'

defineProps({
  project: {
    type: Object,
    required: true
  }
})
</script>
