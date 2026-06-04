<template>
  <router-view v-if="project" :project="project" />
</template>

<script setup>
import { onMounted, provide, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useMediaApi } from '../composables/useMediaApi'

const route = useRoute()
const { getProject } = useMediaApi()

const project = ref(null)

provide('projectRef', project)

async function loadProject() {
  project.value = await getProject(route.params.id)
}

onMounted(loadProject)
watch(() => route.params.id, loadProject)
</script>
