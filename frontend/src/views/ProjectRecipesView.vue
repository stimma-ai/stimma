<template>
  <RecipesLandingView :project-id="project.id" />
</template>

<script setup>
import RecipesLandingView from './RecipesLandingView.vue'

defineProps({
  project: {
    type: Object,
    required: true
  }
})
</script>
